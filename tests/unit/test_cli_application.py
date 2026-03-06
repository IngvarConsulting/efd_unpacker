import unittest
from typing import List

from efd_unpacker.application.cli import CLIApplication, CLIResult
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
