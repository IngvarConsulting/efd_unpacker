"""
Валидатор входного файла и директорий вывода.
"""

from __future__ import annotations

import os
import tempfile
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
    def normalize_path(
        path: str,
        invalid_code: FileValidationCode = FileValidationCode.NOT_FOUND,
    ) -> str:
        """
        Раскрывает `~` и приводит путь к абсолютному виду.

        Для относительного пути `os.path.abspath` дёргает `os.getcwd()`, а тот
        падает, если рабочий каталог процесса удалён. Раньше `FileNotFoundError`
        пролетал мимо обработчиков в CLI и GUI и выходил трейсбеком.
        """
        if not path:
            return path
        try:
            return os.path.abspath(os.path.expanduser(path))
        except OSError as exc:
            raise FileValidationError(invalid_code, {"path": path, "error": str(exc)}) from exc

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

        normalized = self.normalize_path(output_dir, FileValidationCode.OUTPUT_PATH_INVALID)

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
            # Отдельный код: «не удалось создать» — не то же самое, что «нет прав».
            # Настоящая причина (Errno 20, слишком длинное имя, кончилось место)
            # раньше складывалась в details и выбрасывалась при форматировании.
            raise FileValidationError(
                FileValidationCode.OUTPUT_CREATE_FAILED, {"path": output_dir, "error": str(exc)}
            ) from exc

        self._require_writable(normalized, output_dir)
        return normalized

    @staticmethod
    def _require_writable(normalized: str, original: str) -> None:
        """
        Проверяет пробной записью, что в только что созданный каталог можно писать.

        Права на создание у родителя ничего не обещают про сам каталог: umask,
        наследуемые deny-ACE на сетевых дисках, setgid. `os.access` под ACL врёт,
        поэтому проверка — настоящим файлом.
        """
        try:
            with tempfile.TemporaryFile(dir=normalized):
                pass
        except OSError as exc:
            try:
                os.rmdir(normalized)  # не оставлять каталог-сироту, в который нельзя писать
            except OSError:
                pass
            raise FileValidationError(
                FileValidationCode.OUTPUT_NOT_WRITABLE, {"path": original, "error": str(exc)}
            ) from exc

    def get_file_info(self, file_path: str) -> Optional[dict]:
        """Возвращает информацию о файле (без выбрасывания ошибок)."""
        try:
            normalized = self.normalize_path(file_path)
            stat_result = os.stat(normalized)
        except (OSError, FileValidationError):
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
        # Именно isdir, а не exists: для /tmp/report.txt/out «родителем»
        # назначался сам файл report.txt, os.access на него давал True,
        # и makedirs падал с Errno 20 уже после проверки прав.
        current = os.path.dirname(path)
        while current and not os.path.isdir(current):
            next_parent = os.path.dirname(current)
            if next_parent == current:
                break
            current = next_parent
        return current or None
