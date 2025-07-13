"""
Интеграционные тесты для CLI функциональности
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Добавляем src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from cli_processor import CLIProcessor
from file_validator import FileValidator


class TestCLIIntegration(unittest.TestCase):
    """Интеграционные тесты для CLI"""

    def setUp(self):
        """Настройка перед каждым тестом"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_efd_file = os.path.join(self.temp_dir, "test.efd")
        self.output_dir = os.path.join(self.temp_dir, "output")

    def tearDown(self):
        """Очистка после каждого теста"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cli_workflow_valid_file(self):
        """Тест полного CLI workflow с валидным файлом"""
        # Создаем тестовый EFD файл
        with open(self.test_efd_file, 'w') as f:
            f.write("EFD test content")

        # Тестируем валидацию файла
        is_valid, error_message = FileValidator.validate_efd_file(self.test_efd_file)
        self.assertTrue(is_valid)
        self.assertEqual(error_message, "")

        # Тестируем создание выходной директории
        success, error_message = FileValidator.create_output_directory(self.output_dir)
        self.assertTrue(success)
        self.assertEqual(error_message, "")
        self.assertTrue(os.path.exists(self.output_dir))

        # Тестируем CLI обработку
        with patch('sys.argv', ['efd_unpacker', 'unpack', self.test_efd_file, '-tmplts', self.output_dir]):
            cli_args = CLIProcessor.parse_cli_arguments()
            self.assertIsNotNone(cli_args)
            self.assertEqual(cli_args[0], self.test_efd_file)
            self.assertEqual(cli_args[1], self.output_dir)

    def test_cli_workflow_invalid_file(self):
        """Тест полного CLI workflow с невалидным файлом"""
        # Создаем файл с неправильным расширением
        invalid_file = os.path.join(self.temp_dir, "test.txt")
        with open(invalid_file, 'w') as f:
            f.write("test content")

        # Тестируем валидацию файла
        is_valid, error_message = FileValidator.validate_efd_file(invalid_file)
        self.assertFalse(is_valid)
        self.assertIn("Invalid file format", error_message)

        # Тестируем CLI обработку
        with patch('sys.argv', ['efd_unpacker', 'unpack', invalid_file, '-tmplts', self.output_dir]):
            cli_args = CLIProcessor.parse_cli_arguments()
            self.assertIsNotNone(cli_args)
            
            # CLI должен вернуть None для невалидного файла
            with patch('cli_processor.FileValidator.validate_efd_file', return_value=(False, "Invalid file")):
                result = CLIProcessor.process_cli_unpack(cli_args[0], cli_args[1])
                self.assertFalse(result)

    def test_cli_workflow_nonexistent_file(self):
        """Тест CLI workflow с несуществующим файлом"""
        nonexistent_file = os.path.join(self.temp_dir, "nonexistent.efd")

        # Тестируем валидацию файла
        is_valid, error_message = FileValidator.validate_efd_file(nonexistent_file)
        self.assertFalse(is_valid)
        self.assertIn("does not exist", error_message)

        # Тестируем CLI обработку
        with patch('sys.argv', ['efd_unpacker', 'unpack', nonexistent_file, '-tmplts', self.output_dir]):
            cli_args = CLIProcessor.parse_cli_arguments()
            self.assertIsNotNone(cli_args)
            
            # CLI должен вернуть False для несуществующего файла
            result = CLIProcessor.process_cli_unpack(cli_args[0], cli_args[1])
            self.assertFalse(result)

    def test_cli_argument_parsing_edge_cases(self):
        """Тест парсинга CLI аргументов в граничных случаях"""
        # Тест с пустыми аргументами
        with patch('sys.argv', ['efd_unpacker']):
            result = CLIProcessor.parse_cli_arguments()
            self.assertIsNone(result)

        # Тест с недостаточными аргументами
        with patch('sys.argv', ['efd_unpacker', 'unpack']):
            result = CLIProcessor.parse_cli_arguments()
            self.assertIsNone(result)

        # Тест с неправильной командой
        with patch('sys.argv', ['efd_unpacker', 'invalid', 'test.efd', '-tmplts', '/output']):
            result = CLIProcessor.parse_cli_arguments()
            self.assertIsNone(result)

        # Тест с неправильным флагом
        with patch('sys.argv', ['efd_unpacker', 'unpack', 'test.efd', '-wrong', '/output']):
            result = CLIProcessor.parse_cli_arguments()
            self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main() 