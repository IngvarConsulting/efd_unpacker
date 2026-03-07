"""
Сервис распаковки EFD-файлов.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import zlib
from struct import unpack
from typing import BinaryIO, Callable, Protocol

import onec_dtools
from onec_dtools import supply_reader as supply_reader_module

from .errors import UnpackError, UnpackErrorCode


class SupplyReaderProtocol(Protocol):
    """Протокол для onec_dtools.SupplyReader."""

    def unpack(self, output_dir: str) -> None:  # pragma: no cover - протокол
        ...


SupplyReaderFactory = Callable[[BinaryIO], SupplyReaderProtocol]
POSIX_EPOCH = dt.datetime(1970, 1, 1)


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
            decompressor = zlib.decompressobj(-15)
            while True:
                chunk = self.file.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                buffer_file.write(decompressor.decompress(chunk))
            buffer_file.seek(0)

            header, supply_info_count = unpack("II", buffer_file.read(8))
            assert header == 1

            for _ in range(supply_info_count):
                lang, supply_name, provider_name, description_path = supply_reader_module.read_supply_info(buffer_file)
                self.description[lang] = supply_name, provider_name, description_path

            included_files_count = unpack("I", buffer_file.read(4))[0]
            for _ in range(included_files_count):
                self.included_files.append(supply_reader_module.read_included_file_info(buffer_file))

            for src_path, modified_at, size in self.included_files:
                path = os.path.join(
                    os.path.abspath(output_dir),
                    *src_path.split("\\"),
                )

                os.makedirs(os.path.dirname(path), exist_ok=True)

                with open(path, "wb") as out_file:
                    remaining = size
                    while remaining > 0:
                        chunk_size = min(self.CHUNK_SIZE, remaining)
                        out_file.write(buffer_file.read(chunk_size))
                        remaining -= chunk_size

                _apply_file_mtime(path, modified_at)


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
        except FileNotFoundError as exc:
            raise UnpackError(UnpackErrorCode.FILE_NOT_FOUND) from exc
        except PermissionError as exc:
            raise UnpackError(UnpackErrorCode.PERMISSION) from exc
        except Exception as exc:  # pragma: no cover - неожиданные ошибки
            raise UnpackError(UnpackErrorCode.UNEXPECTED, {"error": str(exc)}) from exc
