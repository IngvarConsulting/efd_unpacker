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
    else:
        key = "Unexpected error: %1"

    message = translator.translate("UnpackService", key)
    if error.code is UnpackErrorCode.UNEXPECTED and error.details:
        return message.replace("%1", error.details.get("error", ""))
    return message
