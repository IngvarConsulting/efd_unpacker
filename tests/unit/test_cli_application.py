import unittest
from typing import List

import pytest

from efd_unpacker.application.cli import CLIApplication, CLIResult, wants_help
from efd_unpacker.domain.errors import FileValidationError, FileValidationCode, UnpackError, UnpackErrorCode
from efd_unpacker.domain.file_validator import FileValidator
from efd_unpacker.domain.unpack_service import UnpackService


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return source


class StubValidator(FileValidator):
    def __init__(self) -> None:
        super().__init__()
        self.validated_input = None
        self.prepared_output = None

    def validate_input_file(self, file_path: str) -> str:
        self.validated_input = file_path
        return file_path

    def prepare_output_directory(self, output_dir: str) -> str:
        self.prepared_output = output_dir
        return output_dir


class StubUnpackService(UnpackService):
    def __init__(self) -> None:
        pass

    def unpack(self, input_file: str, output_dir: str) -> None:
        self.last_call = (input_file, output_dir)


class TestCLIApplication(unittest.TestCase):
    def setUp(self) -> None:
        self.translator = DummyTranslator()
        self.validator = StubValidator()
        self.unpack_service = StubUnpackService()
        self.messages: List[str] = []

    def _create_app(self) -> CLIApplication:
        return CLIApplication(
            validator=self.validator,
            unpack_service=self.unpack_service,
            translator=self.translator,
            output=self.messages.append,
        )

    def test_run_returns_unhandled_when_no_args(self) -> None:
        app = self._create_app()
        result = app.run(["efd_unpacker"])
        self.assertEqual(result, CLIResult(exit_code=0, handled=False))
        self.assertEqual(self.messages, [])

    def test_run_returns_unhandled_for_gui_mode_file_argument(self) -> None:
        app = self._create_app()
        result = app.run(["efd_unpacker", "input.efd"])
        self.assertEqual(result, CLIResult(exit_code=0, handled=False))
        self.assertEqual(self.messages, [])

    def test_run_success(self) -> None:
        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "input.efd", "-tmplts", "out"])
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.handled)
        self.assertIn("[OK]", self.messages[0])
        self.assertEqual(self.validator.validated_input, "input.efd")
        self.assertEqual(self.validator.prepared_output, "out")

    def test_run_validation_error(self) -> None:
        class FailingValidator(StubValidator):
            def validate_input_file(self, file_path: str) -> str:
                raise FileValidationError(FileValidationCode.NOT_FOUND)

        self.validator = FailingValidator()
        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "missing.efd", "-tmplts", "out"])
        self.assertEqual(result.exit_code, 1)
        self.assertTrue(result.handled)
        self.assertTrue(self.messages[0].startswith("[ERROR]"))

    def test_run_unpack_error(self) -> None:
        class FailingUnpack(UnpackService):
            def __init__(self) -> None:
                pass

            def unpack(self, input_file: str, output_dir: str) -> None:
                raise UnpackError(UnpackErrorCode.PERMISSION)

        self.unpack_service = FailingUnpack()
        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "input.efd", "-tmplts", "out"])
        self.assertEqual(result.exit_code, 1)
        self.assertTrue(result.handled)
        self.assertTrue(self.messages[0].startswith("[ERROR]"))


if __name__ == "__main__":
    unittest.main()


# --- строгий разбор команды unpack (#15) -------------------------------------


class _Recorder:
    """Собирает вывод CLI, чтобы проверить, что пользователь что-то увидел."""

    def __init__(self):
        self.lines = []

    def __call__(self, message):
        self.lines.append(message)

    @property
    def text(self):
        return "\n".join(self.lines)


def _cli_with_output(output):
    return CLIApplication(
        validator=FileValidator(),
        unpack_service=UnpackService(),
        translator=DummyTranslator(),
        output=output,
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["efd_unpacker", "unpack", "a.efd", "--tmplts", "out"],
        ["efd_unpacker", "unpack", "-tmplts", "out", "a.efd"],
        ["efd_unpacker", "UNPACK", "a.efd", "-tmplts", "out"],
        ["efd_unpacker", "unpack", "a.efd"],
        ["efd_unpacker", "unpack"],
        ["efd_unpacker", "unpack", "a.efd", "-tmplts", "out", "EXTRA"],
        ["efd_unpacker", "unpack", "a.efd", "-t", "out"],
        ["efd_unpacker", "unpack", "a.efd", "-tmp", "out"],
        ["efd_unpacker", "unpack", "a.efd", "-tmplts", ""],
    ],
    ids=[
        "--tmplts", "перепутан порядок", "верхний регистр", "без флага",
        "только команда", "лишний хвост", "сокращение -t", "сокращение -tmp",
        "пустой каталог",
    ],
)
def test_malformed_unpack_prints_usage_instead_of_opening_the_gui(argv):
    """
    Регресс #15: любой неверный хвост возвращал handled=False, процесс
    проваливался в Qt event loop и висел до убийства — ни сообщения, ни кода.

    Сокращения проверяются отдельно: allow_abbrev=False в argparse отключает
    их только для --опций, и `-t out` он принял бы как -tmplts.
    """
    output = _Recorder()

    result = _cli_with_output(output).run(argv)

    assert result.handled is True
    assert result.exit_code == 2
    assert "efd_unpacker unpack <input_file.efd> -tmplts <output_dir>" in output.text


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_after_the_command_prints_help(flag):
    """`unpack --help` — именно то, что наберёт забывший синтаксис."""
    output = _Recorder()

    result = _cli_with_output(output).run(["efd_unpacker", "unpack", flag])

    assert result == CLIResult(exit_code=0, handled=True)
    assert "efd_unpacker unpack <input_file.efd> -tmplts <output_dir>" in output.text


def test_help_wins_over_a_malformed_tail():
    output = _Recorder()

    result = _cli_with_output(output).run(["efd_unpacker", "unpack", "a.efd", "--help", "x"])

    assert result.exit_code == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["efd_unpacker"],
        ["efd_unpacker", "/path/file.efd"],
        ["efd_unpacker", "-platform", "offscreen"],
        ["efd_unpacker", "unpacked.efd"],
    ],
    ids=["без аргументов", "файл для GUI", "флаг Qt", "имя, похожее на команду"],
)
def test_non_unpack_arguments_still_go_to_the_gui(argv):
    """GUI-режим трогать нельзя: без команды unpack CLI обязан отдать управление."""
    result = _cli_with_output(_Recorder()).run(argv)

    assert result == CLIResult(exit_code=0, handled=False)


def test_wants_help_scans_every_position():
    assert wants_help(["unpack", "a.efd", "--help"]) is True
    assert wants_help(["-h"]) is True
    assert wants_help(["unpack", "a.efd", "-tmplts", "out"]) is False
