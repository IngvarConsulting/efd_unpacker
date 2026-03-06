"""
Юнит тесты для FileValidator.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from efd_unpacker.domain.errors import FileValidationCode, FileValidationError
from efd_unpacker.domain.file_validator import FileValidator


class TestFileValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = FileValidator()
        self.temp_dir = tempfile.mkdtemp()
        self.valid_file = os.path.join(self.temp_dir, "valid.efd")
        with open(self.valid_file, "w") as handle:
            handle.write("content")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_validate_input_file_success(self) -> None:
        result = self.validator.validate_input_file(self.valid_file)
        self.assertEqual(result, os.path.abspath(self.valid_file))

    def test_validate_input_file_not_found(self) -> None:
        with self.assertRaises(FileValidationError) as ctx:
            self.validator.validate_input_file(os.path.join(self.temp_dir, "missing.efd"))
        self.assertEqual(ctx.exception.code, FileValidationCode.NOT_FOUND)

    def test_validate_input_file_invalid_extension(self) -> None:
        invalid = os.path.join(self.temp_dir, "file.txt")
        with open(invalid, "w") as handle:
            handle.write("test")
        with self.assertRaises(FileValidationError) as ctx:
            self.validator.validate_input_file(invalid)
        self.assertEqual(ctx.exception.code, FileValidationCode.INVALID_EXTENSION)

    def test_validate_input_file_empty(self) -> None:
        empty = os.path.join(self.temp_dir, "empty.efd")
        open(empty, "w").close()
        with self.assertRaises(FileValidationError) as ctx:
            self.validator.validate_input_file(empty)
        self.assertEqual(ctx.exception.code, FileValidationCode.EMPTY)

    def test_prepare_output_directory_existing(self) -> None:
        output = os.path.join(self.temp_dir, "output")
        os.makedirs(output)
        os.chmod(output, 0o755)
        result = self.validator.prepare_output_directory(output)
        self.assertTrue(os.path.isdir(result))

    def test_prepare_output_directory_creates(self) -> None:
        nested = os.path.join(self.temp_dir, "nested", "dir")
        result = self.validator.prepare_output_directory(nested)
        self.assertTrue(os.path.isdir(result))

    def test_prepare_output_directory_expands_user(self) -> None:
        target = os.path.join(self.temp_dir, "user_dir")
        tilde_path = os.path.join("~", "efd_unpacker", "output")
        with patch("efd_unpacker.domain.file_validator.os.path.expanduser", return_value=target):
            result = self.validator.prepare_output_directory(tilde_path)
        self.assertTrue(os.path.isdir(result))
        self.assertEqual(result, os.path.abspath(target))

    def test_prepare_output_directory_no_permission(self) -> None:
        tmp = os.path.join(self.temp_dir, "locked")
        os.makedirs(tmp, exist_ok=True)
        with patch("os.access", return_value=False):
            with self.assertRaises(FileValidationError) as ctx:
                self.validator.prepare_output_directory(tmp)
            self.assertEqual(ctx.exception.code, FileValidationCode.OUTPUT_NOT_WRITABLE)

    def test_get_file_info(self) -> None:
        info = self.validator.get_file_info(self.valid_file)
        self.assertIsNotNone(info)
        self.assertGreater(info["size"], 0)

    def test_get_file_info_nonexistent(self) -> None:
        info = self.validator.get_file_info(os.path.join(self.temp_dir, "missing.efd"))
        self.assertIsNone(info)


if __name__ == "__main__":
    unittest.main()
