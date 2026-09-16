"""
Сервис распаковки EFD-файлов.
"""

from __future__ import annotations

import datetime as dt
import ntpath
import os
import posixpath
import stat
import tempfile
import zlib
from struct import unpack
from typing import BinaryIO, Callable, List, Protocol

import onec_dtools
from onec_dtools import supply_reader as supply_reader_module

from .errors import UnpackError, UnpackErrorCode


class SupplyReaderProtocol(Protocol):
    """Протокол для onec_dtools.SupplyReader."""

    def unpack(self, output_dir: str) -> None:  # pragma: no cover - протокол
        ...


SupplyReaderFactory = Callable[[BinaryIO], SupplyReaderProtocol]
POSIX_EPOCH = dt.datetime(1970, 1, 1)
# Нижняя граница, которую os.utime представляет одинаково на всех платформах.
MIN_REPRESENTABLE_MTIME = dt.datetime(1678, 1, 1)
# Единственная версия заголовка, встречавшаяся в исследованных файлах поставки.
SUPPORTED_HEADER = 1

# Права на вновь созданных файлах. mkstemp даёт 0600, и os.replace переносит
# этот режим на цель, поэтому его нужно выставлять явно — иначе распакованные
# шаблоны становятся доступны только владельцу. umask читаем один раз на
# импорте: процесс в этот момент однопоточный.
_UMASK = os.umask(0)
os.umask(_UMASK)
DEFAULT_FILE_MODE = 0o644 & ~_UMASK

# Порция, которую zlib отдаёт за один вызов. Ограничивает пиковую память:
# без max_length один чанк входа может развернуться в гигабайты одним объектом.
MAX_DECOMPRESS_CHUNK = 4 * 1024 * 1024
# Абсолютный потолок на объём распакованных данных.
MAX_TOTAL_BYTES = 32 * 1024 * 1024 * 1024
# Потолок на степень сжатия. Применяется только после MIN_RATIO_CHECK_BYTES,
# чтобы не спотыкаться о маленькие, но хорошо сжатые архивы.
MAX_COMPRESSION_RATIO = 200
MIN_RATIO_CHECK_BYTES = 128 * 1024 * 1024


def _safe_relative_parts(src_path: str) -> List[str]:
    """
    Разбирает имя записи архива в безопасный относительный путь.

    Имена в .efd записаны в windows-стиле, но прямой слэш тоже встречается,
    поэтому режем по обоим разделителям. Любая попытка выйти за пределы
    каталога распаковки отвергается, а не исправляется молча: у нас нет
    механизма частичного отчёта, и молчаливый пропуск записи снова дал бы
    пользователю «успешную» распаковку.
    """
    if (
        ntpath.splitdrive(src_path)[0]
        or ntpath.isabs(src_path)
        or posixpath.isabs(src_path)
    ):
        raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path})

    parts: List[str] = []
    for component in src_path.replace("\\", "/").split("/"):
        if component in ("", "."):
            continue
        if component == "..":
            raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path})
        parts.append(component)

    if not parts:
        raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path})

    return parts


def _resolve_entry_path(output_root: str, src_path: str, parts: List[str]) -> str:
    """
    Возвращает путь записи внутри output_root или поднимает UnpackError.

    Проверка идёт через commonpath, а не через startswith: строковый префикс
    считает `/tmp/out2` находящимся внутри `/tmp/out`. realpath дополнительно
    закрывает случай, когда промежуточный каталог оказался симлинком наружу.
    """
    target = os.path.join(output_root, *parts)

    try:
        if os.path.commonpath([output_root, os.path.realpath(target)]) != output_root:
            raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path})
    except ValueError as exc:
        # Разные диски на Windows или смесь абсолютного и относительного пути.
        raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path}) from exc

    return target


def _check_decompression_budget(total_out: int, total_in: int) -> None:
    """Прерывает распаковку, если поток разворачивается неправдоподобно сильно."""
    if total_out > MAX_TOTAL_BYTES:
        raise UnpackError(UnpackErrorCode.TOO_LARGE, {"unpacked": total_out})
    if total_out > MIN_RATIO_CHECK_BYTES and total_out > MAX_COMPRESSION_RATIO * max(total_in, 1):
        raise UnpackError(UnpackErrorCode.TOO_LARGE, {"unpacked": total_out, "packed": total_in})


def _reject_conflicting_entries(src_paths: List[str], parts_list: List[List[str]]) -> None:
    """
    Отвергает архив, в котором записи затирают друг друга.

    Без этой проверки дубль имени молча терял первую запись, а имя, совпадающее
    с каталогом соседней записи, роняло распаковку на середине с FileExistsError
    из недр os.makedirs — то есть с сообщением «Неожиданная ошибка».

    Ключи строятся из тех же компонентов, что и целевой путь, а не из сырого
    имени: иначе `a.txt` и `./a.txt` считались бы разными записями и вторая
    молча перезаписала бы первую.

    Сравнение регистронезависимое: на APFS и NTFS `README.txt` и `readme.txt` —
    один и тот же файл.
    """
    keys = ["/".join(parts).casefold() for parts in parts_list]

    seen = set()
    for key, src_path in zip(keys, src_paths):
        if key in seen:
            raise UnpackError(
                UnpackErrorCode.CORRUPTED_ARCHIVE,
                {"reason": "duplicate_entry", "entry": src_path},
            )
        seen.add(key)

    for key, src_path in zip(keys, src_paths):
        components = key.split("/")
        for depth in range(1, len(components)):
            if "/".join(components[:depth]) in seen:
                raise UnpackError(
                    UnpackErrorCode.CORRUPTED_ARCHIVE,
                    {"reason": "entry_is_also_directory", "entry": src_path},
                )


def _apply_file_mode(temporary: str, path: str) -> None:
    """
    Выставляет режим временному файлу перед подстановкой на место цели.

    mkstemp создаёт файл с 0600, и os.replace переносит этот режим на цель.
    Если цель уже существует обычным файлом — сохраняем её режим, как делала
    прежняя запись поверх; иначе берём обычные права для новых файлов.
    lstat, а не stat: у симлинка режим брать нельзя.
    """
    mode = DEFAULT_FILE_MODE
    try:
        existing = os.lstat(path)
        if stat.S_ISREG(existing.st_mode):
            mode = stat.S_IMODE(existing.st_mode)
    except OSError:
        pass

    try:
        os.chmod(temporary, mode)
    except OSError:
        # На Windows chmod умеет немногое; права — не повод валить распаковку.
        pass


def _apply_file_mtime(path: str, modified_at: dt.datetime) -> None:
    """
    Применяет mtime к распакованному файлу.

    onec_dtools хранит даты в FILETIME (отсчёт от 1601 года) и регулярно отдаёт
    значения задолго до 1970: у всех четырёх записей tests/data/1cv8.efd дата
    именно такая. Раньше отсекание было привязано к Windows, поэтому на macOS и
    Linux os.utime получал огромное отрицательное число и выставлял файлам
    st_mtime_ns = INT64_MIN — `ls -l` показывал 1677 год. Отсекаем по
    представимому диапазону, одинаково на всех платформах.
    """
    if modified_at < MIN_REPRESENTABLE_MTIME:
        return

    timestamp = (modified_at - POSIX_EPOCH).total_seconds()
    try:
        os.utime(path, (timestamp, timestamp))
    except OSError:
        # Метка времени — не повод считать распаковку неуспешной.
        pass


class SafeSupplyReader(onec_dtools.SupplyReader):
    """Совместимая обертка над onec_dtools с безопасной обработкой mtime на Windows."""

    def unpack(self, output_dir: str) -> None:
        with tempfile.TemporaryFile() as buffer_file:
            self._inflate_to(buffer_file)
            buffer_file.seek(0)

            head = buffer_file.read(8)
            if len(head) < 8:
                raise UnpackError(
                    UnpackErrorCode.CORRUPTED_ARCHIVE,
                    {"reason": "truncated_header"},
                )

            header, supply_info_count = unpack("II", head)
            if header != SUPPORTED_HEADER:
                # Раньше здесь стоял assert: под -O он исчезал вовсе, а при
                # срабатывании давал пользователю «Неожиданная ошибка: » без текста.
                raise UnpackError(
                    UnpackErrorCode.CORRUPTED_ARCHIVE,
                    {"reason": "unsupported_header", "header": header},
                )

            for _ in range(supply_info_count):
                lang, supply_name, provider_name, description_path = supply_reader_module.read_supply_info(buffer_file)
                self.description[lang] = supply_name, provider_name, description_path

            included_files_count = unpack("I", buffer_file.read(4))[0]
            for _ in range(included_files_count):
                self.included_files.append(supply_reader_module.read_included_file_info(buffer_file))

            output_root = os.path.realpath(output_dir)

            # Сначала проверяем все имена, и только потом пишем: отклонить
            # архив на середине значит оставить пользователю половину файлов.
            src_paths = [entry[0] for entry in self.included_files]
            parts_list = [_safe_relative_parts(src_path) for src_path in src_paths]
            _reject_conflicting_entries(src_paths, parts_list)
            paths = [
                _resolve_entry_path(output_root, src_path, parts)
                for src_path, parts in zip(src_paths, parts_list)
            ]

            for (src_path, modified_at, size), path in zip(self.included_files, paths):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                self._write_entry(buffer_file, path, src_path, size)
                _apply_file_mtime(path, modified_at)

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
                    data = buffer_file.read(min(self.CHUNK_SIZE, size - written))
                    if not data:
                        # Объявленный размер больше, чем осталось в потоке.
                        raise UnpackError(
                            UnpackErrorCode.CORRUPTED_ARCHIVE,
                            {"reason": "truncated_entry", "entry": src_path,
                             "expected": size, "actual": written},
                        )
                    written += out_file.write(data)
            _apply_file_mode(temporary, path)
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

    def unpack(self, input_file: str, output_dir: str) -> None:
        """Распаковывает файл или поднимает UnpackError."""
        try:
            with open(input_file, "rb") as handle:
                reader = self._reader_factory(handle)
                reader.unpack(output_dir)
        except UnpackError:
            # Уже доменная ошибка с точным кодом — переупаковывать нечего.
            raise
        except FileNotFoundError as exc:
            raise UnpackError(UnpackErrorCode.FILE_NOT_FOUND) from exc
        except PermissionError as exc:
            raise UnpackError(UnpackErrorCode.PERMISSION) from exc
        except Exception as exc:  # pragma: no cover - неожиданные ошибки
            raise UnpackError(UnpackErrorCode.UNEXPECTED, {"error": str(exc)}) from exc
