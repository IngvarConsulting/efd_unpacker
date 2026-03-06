"""
Доменные исключения и коды ошибок.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class FileValidationCode(Enum):
    """Коды ошибок валидации входного файла/директории."""

    NOT_FOUND = "file_not_found"
    NOT_A_FILE = "not_a_file"
    INVALID_EXTENSION = "invalid_extension"
    NOT_READABLE = "not_readable"
    EMPTY = "file_empty"
    SIZE_UNAVAILABLE = "size_unavailable"
    OUTPUT_PATH_EMPTY = "output_path_empty"
    OUTPUT_NOT_DIRECTORY = "output_not_directory"
    OUTPUT_NOT_WRITABLE = "output_not_writable"
    OUTPUT_CANNOT_CREATE = "output_cannot_create"


class UnpackErrorCode(Enum):
    """Коды ошибок сервиса распаковки."""

    FILE_NOT_FOUND = "unpack_file_not_found"
    PERMISSION = "unpack_permission"
    UNEXPECTED = "unpack_unexpected"


@dataclass
class DomainError(Exception):
    """Базовое доменное исключение."""

    code: Enum
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        base = self.code.value if isinstance(self.code, Enum) else str(self.code)
        if not self.details:
            return base
        return f"{base}: {self.details}"


class FileValidationError(DomainError):
    """Исключение валидации файлов."""

    code: FileValidationCode


class UnpackError(DomainError):
    """Исключение при распаковке."""

    code: UnpackErrorCode
