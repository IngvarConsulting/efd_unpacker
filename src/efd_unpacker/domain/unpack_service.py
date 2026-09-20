"""
Сервис распаковки EFD-файлов.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import zlib
from typing import BinaryIO, Callable, Optional, Protocol

import onec_dtools

from .errors import UnpackError, UnpackErrorCode
from .writing import (
    apply_file_mode,
    reject_conflicting_entries,
    resolve_entry_path,
)
from .supply import parse_catalog


class SupplyReaderProtocol(Protocol):
    """Протокол для onec_dtools.SupplyReader."""

    def unpack(self, output_dir: str) -> None:  # pragma: no cover - протокол
        ...


SupplyReaderFactory = Callable[[BinaryIO], SupplyReaderProtocol]
POSIX_EPOCH = dt.datetime(1970, 1, 1)
# Нижняя граница, которую os.utime представляет одинаково на всех платформах.
MIN_REPRESENTABLE_MTIME = dt.datetime(1678, 1, 1)

# Права на вновь созданных файлах. mkstemp даёт 0600, и os.replace переносит
# этот режим на цель, поэтому его нужно выставлять явно — иначе распакованные
# шаблоны становятся доступны только владельцу. umask читаем один раз на
# импорте: процесс в этот момент однопоточный.

# Порция, которую zlib отдаёт за один вызов. Ограничивает пиковую память:
# без max_length один чанк входа может развернуться в гигабайты одним объектом.
MAX_DECOMPRESS_CHUNK = 4 * 1024 * 1024
# Абсолютный потолок на объём распакованных данных.
MAX_TOTAL_BYTES = 32 * 1024 * 1024 * 1024
# Потолок на степень сжатия. Применяется только после MIN_RATIO_CHECK_BYTES,
# чтобы не спотыкаться о маленькие, но хорошо сжатые архивы.
MAX_COMPRESSION_RATIO = 200
MIN_RATIO_CHECK_BYTES = 128 * 1024 * 1024


def _check_decompression_budget(total_out: int, total_in: int) -> None:
    """Прерывает распаковку, если поток разворачивается неправдоподобно сильно."""
    if total_out > MAX_TOTAL_BYTES:
        raise UnpackError(UnpackErrorCode.TOO_LARGE, {"unpacked": total_out})
    if total_out > MIN_RATIO_CHECK_BYTES and total_out > MAX_COMPRESSION_RATIO * max(total_in, 1):
        raise UnpackError(UnpackErrorCode.TOO_LARGE, {"unpacked": total_out, "packed": total_in})


def _apply_file_mtime(path: str, modified_at: Optional[dt.datetime]) -> None:
    """
    Применяет mtime к распакованному файлу.

    onec_dtools хранит даты в FILETIME (отсчёт от 1601 года) и регулярно отдаёт
    значения задолго до 1970: у всех четырёх записей tests/data/1cv8.efd дата
    именно такая. Раньше отсекание было привязано к Windows, поэтому на macOS и
    Linux os.utime получал огромное отрицательное число и выставлял файлам
    st_mtime_ns = INT64_MIN — `ls -l` показывал 1677 год. Отсекаем по
    представимому диапазону, одинаково на всех платформах.
    """
    if modified_at is None or modified_at < MIN_REPRESENTABLE_MTIME:
        return

    timestamp = (modified_at - POSIX_EPOCH).total_seconds()
    try:
        os.utime(path, (timestamp, timestamp))
    except OSError:
        # Метка времени — не повод считать распаковку неуспешной.
        pass


class SafeSupplyReader(onec_dtools.SupplyReader):
    """Совместимая обертка над onec_dtools с безопасной обработкой mtime на Windows."""

    def __init__(self, file: BinaryIO) -> None:
        super().__init__(file)
        self._cancel_check: Optional[Callable[[], bool]] = None
        self._keep: Optional[Callable[[str], bool]] = None
        self._progress: Optional[Callable[[int, str], None]] = None

    def set_progress(self, progress: Callable[[int, str], None]) -> None:
        """
        Сообщать о ходе после каждой записи.

        Между записями, а не внутри: запись ставится на место целиком через
        os.replace, и показывать половину файла как готовую было бы неверно.
        """
        self._progress = progress

    def set_filter(self, keep: Callable[[str], bool]) -> None:
        """
        Ограничить распаковку частью записей.

        Нужно для `--only cf` и для поставки с несколькими шаблонами, когда
        распаковывается один. Отбор по пути записи, а не по индексу: индексы
        сдвинутся, стоит формату добавить поле.
        """
        self._keep = keep

    def set_cancel_check(self, cancel_check: Callable[[], bool]) -> None:
        """Функция, по которой распаковка прерывается между записями."""
        self._cancel_check = cancel_check

    def _cancelled(self) -> bool:
        return self._cancel_check is not None and self._cancel_check()

    def _raise_if_cancelled(self, entry: str = "") -> None:
        if self._cancelled():
            raise UnpackError(UnpackErrorCode.CANCELLED, {"entry": entry} if entry else None)

    def unpack(self, output_dir: str) -> None:
        with tempfile.TemporaryFile() as buffer_file:
            self._inflate_to(buffer_file)
            buffer_file.seek(0)

            catalog = parse_catalog(buffer_file)
            # Поля базового класса onec_dtools остаются заполненными: на них
            # опирается код, который читает результат распаковки.
            for info in catalog.supply_info:
                self.description[info.lang] = (info.name, info.provider, info.description_path)
            self.included_files.extend(
                (entry.path, entry.modified_at, entry.size) for entry in catalog.entries
            )

            output_root = os.path.realpath(output_dir)
            written = 0

            # Сначала проверяем все имена, и только потом пишем: отклонить
            # архив на середине значит оставить пользователю половину файлов.
            src_paths = [entry.path for entry in catalog.entries]
            parts_list = [list(entry.parts) for entry in catalog.entries]
            reject_conflicting_entries(src_paths, parts_list)
            paths = [
                resolve_entry_path(output_root, src_path, parts)
                for src_path, parts in zip(src_paths, parts_list)
            ]

            for (src_path, modified_at, size), path in zip(self.included_files, paths):
                # Прерываемся между записями, а не посреди файла: каждая запись
                # ставится на место через os.replace, поэтому уже записанные
                # файлы целые. Удалять их нельзя — output_dir это общий каталог
                # шаблонов, где лежат и чужие.
                self._raise_if_cancelled(src_path)

                if self._keep is not None and not self._keep(src_path):
                    # Пропущенную запись надо перешагнуть в потоке: данные
                    # записей лежат подряд, и следующая прочиталась бы не с
                    # того места.
                    buffer_file.seek(size, os.SEEK_CUR)
                    continue

                os.makedirs(os.path.dirname(path), exist_ok=True)
                self._write_entry(buffer_file, path, src_path, size)
                _apply_file_mtime(path, modified_at)

                written += size
                if self._progress is not None:
                    self._progress(written, src_path)

    def _write_entry(self, buffer_file: BinaryIO, path: str, src_path: str, size: int) -> None:
        """
        Пишет одну запись через соседний временный файл и os.replace.

        Так при обрыве на середине (кончилось место, снят процесс) на месте
        целевого файла остаётся либо прежняя версия, либо новая целиком —
        но не обрезанная. Простой откат удалением записанного здесь не годится:
        он стёр бы пользовательские шаблоны, которые распаковка перезаписывает.
        """
        directory = os.path.dirname(path)
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".efd-", suffix=".part")

        try:
            with os.fdopen(descriptor, "wb") as out_file:
                written = 0
                while written < size:
                    # Одна запись бывает в сотни мегабайт: без опроса внутри
                    # цикла отмена не успевала сработать и закрытие окна
                    # неизбежно упиралось в terminate().
                    self._raise_if_cancelled(src_path)

                    data = buffer_file.read(min(self.CHUNK_SIZE, size - written))
                    if not data:
                        # Объявленный размер больше, чем осталось в потоке.
                        raise UnpackError(
                            UnpackErrorCode.CORRUPTED_ARCHIVE,
                            {"reason": "truncated_entry", "entry": src_path,
                             "expected": size, "actual": written},
                        )
                    written += out_file.write(data)
            apply_file_mode(temporary, path)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _inflate_to(self, buffer_file: BinaryIO) -> None:
        """Разжимает поток порциями, удерживая пиковую память и общий объём."""
        decompressor = zlib.decompressobj(-15)
        total_in = 0
        total_out = 0

        while True:
            self._raise_if_cancelled()

            chunk = self.file.read(self.CHUNK_SIZE)
            if not chunk:
                break
            total_in += len(chunk)

            data = decompressor.decompress(chunk, MAX_DECOMPRESS_CHUNK)
            while True:
                if data:
                    total_out += len(data)
                    _check_decompression_budget(total_out, total_in)
                    buffer_file.write(data)
                tail = decompressor.unconsumed_tail
                if not tail or not data:
                    break
                data = decompressor.decompress(tail, MAX_DECOMPRESS_CHUNK)

        remainder = decompressor.flush()
        if remainder:
            total_out += len(remainder)
            _check_decompression_budget(total_out, total_in)
            buffer_file.write(remainder)

        if not decompressor.eof:
            # Поток кончился раньше маркера конца: файл недокачан или обрезан.
            # Раньше это молча считалось успехом.
            raise UnpackError(
                UnpackErrorCode.CORRUPTED_ARCHIVE,
                {"reason": "truncated_stream", "unpacked": total_out},
            )


def _default_reader_factory(handle: BinaryIO) -> SupplyReaderProtocol:
    return SafeSupplyReader(handle)


class UnpackService:
    """
    Выполняет распаковку с помощью onec_dtools.SupplyReader.
    Не занимается выводом сообщений — только поднимает исключения.
    """

    def __init__(self, reader_factory: SupplyReaderFactory = _default_reader_factory) -> None:
        self._reader_factory = reader_factory

    def unpack(
        self,
        input_file: str,
        output_dir: str,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Распаковывает файл или поднимает UnpackError."""
        try:
            with open(input_file, "rb") as handle:
                self._unpack_handle(handle, output_dir, cancel_check)
        except UnpackError:
            # Уже доменная ошибка с точным кодом — переупаковывать нечего.
            raise
        except FileNotFoundError as exc:
            raise UnpackError(UnpackErrorCode.FILE_NOT_FOUND) from exc
        except PermissionError as exc:
            raise UnpackError(UnpackErrorCode.PERMISSION) from exc
        except Exception as exc:
            # str(AssertionError()) и str(MemoryError()) пусты — без запасного
            # варианта пользователь и автор issue получали «Неожиданная ошибка»
            # вообще без признака того, что именно сломалось.
            raise UnpackError(
                UnpackErrorCode.UNEXPECTED, {"error": str(exc) or type(exc).__name__}
            ) from exc

    def unpack_stream(
        self,
        handle: BinaryIO,
        output_dir: str,
        cancel_check: Optional[Callable[[], bool]] = None,
        keep: Optional[Callable[[str], bool]] = None,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        """
        Распаковывает уже открытый поток.

        Нужен, чтобы читать .efd прямо из контейнера — zip, tar, — не создавая
        его копию на диске. У самой большой из исследованных поставок эта
        копия весила бы 2.4 ГБ.
        """
        try:
            self._unpack_handle(handle, output_dir, cancel_check, keep, on_progress)
        except UnpackError:
            raise
        except FileNotFoundError as exc:
            raise UnpackError(UnpackErrorCode.FILE_NOT_FOUND) from exc
        except PermissionError as exc:
            raise UnpackError(UnpackErrorCode.PERMISSION) from exc
        except Exception as exc:
            raise UnpackError(
                UnpackErrorCode.UNEXPECTED, {"error": str(exc) or type(exc).__name__}
            ) from exc

    def _unpack_handle(
        self,
        handle: BinaryIO,
        output_dir: str,
        cancel_check: Optional[Callable[[], bool]],
        keep: Optional[Callable[[str], bool]] = None,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        reader = self._reader_factory(handle)
        if cancel_check is not None:
            setter = getattr(reader, "set_cancel_check", None)
            if setter is not None:
                setter(cancel_check)
        if keep is not None:
            # getattr, а не прямой вызов: reader_factory подменяется в тестах,
            # и подставной reader не обязан знать про отбор.
            setter = getattr(reader, "set_filter", None)
            if setter is not None:
                setter(keep)
        if on_progress is not None:
            setter = getattr(reader, "set_progress", None)
            if setter is not None:
                setter(on_progress)
        reader.unpack(output_dir)
