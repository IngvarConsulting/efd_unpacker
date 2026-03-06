"""
Валидатор входного файла и директорий вывода.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .errors import FileValidationCode, FileValidationError


@dataclass
class FileValidator:
    """
    Валидатор файлов EFD.

    Возвращает нормализованные пути или выбрасывает FileValidationError с кодом проблемы.
    """

    extension: str = ".efd"

    @staticmethod
    def normalize_path(path: str) -> str:
        """Раскрывает `~` и приводит путь к абсолютному виду."""
        if not path:
            return path
        expanded = os.path.expanduser(path)
        return os.path.abspath(expanded)

    def validate_input_file(self, file_path: str) -> str:
        """Возвращает нормализованный путь к файлу или выбрасывает FileValidationError."""
        normalized = self.normalize_path(file_path)

        if not os.path.exists(normalized):
            raise FileValidationError(FileValidationCode.NOT_FOUND, {"path": file_path})

        if not os.path.isfile(normalized):
            raise FileValidationError(FileValidationCode.NOT_A_FILE, {"path": file_path})

        if not normalized.lower().endswith(self.extension):
            raise FileValidationError(
                FileValidationCode.INVALID_EXTENSION,
                {"path": file_path, "expected": self.extension},
            )

        if not os.access(normalized, os.R_OK):
            raise FileValidationError(FileValidationCode.NOT_READABLE, {"path": file_path})

        try:
            file_size = os.path.getsize(normalized)
        except OSError as exc:
            raise FileValidationError(FileValidationCode.SIZE_UNAVAILABLE, {"error": str(exc)}) from exc

        if file_size == 0:
            raise FileValidationError(FileValidationCode.EMPTY, {"path": file_path})

        return normalized

    def prepare_output_directory(self, output_dir: str) -> str:
        """
        Убеждается, что директория существует и доступна для записи.
        Возвращает нормализованный путь или выбрасывает FileValidationError.
        """
        if not output_dir or not output_dir.strip():
            raise FileValidationError(FileValidationCode.OUTPUT_PATH_EMPTY)

        normalized = self.normalize_path(output_dir)

        if os.path.exists(normalized):
            if not os.path.isdir(normalized):
                raise FileValidationError(FileValidationCode.OUTPUT_NOT_DIRECTORY, {"path": output_dir})
            if not os.access(normalized, os.W_OK):
                raise FileValidationError(FileValidationCode.OUTPUT_NOT_WRITABLE, {"path": output_dir})
            return normalized

        parent_dir = self._find_existing_parent(normalized)
        if not parent_dir or not os.access(parent_dir, os.W_OK):
            raise FileValidationError(FileValidationCode.OUTPUT_CANNOT_CREATE, {"parent": parent_dir})

        try:
            os.makedirs(normalized, exist_ok=True)
        except OSError as exc:
            raise FileValidationError(FileValidationCode.OUTPUT_CANNOT_CREATE, {"error": str(exc)}) from exc

        return normalized

    def get_file_info(self, file_path: str) -> Optional[dict]:
        """Возвращает информацию о файле (без выбрасывания ошибок)."""
        normalized = self.normalize_path(file_path)
        try:
            stat_result = os.stat(normalized)
        except OSError:
            return None

        return {
            "size": stat_result.st_size,
            "modified": stat_result.st_mtime,
            "created": stat_result.st_ctime,
            "readable": os.access(normalized, os.R_OK),
            "writable": os.access(normalized, os.W_OK),
        }

    @staticmethod
    def _find_existing_parent(path: str) -> Optional[str]:
        """Ищет ближайшую существующую директорию."""
        current = os.path.dirname(path)
        while current and not os.path.exists(current):
            next_parent = os.path.dirname(current)
            if next_parent == current:
                break
            current = next_parent
        return current or None
