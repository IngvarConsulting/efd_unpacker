"""
Тесты точности диагностики в FileValidator.

Все проверки здесь — регрессы на #13: валидатор либо ставил ложный диагноз
(«нет прав» вместо настоящей причины ОС), либо выпускал голое OSError мимо
обработчиков, либо возвращал каталог, в который нельзя писать.
"""

import os
import shutil
import sys
import tempfile

import pytest

from efd_unpacker.application.messages import format_validation_error
from efd_unpacker.domain.errors import FileValidationCode, FileValidationError
from efd_unpacker.domain.file_validator import FileValidator
from efd_unpacker.localization.translator import Translator
from pathlib import Path

TRANSLATIONS_DIR = str(Path(__file__).resolve().parents[2] / "translations")
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="права POSIX")


@pytest.fixture
def validator():
    return FileValidator()


# --- файл в середине пути ----------------------------------------------------


def test_file_in_the_middle_of_the_path_is_not_a_parent_directory(validator, tmp_path):
    """
    Регресс: _find_existing_parent проверял exists, а не isdir, поэтому сам файл
    report.txt объявлялся родительским каталогом, os.access на него давал True,
    и makedirs падал уже после проверки прав.
    """
    report = tmp_path / "report.txt"
    report.write_text("x", encoding="utf-8")

    parent = validator._find_existing_parent(str(report / "out"))

    assert parent == str(tmp_path)


def test_creating_a_directory_under_a_file_reports_the_os_reason(validator, tmp_path):
    report = tmp_path / "report.txt"
    report.write_text("x", encoding="utf-8")

    with pytest.raises(FileValidationError) as ctx:
        validator.prepare_output_directory(str(report / "out"))

    assert ctx.value.code is FileValidationCode.OUTPUT_CREATE_FAILED
    assert ctx.value.details["error"]

    shown = format_validation_error(Translator(lang="ru", translations_dir=TRANSLATIONS_DIR), ctx.value)
    assert shown.startswith("Не удалось создать папку вывода: ")
    assert shown != "Нет прав на создание папки вывода"


def test_missing_parent_still_reports_no_permission(validator, tmp_path):
    """Ветка «родителя нет вовсе» должна остаться на прежнем коде."""
    unwritable = tmp_path / "locked"
    unwritable.mkdir()
    os.chmod(unwritable, 0o555)
    try:
        with pytest.raises(FileValidationError) as ctx:
            validator.prepare_output_directory(str(unwritable / "deep" / "out"))
        assert ctx.value.code is FileValidationCode.OUTPUT_CANNOT_CREATE
    finally:
        os.chmod(unwritable, 0o755)


# --- проверка записи в созданный каталог -------------------------------------


@POSIX_ONLY
def test_created_directory_is_probed_for_writes(validator, tmp_path):
    """
    Регресс: каталог возвращался сразу после makedirs. Под umask 0222 он выходил
    режимом 0o555, prepare_output_directory отвечал «ок», а первая же запись падала.
    """
    previous = os.umask(0o222)
    try:
        with pytest.raises(FileValidationError) as ctx:
            validator.prepare_output_directory(str(tmp_path / "new_out"))
    finally:
        os.umask(previous)

    assert ctx.value.code is FileValidationCode.OUTPUT_NOT_WRITABLE
    assert ctx.value.details["error"]


@POSIX_ONLY
def test_unwritable_directory_is_not_left_behind(validator, tmp_path):
    """Каталог-сироту, в который нельзя писать, за собой оставлять нельзя."""
    previous = os.umask(0o222)
    try:
        with pytest.raises(FileValidationError):
            validator.prepare_output_directory(str(tmp_path / "new_out"))
    finally:
        os.umask(previous)

    assert not (tmp_path / "new_out").exists()


def test_writable_directory_is_returned_as_before(validator, tmp_path):
    target = tmp_path / "deep" / "out"

    result = validator.prepare_output_directory(str(target))

    assert result == str(target)
    assert target.is_dir()
    (target / "probe").write_text("x", encoding="utf-8")


def test_write_probe_leaves_no_files(validator, tmp_path):
    result = validator.prepare_output_directory(str(tmp_path / "out"))

    assert os.listdir(result) == []


# --- удалённый рабочий каталог ----------------------------------------------


@pytest.fixture
def deleted_cwd():
    """Процесс с удалённым cwd: os.getcwd() падает, а с ним и os.path.abspath."""
    keep = os.getcwd()
    doomed = tempfile.mkdtemp()
    os.chdir(doomed)
    shutil.rmtree(doomed)
    try:
        yield
    finally:
        os.chdir(keep)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Windows держит cwd открытым")
def test_normalize_path_wraps_a_deleted_cwd(validator, deleted_cwd):
    """Регресс: голый FileNotFoundError пролетал мимо обработчиков CLI и GUI."""
    with pytest.raises(FileValidationError) as ctx:
        validator.normalize_path("a.efd")

    assert ctx.value.code is FileValidationCode.NOT_FOUND


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Windows держит cwd открытым")
def test_prepare_output_directory_reports_an_invalid_path(validator, deleted_cwd):
    """Для папки вывода диагноз точнее: путь невозможно разрешить."""
    with pytest.raises(FileValidationError) as ctx:
        validator.prepare_output_directory("out")

    assert ctx.value.code is FileValidationCode.OUTPUT_PATH_INVALID


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Windows держит cwd открытым")
def test_validate_input_file_reports_a_domain_error(validator, deleted_cwd):
    with pytest.raises(FileValidationError):
        validator.validate_input_file("a.efd")


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Windows держит cwd открытым")
def test_get_file_info_keeps_its_promise_not_to_raise(validator, deleted_cwd):
    """Докстринг обещает «без выбрасывания ошибок» — обещание должно держаться."""
    assert validator.get_file_info("a.efd") is None


def test_absolute_paths_survive_a_deleted_cwd(validator, tmp_path, deleted_cwd):
    """Абсолютный путь getcwd() не трогает и обязан работать дальше."""
    assert validator.prepare_output_directory(str(tmp_path / "out")) == str(tmp_path / "out")
