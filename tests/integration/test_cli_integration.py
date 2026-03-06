import os
import tempfile
import unittest

from efd_unpacker.application.cli import CLIApplication, CLIResult
from efd_unpacker.domain.file_validator import FileValidator
from efd_unpacker.domain.unpack_service import UnpackService


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return source


class NoopUnpackService(UnpackService):
    def __init__(self) -> None:
        pass

    def unpack(self, input_file: str, output_dir: str) -> None:
        self.called_with = (input_file, output_dir)


class TestCLIIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.input_file = os.path.join(self.temp_dir, "data.efd")
        with open(self.input_file, "w") as handle:
            handle.write("payload")
        self.output_dir = os.path.join(self.temp_dir, "out")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cli_valid_flow(self) -> None:
        validator = FileValidator()
        unpack_service = NoopUnpackService()
        cli = CLIApplication(
            validator=validator,
            unpack_service=unpack_service,
            translator=DummyTranslator(),
            output=lambda msg: None,
        )
        result = cli.run(["efd_unpacker", "unpack", self.input_file, "-tmplts", self.output_dir])
        self.assertEqual(result, CLIResult(exit_code=0, handled=True))
        self.assertTrue(os.path.isdir(self.output_dir))

    def test_cli_invalid_file(self) -> None:
        validator = FileValidator()
        unpack_service = NoopUnpackService()
        cli = CLIApplication(
            validator=validator,
            unpack_service=unpack_service,
            translator=DummyTranslator(),
            output=lambda msg: None,
        )
        result = cli.run(["efd_unpacker", "unpack", os.path.join(self.temp_dir, "missing.efd"), "-tmplts", self.output_dir])
        self.assertEqual(result.exit_code, 1)
        self.assertTrue(result.handled)


if __name__ == "__main__":
    unittest.main()
