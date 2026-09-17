import urllib.parse

import pytest

from efd_unpacker.application.main import format_help_text, process_file_argument
from efd_unpacker.domain.file_validator import FileValidator


class StubTranslator:
    def __init__(self, mapping: dict[tuple[str, str], str]) -> None:
        self.mapping = mapping

    def translate(self, context: str, source: str) -> str:
        return self.mapping.get((context, source), source)


def test_process_file_argument_resolves_relative_path(tmp_path, monkeypatch):
    input_file = tmp_path / "input.efd"
    input_file.write_text("payload", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = process_file_argument("input.efd", FileValidator())

    assert result == str(input_file.resolve())


def test_process_file_argument_supports_file_url(tmp_path):
    input_file = tmp_path / "input.efd"
    input_file.write_text("payload", encoding="utf-8")

    result = process_file_argument(input_file.resolve().as_uri(), FileValidator())

    assert result == str(input_file.resolve())


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


def test_process_file_argument_supports_percent_encoded_file_url(tmp_path):
    input_file = tmp_path / "файл с пробелом.efd"
    input_file.write_text("payload", encoding="utf-8")

    result = process_file_argument(input_file.resolve().as_uri(), FileValidator())

    assert result == str(input_file.resolve())


def test_process_file_argument_returns_none_for_missing_file(tmp_path):
    """Сейчас причина отказа теряется — GUI открывается пустым (см. #15)."""
    assert process_file_argument(str(tmp_path / "missing.efd"), FileValidator()) is None


def test_process_file_argument_rejects_wrong_extension(tmp_path):
    other = tmp_path / "data.zip"
    other.write_text("payload", encoding="utf-8")

    assert process_file_argument(str(other), FileValidator()) is None


@pytest.mark.xfail(
    strict=True,
    reason="#15: parsed.path.lstrip('/') превращает абсолютный путь в относительный",
)
def test_process_file_argument_supports_efd_scheme(tmp_path, monkeypatch):
    """Форма из docs/FILE_ASSOCIATION_GUIDE.md: efd:///abs/path.efd."""
    input_file = tmp_path / "sample.efd"
    input_file.write_text("payload", encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)

    result = process_file_argument(f"efd://{input_file.resolve().as_posix()}", FileValidator())

    assert result == str(input_file.resolve())


@pytest.mark.xfail(
    strict=True,
    reason="#15: efd:// с percent-encoding не декодируется, unquote применяется только к file://",
)
def test_process_file_argument_decodes_efd_scheme(tmp_path):
    input_file = tmp_path / "файл.efd"
    input_file.write_text("payload", encoding="utf-8")
    quoted = urllib.parse.quote(input_file.resolve().as_posix())

    result = process_file_argument(f"efd://{quoted}", FileValidator())

    assert result == str(input_file.resolve())
