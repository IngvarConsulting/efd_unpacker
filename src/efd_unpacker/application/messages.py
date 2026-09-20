"""
Форматирование сообщений для CLI/GUI.
"""

from __future__ import annotations

from ..domain.errors import FileValidationCode, FileValidationError, UnpackError, UnpackErrorCode
from ..localization.translator import Translator

VALIDATION_KEYS = {
    FileValidationCode.NOT_FOUND: "File does not exist",
    FileValidationCode.NOT_A_FILE: "Path is not a file",
    FileValidationCode.INVALID_EXTENSION: "Invalid file format. Expected .efd file",
    FileValidationCode.NOT_READABLE: "No permission to read file",
    FileValidationCode.EMPTY: "File is empty",
    FileValidationCode.SIZE_UNAVAILABLE: "Cannot access file size",
    FileValidationCode.OUTPUT_PATH_EMPTY: "Output directory path is empty",
    FileValidationCode.OUTPUT_PATH_INVALID: "Invalid output directory path",
    FileValidationCode.OUTPUT_NOT_DIRECTORY: "Output path exists but is not a directory",
    FileValidationCode.OUTPUT_NOT_WRITABLE: "No permission to write to output directory",
    FileValidationCode.OUTPUT_CANNOT_CREATE: "No permission to create output directory",
    FileValidationCode.OUTPUT_CREATE_FAILED: "Failed to create output directory: %1",
}

UNPACK_KEYS = {
    UnpackErrorCode.FILE_NOT_FOUND: "File not found",
    UnpackErrorCode.PERMISSION: "Permission error",
    UnpackErrorCode.UNSAFE_ENTRY: "Archive rejected: it tries to write outside the output folder",
    UnpackErrorCode.TOO_LARGE: "Archive rejected: unpacked size exceeds the allowed limit",
    UnpackErrorCode.CORRUPTED_ARCHIVE: "Archive is damaged or incomplete: %1",
    UnpackErrorCode.CONTAINER_UNSUPPORTED: "This archive format is not supported: %1",
    UnpackErrorCode.NESTING_TOO_DEEP: "Archive rejected: too many nested archives",
    UnpackErrorCode.TOO_MANY_ENTRIES: "Archive rejected: too many files inside",
    UnpackErrorCode.CANCELLED: "Unpacking was stopped, some files were not extracted",
    UnpackErrorCode.UNEXPECTED: "Unexpected error: %1",
}

CORRUPTED_ARCHIVE_REASONS = {
    "truncated_stream": "the file is incomplete, most likely the download was interrupted",
    "truncated_header": "the file is too short to be an EFD archive",
    "unsupported_header": "unsupported format version",
    "truncated_entry": "a file inside the archive is shorter than declared",
    "duplicate_entry": "the archive contains two files with the same name",
    "entry_is_also_directory": "a file name in the archive conflicts with a folder name",
}


def format_validation_error(translator: Translator, error: FileValidationError) -> str:
    key = VALIDATION_KEYS.get(error.code)
    if key is None:
        # Новый член enum без правки таблицы раньше давал KeyError прямо внутри
        # `except FileValidationError` — падение в обработчике ошибок. Тест-страж
        # в tests/unit/test_messages.py ловит это в CI, а здесь — страховка в рантайме.
        message = translator.translate("FileValidator", "Unexpected error: %1")
        return _substitute(message, str(getattr(error.code, "value", error.code)))

    message = translator.translate("FileValidator", key)
    return _substitute(message, str((error.details or {}).get("error", "")))


def format_unpack_result(translator: Translator, success: bool, error: UnpackError | None = None) -> str:
    if success:
        return translator.translate("UnpackService", "Unpacking completed successfully")

    key = UNPACK_KEYS.get(getattr(error, "code", None), UNPACK_KEYS[UnpackErrorCode.UNEXPECTED])
    message = translator.translate("UnpackService", key)
    detail = _unpack_detail(translator, error) if error is not None else ""
    return _substitute(message, detail)


def _substitute(message: str, detail: str) -> str:
    """
    Подставляет причину вместо %1.

    Подстановка привязана к самому сообщению, а не к коду ошибки, иначе новый код
    с плейсхолдером молча покажет пользователю «%1». Если причины нет, хвост
    ` : %1` убирается целиком — «Неожиданная ошибка: » с пустым концом читается
    как обрыв.
    """
    if "%1" not in message:
        return message
    detail = detail.strip()
    return message.replace("%1", detail) if detail else message.replace(": %1", "")


def _unpack_detail(translator: Translator, error: UnpackError) -> str:
    """Короткое пояснение к ошибке распаковки для подстановки вместо %1."""
    details = error.details or {}
    if error.code is UnpackErrorCode.CONTAINER_UNSUPPORTED:
        return str(details.get("kind", ""))
    if error.code is UnpackErrorCode.CORRUPTED_ARCHIVE:
        reason = CORRUPTED_ARCHIVE_REASONS.get(details.get("reason"))
        return translator.translate("UnpackService", reason) if reason else ""
    return str(details.get("error", ""))
