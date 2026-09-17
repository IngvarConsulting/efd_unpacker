"""
Тесты разбора аргументов запуска.

process_file_argument больше не валидирует: он приводит аргумент к пути на
диске, а причину отказа показывает MainWindow.set_input_file — до правки она
терялась вместе с кодом ошибки, и GUI открывался пустым.
"""

import urllib.parse

import pytest

from efd_unpacker.application.main import (
    looks_like_input,
    process_file_argument,
)
from efd_unpacker.application.help_text import format_help_text


class StubTranslator:
    def __init__(self, mapping) -> None:
        self.mapping = mapping

    def translate(self, context: str, source: str) -> str:
        return self.mapping.get((context, source), source)


def test_plain_path_is_returned_unchanged(tmp_path):
    """Обычный путь — не URL, разбирать нечего. Абсолютным его сделает валидатор."""
    assert process_file_argument("input.efd") == "input.efd"
    assert process_file_argument(str(tmp_path / "a.efd")) == str(tmp_path / "a.efd")


def test_file_url_becomes_an_absolute_path(tmp_path):
    input_file = tmp_path / "input.efd"

    assert process_file_argument(input_file.as_uri()) == str(input_file)


def test_file_url_decodes_percent_encoding(tmp_path):
    input_file = tmp_path / "файл с пробелом.efd"

    assert process_file_argument(input_file.as_uri()) == str(input_file)


# --- схема efd:// ------------------------------------------------------------
#
# Регресс #15: ветка efd:// делала parsed.path.lstrip("/"), поэтому абсолютный
# путь становился относительным, а unquote не вызывался вовсе. Не работала ни
# одна реалистичная форма, включая команду прямо из FILE_ASSOCIATION_GUIDE.


@pytest.mark.parametrize(
    "name",
    ["sample.efd", "файл.efd", "файл с пробелом.efd", "a+b.efd", "100%.efd"],
    ids=["ascii", "кириллица", "пробел", "плюс", "процент"],
)
def test_efd_scheme_matches_the_file_scheme(tmp_path, name):
    """Критерий #15: efd:// обязан давать ровно то же, что эквивалентный file://."""
    input_file = tmp_path / name
    file_url = input_file.as_uri()
    efd_url = "efd://" + file_url[len("file://"):]

    assert process_file_argument(efd_url) == process_file_argument(file_url)
    assert process_file_argument(efd_url) == str(input_file)


def test_efd_scheme_from_the_documentation(tmp_path, monkeypatch):
    """Форма из docs/FILE_ASSOCIATION_GUIDE.md: efd:///abs/path.efd."""
    input_file = tmp_path / "sample.efd"
    monkeypatch.chdir(tmp_path.parent)

    result = process_file_argument("efd://" + input_file.as_posix())

    assert result == str(input_file)


def test_efd_scheme_decodes_percent_encoding(tmp_path):
    input_file = tmp_path / "файл.efd"
    quoted = urllib.parse.quote(input_file.as_posix())

    assert process_file_argument("efd://" + quoted) == str(input_file)


@pytest.mark.parametrize("scheme", ["file", "efd"], ids=["file", "efd"])
def test_windows_drive_letter_is_not_treated_as_a_host(scheme):
    """
    efd://C:/dir/f.efd — буква диска, а не UNC-хост.

    urlparse кладёт «C:» в netloc, и без отдельной ветки путь превратился бы
    в мусор //C:/dir/f.efd.
    """
    assert process_file_argument(f"{scheme}://C:/dir/f.efd") == "C:/dir/f.efd"


def test_localhost_host_is_dropped(tmp_path):
    input_file = tmp_path / "a.efd"

    assert process_file_argument("file://localhost" + input_file.as_posix()) == str(input_file)


# --- отбор аргументов, похожих на ввод ---------------------------------------


@pytest.mark.parametrize(
    "argument",
    ["/tmp/a.efd", "A.EFD", "file:///tmp/a.efd", "efd:///tmp/a.efd", "efd://host/x"],
)
def test_input_like_arguments_are_recognized(argument):
    assert looks_like_input(argument) is True


@pytest.mark.parametrize(
    "argument",
    ["-platform", "--style=fusion", "offscreen", "/tmp/a.zip", ""],
)
def test_other_arguments_are_left_to_qt(argument):
    """
    Посторонние флаги запуска не должны порождать «файл не существует».

    main намеренно пропускает нераспознанные аргументы в Qt, а показ причины
    отказа теперь живой — без отбора он бы сработал на каждом таком флаге.
    """
    assert looks_like_input(argument) is False


def test_format_help_text_localizes_headings_and_descriptions():
    translator = StubTranslator(
        {
            ("CLIHelp", "EFD Unpacker - cross-platform EFD file unpacker"): "EFD Unpacker - кроссплатформенный распаковщик файлов EFD",
            ("CLIHelp", "CLI modes:"): "Режимы CLI:",
            ("CLIHelp", "1. GUI mode: open the window and preselect the input file"): "1. Режим GUI: открыть окно и заранее выбрать входной файл",
            ("CLIHelp", "2. Headless mode: unpack directly in the console"): "2. Консольный режим: распаковать напрямую в консоли",
            ("CLIHelp", "Usage:"): "Использование:",
        }
    )

    help_text = format_help_text(translator)

    assert "Режимы CLI:" in help_text
    assert "Использование:" in help_text
    assert "GUI mode: open the window and preselect the input file" not in help_text
    assert "efd_unpacker unpack <input_file.efd> -tmplts <output_dir>" in help_text
