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
    OUTPUT_CREATE_FAILED = "output_create_failed"
    OUTPUT_PATH_INVALID = "output_path_invalid"


class UnpackErrorCode(Enum):
    """Коды ошибок сервиса распаковки."""

    FILE_NOT_FOUND = "unpack_file_not_found"
    PERMISSION = "unpack_permission"
    UNSAFE_ENTRY = "unpack_unsafe_entry"
    TOO_LARGE = "unpack_too_large"
    CORRUPTED_ARCHIVE = "unpack_corrupted_archive"
    CONTAINER_UNSUPPORTED = "unpack_container_unsupported"
    NESTING_TOO_DEEP = "unpack_nesting_too_deep"
    TOO_MANY_ENTRIES = "unpack_too_many_entries"
    CANCELLED = "unpack_cancelled"
    UNEXPECTED = "unpack_unexpected"


# eq=False возвращает наследуемый от Exception __hash__: сгенерированный
# dataclass'ом __eq__ ставит __hash__ = None, и ошибку нельзя положить
# ни в set, ни в ключ словаря. На сравнение ошибок по значению код
# нигде не опирается — везде сравнивается error.code.
@dataclass(eq=False)
class DomainError(Exception):
    """Базовое доменное исключение."""

    code: Enum
    details: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        # dataclass не вызывает Exception.__init__, поэтому при именованном
        # вызове args оставался пустым, и traceback терял код ошибки.
        super().__init__(self.code, self.details)

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
