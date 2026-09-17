"""
Тесты базового доменного исключения.

@dataclass на наследнике Exception — ловушка: сгенерированный __eq__ обнуляет
__hash__, а __init__ dataclass'а не зовёт Exception.__init__, из-за чего args
оставался пустым при именованном вызове.
"""

import copy
import pickle

import pytest

from efd_unpacker.domain.errors import (
    DomainError,
    FileValidationCode,
    FileValidationError,
    UnpackError,
    UnpackErrorCode,
)


def test_errors_are_hashable():
    """Регресс: __hash__ был None, ошибку нельзя было положить в set."""
    errors = {
        FileValidationError(FileValidationCode.NOT_FOUND),
        UnpackError(UnpackErrorCode.PERMISSION),
    }

    assert len(errors) == 2


def test_args_are_filled_for_keyword_construction():
    """Регресс: при вызове с kwargs args == (), и traceback терял код ошибки."""
    error = FileValidationError(code=FileValidationCode.NOT_FOUND, details={"path": "a.efd"})

    assert error.args == (FileValidationCode.NOT_FOUND, {"path": "a.efd"})


def test_args_are_filled_for_positional_construction():
    error = UnpackError(UnpackErrorCode.CANCELLED)

    assert error.args == (UnpackErrorCode.CANCELLED, None)


def test_identity_comparison_is_preserved():
    """eq=False возвращает сравнение по идентичности — на значение ничто не опирается."""
    first = FileValidationError(FileValidationCode.EMPTY)
    second = FileValidationError(FileValidationCode.EMPTY)

    assert first != second
    assert first == first
    assert first.code is second.code


@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy, lambda e: pickle.loads(pickle.dumps(e))],
                         ids=["copy", "deepcopy", "pickle"])
def test_errors_survive_copying(clone):
    error = UnpackError(UnpackErrorCode.CORRUPTED_ARCHIVE, {"reason": "truncated_entry"})

    restored = clone(error)

    assert restored.code is UnpackErrorCode.CORRUPTED_ARCHIVE
    assert restored.details == {"reason": "truncated_entry"}


def test_str_keeps_code_and_details():
    error = UnpackError(UnpackErrorCode.TOO_LARGE, {"limit": 10})

    assert str(error) == "unpack_too_large: {'limit': 10}"


def test_str_without_details_is_just_the_code():
    assert str(UnpackError(UnpackErrorCode.CANCELLED)) == "unpack_cancelled"


def test_raising_and_catching_keeps_the_code():
    with pytest.raises(DomainError) as ctx:
        raise FileValidationError(FileValidationCode.NOT_READABLE, {"path": "x"})

    assert ctx.value.code is FileValidationCode.NOT_READABLE
