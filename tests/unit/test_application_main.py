from efd_unpacker.application.main import process_file_argument
from efd_unpacker.domain.file_validator import FileValidator


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
