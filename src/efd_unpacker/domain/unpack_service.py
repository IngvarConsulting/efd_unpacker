"""
Сервис распаковки EFD-файлов.
"""

from __future__ import annotations

from typing import BinaryIO, Callable, Protocol

import onec_dtools

from .errors import UnpackError, UnpackErrorCode


class SupplyReaderProtocol(Protocol):
    """Протокол для onec_dtools.SupplyReader."""

    def unpack(self, output_dir: str) -> None:  # pragma: no cover - протокол
        ...


SupplyReaderFactory = Callable[[BinaryIO], SupplyReaderProtocol]


def _default_reader_factory(handle: BinaryIO) -> SupplyReaderProtocol:
    return onec_dtools.SupplyReader(handle)


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
