"""
Тесты форматирования сообщений.

Главный здесь — страж полноты таблиц: до него добавление члена в enum без
правки messages.py давало KeyError изнутри `except FileValidationError`,
то есть падение прямо в обработчике ошибок.
"""

from pathlib import Path

import pytest

from efd_unpacker.application import messages
from efd_unpacker.application.messages import format_unpack_result, format_validation_error
from efd_unpacker.domain.errors import (
    FileValidationCode,
    FileValidationError,
    UnpackError,
    UnpackErrorCode,
)
from efd_unpacker.localization.translator import Translator

TRANSLATIONS_DIR = str(Path(__file__).resolve().parents[2] / "translations")


class PassthroughTranslator:
    def translate(self, _context: str, source: str) -> str:
        return source


def russian() -> Translator:
    return Translator(lang="ru", translations_dir=TRANSLATIONS_DIR)


@pytest.fixture(params=[PassthroughTranslator, russian], ids=["passthrough", "ru"])
def translator(request):
    return request.param()


@pytest.mark.parametrize("code", list(FileValidationCode), ids=lambda code: code.name)
def test_every_validation_code_has_a_message(translator, code):
    """Новый член enum без правки VALIDATION_KEYS обязан ронять CI, а не рантайм."""
    assert code in messages.VALIDATION_KEYS, f"{code.name} нет в VALIDATION_KEYS"

    result = format_validation_error(translator, FileValidationError(code))

    assert result.strip()
    assert "%1" not in result
    assert not result.rstrip().endswith(":")


@pytest.mark.parametrize("code", list(UnpackErrorCode), ids=lambda code: code.name)
def test_every_unpack_code_has_a_message(translator, code):
    assert code in messages.UNPACK_KEYS, f"{code.name} нет в UNPACK_KEYS"

    result = format_unpack_result(translator, success=False, error=UnpackError(code))

    assert result.strip()
    assert "%1" not in result
    assert not result.rstrip().endswith(":")


def test_unknown_validation_code_does_not_raise_inside_the_error_handler():
    """
    Регресс: таблица индексировалась через [error.code] без .get, и чужой код
    давал KeyError там, где уже обрабатывалась ошибка.
    """
    error = FileValidationError(UnpackErrorCode.PERMISSION)

    result = format_validation_error(PassthroughTranslator(), error)

    assert "unpack_permission" in result
    assert "%1" not in result


def test_output_create_failed_shows_the_os_reason():
    """Причина отказа ОС должна доезжать до пользователя, а не оседать в details."""
    error = FileValidationError(
        FileValidationCode.OUTPUT_CREATE_FAILED,
        {"error": "[Errno 20] Not a directory: '/tmp/report.txt/out'"},
    )

    result = format_validation_error(russian(), error)

    assert result == "Не удалось создать папку вывода: [Errno 20] Not a directory: '/tmp/report.txt/out'"


def test_output_create_failed_without_details_drops_the_tail():
    result = format_validation_error(russian(), FileValidationError(FileValidationCode.OUTPUT_CREATE_FAILED))

    assert result == "Не удалось создать папку вывода"


def test_unexpected_error_keeps_the_exception_text():
    error = UnpackError(UnpackErrorCode.UNEXPECTED, {"error": "MemoryError"})

    assert format_unpack_result(russian(), success=False, error=error) == "Неожиданная ошибка: MemoryError"


def test_unpack_result_without_error_object_stays_readable():
    """GUI зовёт форматирование и без объекта ошибки — «Неожиданная ошибка: » недопустимо."""
    result = format_unpack_result(russian(), success=False)

    assert result == "Неожиданная ошибка"


def test_corrupted_archive_reason_is_translated():
    error = UnpackError(UnpackErrorCode.CORRUPTED_ARCHIVE, {"reason": "truncated_entry"})

    result = format_unpack_result(russian(), success=False, error=error)

    assert "%1" not in result
    assert result != "Архив повреждён или неполон"
    assert len(result) > len("Архив повреждён или неполон")


def test_unknown_corruption_reason_drops_the_tail():
    """Незнакомая причина не должна оставлять двоеточие в конце строки."""
    error = UnpackError(UnpackErrorCode.CORRUPTED_ARCHIVE, {"reason": "who_knows"})

    result = format_unpack_result(russian(), success=False, error=error)

    assert "%1" not in result
    assert not result.rstrip().endswith(":")


def test_success_message_is_translated():
    assert format_unpack_result(russian(), success=True) == "Распаковка завершена успешно"
