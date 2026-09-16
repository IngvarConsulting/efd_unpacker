"""
Сервис распаковки EFD-файлов.
"""

from __future__ import annotations

import datetime as dt
import ntpath
import os
import posixpath
import sys
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


def _resolve_entry_path(output_root: str, src_path: str) -> str:
    """
    Возвращает путь записи внутри output_root или поднимает UnpackError.

    Проверка идёт через commonpath, а не через startswith: строковый префикс
    считает `/tmp/out2` находящимся внутри `/tmp/out`. realpath дополнительно
    закрывает случай, когда промежуточный каталог оказался симлинком наружу.
    """
    target = os.path.join(output_root, *_safe_relative_parts(src_path))

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


def _apply_file_mtime(path: str, modified_at: dt.datetime) -> None:
    """
    Применяет mtime к распакованному файлу.

    onec_dtools хранит даты в FILETIME и может отдавать значения до 1970 года.
    На Windows `datetime.timestamp()` и `os.utime()` для таких значений падают с
    `OSError: [Errno 22] Invalid argument`, поэтому древние timestamp там пропускаем.
    """
    if sys.platform.startswith("win") and modified_at < POSIX_EPOCH:
        return

    timestamp = (modified_at - POSIX_EPOCH).total_seconds()
    os.utime(path, (timestamp, timestamp))


class SafeSupplyReader(onec_dtools.SupplyReader):
    """Совместимая обертка над onec_dtools с безопасной обработкой mtime на Windows."""

    def unpack(self, output_dir: str) -> None:
        with tempfile.TemporaryFile() as buffer_file:
            self._inflate_to(buffer_file)
            buffer_file.seek(0)

            header, supply_info_count = unpack("II", buffer_file.read(8))
            assert header == 1

            for _ in range(supply_info_count):
                lang, supply_name, provider_name, description_path = supply_reader_module.read_supply_info(buffer_file)
                self.description[lang] = supply_name, provider_name, description_path

            included_files_count = unpack("I", buffer_file.read(4))[0]
            for _ in range(included_files_count):
                self.included_files.append(supply_reader_module.read_included_file_info(buffer_file))

            output_root = os.path.realpath(output_dir)

            # Сначала проверяем все имена, и только потом пишем: отклонить
            # архив на середине значит оставить пользователю половину файлов.
            paths = [_resolve_entry_path(output_root, entry[0]) for entry in self.included_files]

            for (src_path, modified_at, size), path in zip(self.included_files, paths):
                os.makedirs(os.path.dirname(path), exist_ok=True)

                with self._open_for_write(path) as out_file:
                    remaining = size
                    while remaining > 0:
                        chunk_size = min(self.CHUNK_SIZE, remaining)
                        out_file.write(buffer_file.read(chunk_size))
                        remaining -= chunk_size

                _apply_file_mtime(path, modified_at)

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

    @staticmethod
    def _open_for_write(path: str):
        """
        Открывает файл на запись, не следуя за симлинком в последнем компоненте.

        O_TRUNC, а не O_EXCL: повторная распаковка того же шаблона в тот же
        каталог — штатный сценарий. O_NOFOLLOW и O_BINARY берём через getattr,
        их нет на всех платформах.
        """
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_TRUNC
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0)
        )
        return os.fdopen(os.open(path, flags, 0o644), "wb")


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
