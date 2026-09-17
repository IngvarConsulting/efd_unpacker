"""
Форматирование сообщений для CLI/GUI.
"""

from __future__ import annotations

from ..domain.errors import FileValidationCode, FileValidationError, UnpackError, UnpackErrorCode
from ..localization.translator import Translator


def format_validation_error(translator: Translator, error: FileValidationError) -> str:
    key = {
        FileValidationCode.NOT_FOUND: "File does not exist",
        FileValidationCode.NOT_A_FILE: "Path is not a file",
        FileValidationCode.INVALID_EXTENSION: "Invalid file format. Expected .efd file",
        FileValidationCode.NOT_READABLE: "No permission to read file",
        FileValidationCode.EMPTY: "File is empty",
        FileValidationCode.SIZE_UNAVAILABLE: "Cannot access file size",
        FileValidationCode.OUTPUT_PATH_EMPTY: "Output directory path is empty",
        FileValidationCode.OUTPUT_NOT_DIRECTORY: "Output path exists but is not a directory",
        FileValidationCode.OUTPUT_NOT_WRITABLE: "No permission to write to output directory",
        FileValidationCode.OUTPUT_CANNOT_CREATE: "No permission to create output directory",
    }[error.code]
    return translator.translate("FileValidator", key)


def format_unpack_result(translator: Translator, success: bool, error: UnpackError | None = None) -> str:
    if success:
        return translator.translate("UnpackService", "Unpacking completed successfully")
    if error is None:
        return translator.translate("UnpackService", "Unexpected error: %1").replace("%1", "")

    if error.code is UnpackErrorCode.FILE_NOT_FOUND:
        key = "File not found"
    elif error.code is UnpackErrorCode.PERMISSION:
        key = "Permission error"
    elif error.code is UnpackErrorCode.UNSAFE_ENTRY:
        key = "Archive rejected: it tries to write outside the output folder"
    elif error.code is UnpackErrorCode.TOO_LARGE:
        key = "Archive rejected: unpacked size exceeds the allowed limit"
    elif error.code is UnpackErrorCode.CORRUPTED_ARCHIVE:
        key = "Archive is damaged or incomplete: %1"
    elif error.code is UnpackErrorCode.CANCELLED:
        key = "Unpacking was stopped, some files were not extracted"
    else:
        key = "Unexpected error: %1"

    message = translator.translate("UnpackService", key)
    if "%1" not in message:
        return message

    # Подстановка привязана к самому сообщению, а не к конкретному коду ошибки,
    # иначе новый код с плейсхолдером молча покажет пользователю «%1».
    detail = _error_detail(translator, error)
    return message.replace("%1", detail) if detail else message.replace(": %1", "")


CORRUPTED_ARCHIVE_REASONS = {
    "truncated_stream": "the file is incomplete, most likely the download was interrupted",
    "truncated_header": "the file is too short to be an EFD archive",
    "unsupported_header": "unsupported format version",
    "truncated_entry": "a file inside the archive is shorter than declared",
    "duplicate_entry": "the archive contains two files with the same name",
    "entry_is_also_directory": "a file name in the archive conflicts with a folder name",
}


def _error_detail(translator: Translator, error: UnpackError) -> str:
    """Короткое пояснение к ошибке распаковки для подстановки вместо %1."""
    details = error.details or {}
    if error.code is UnpackErrorCode.CORRUPTED_ARCHIVE:
        reason = CORRUPTED_ARCHIVE_REASONS.get(details.get("reason"))
        return translator.translate("UnpackService", reason) if reason else ""
    return str(details.get("error", ""))
