"""
Юнит тесты для CLIProcessor
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Добавляем src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from cli_processor import CLIProcessor


class TestCLIProcessor(unittest.TestCase):
    """Тесты для класса CLIProcessor"""

    def setUp(self):
        """Настройка перед каждым тестом"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_efd_file = os.path.join(self.temp_dir, "test.efd")
        self.output_dir = os.path.join(self.temp_dir, "output")

    def tearDown(self):
        """Очистка после каждого теста"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_cli_arguments_valid(self):
        """Тест парсинга корректных CLI аргументов"""
        with patch('sys.argv', ['efd_unpacker', 'unpack', 'test.efd', '-tmplts', '/output']):
            result = CLIProcessor.parse_cli_arguments()
            
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'test.efd')
        self.assertEqual(result[1], '/output')

    def test_parse_cli_arguments_invalid_command(self):
        """Тест парсинга некорректной команды"""
        with patch('sys.argv', ['efd_unpacker', 'invalid', 'test.efd', '-tmplts', '/output']):
            result = CLIProcessor.parse_cli_arguments()
            
        self.assertIsNone(result)

    def test_parse_cli_arguments_invalid_flag(self):
        """Тест парсинга некорректного флага"""
        with patch('sys.argv', ['efd_unpacker', 'unpack', 'test.efd', '-invalid', '/output']):
            result = CLIProcessor.parse_cli_arguments()
            
        self.assertIsNone(result)

    def test_parse_cli_arguments_insufficient_args(self):
        """Тест парсинга недостаточного количества аргументов"""
        with patch('sys.argv', ['efd_unpacker', 'unpack', 'test.efd']):
            result = CLIProcessor.parse_cli_arguments()
            
        self.assertIsNone(result)

    @patch('cli_processor.FileValidator.validate_efd_file')
    @patch('cli_processor.FileValidator.create_output_directory')
    @patch('cli_processor.UnpackService.unpack')
    def test_process_cli_unpack_success(self, mock_unpack, mock_create_dir, mock_validate):
        """Тест успешной CLI распаковки"""
        # Мокаем зависимости
        mock_validate.return_value = (True, "")
        mock_create_dir.return_value = (True, "")
        mock_unpack.return_value = (True, "Success")

        result = CLIProcessor.process_cli_unpack(self.test_efd_file, self.output_dir)
        
        self.assertTrue(result)
        mock_validate.assert_called_once_with(self.test_efd_file)
        mock_create_dir.assert_called_once_with(self.output_dir)
        mock_unpack.assert_called_once_with(self.test_efd_file, self.output_dir)

    @patch('cli_processor.FileValidator.validate_efd_file')
    def test_process_cli_unpack_invalid_file(self, mock_validate):
        """Тест CLI распаковки с невалидным файлом"""
        # Мокаем валидацию файла
        mock_validate.return_value = (False, "File not found")

        result = CLIProcessor.process_cli_unpack(self.test_efd_file, self.output_dir)
        
        self.assertFalse(result)

    @patch('cli_processor.FileValidator.validate_efd_file')
    @patch('cli_processor.FileValidator.create_output_directory')
    def test_process_cli_unpack_invalid_output_dir(self, mock_create_dir, mock_validate):
        """Тест CLI распаковки с невалидной выходной директорией"""
        # Мокаем зависимости
        mock_validate.return_value = (True, "")
        mock_create_dir.return_value = (False, "Permission denied")

        result = CLIProcessor.process_cli_unpack(self.test_efd_file, self.output_dir)
        
        self.assertFalse(result)

    @patch('cli_processor.FileValidator.validate_efd_file')
    @patch('cli_processor.FileValidator.create_output_directory')
    @patch('cli_processor.UnpackService.unpack')
    def test_process_cli_unpack_unpack_failed(self, mock_unpack, mock_create_dir, mock_validate):
        """Тест CLI распаковки когда распаковка не удалась"""
        # Мокаем зависимости
        mock_validate.return_value = (True, "")
        mock_create_dir.return_value = (True, "")
        mock_unpack.return_value = (False, "Unpack failed")

        result = CLIProcessor.process_cli_unpack(self.test_efd_file, self.output_dir)
        
        self.assertFalse(result)

    @patch('cli_processor.FileValidator.normalize_path')
    @patch('cli_processor.FileValidator.validate_efd_file')
    @patch('cli_processor.FileValidator.create_output_directory')
    @patch('cli_processor.UnpackService.unpack')
    def test_process_cli_unpack_uses_normalized_paths(self, mock_unpack, mock_create_dir, mock_validate, mock_normalize):
        """Тест использования нормализованных путей при распаковке"""
        mock_validate.return_value = (True, "")
        mock_create_dir.return_value = (True, "")
        mock_unpack.return_value = (True, "Success")
        def normalize_side_effect(path):
            return f"/abs/{os.path.basename(path)}"
        mock_normalize.side_effect = normalize_side_effect

        result = CLIProcessor.process_cli_unpack('~/test.efd', '~/output')

        self.assertTrue(result)
        mock_validate.assert_called_once_with('/abs/test.efd')
        mock_create_dir.assert_called_once_with('/abs/output')
        mock_unpack.assert_called_once_with('/abs/test.efd', '/abs/output')

    @patch('cli_processor.FileValidator.validate_efd_file')
    @patch('cli_processor.FileValidator.create_output_directory')
    @patch('cli_processor.UnpackService.unpack')
    @patch('sys.exit')
    def test_handle_cli_mode_success(self, mock_exit, mock_unpack, mock_create_dir, mock_validate):
        """Тест обработки CLI режима - успешный случай"""
        # Мокаем зависимости
        mock_validate.return_value = (True, "")
        mock_create_dir.return_value = (True, "")
        mock_unpack.return_value = (True, "Success")

        with patch('sys.argv', ['efd_unpacker', 'unpack', 'test.efd', '-tmplts', '/output']):
            # sys.exit должен вызываться, поэтому результат не важен
            CLIProcessor.handle_cli_mode()
        
        # Проверяем, что sys.exit был вызван с кодом 0
        mock_exit.assert_called_once_with(0)

    @patch('cli_processor.FileValidator.validate_efd_file')
    @patch('cli_processor.FileValidator.create_output_directory')
    @patch('cli_processor.UnpackService.unpack')
    @patch('sys.exit')
    def test_handle_cli_mode_failure(self, mock_exit, mock_unpack, mock_create_dir, mock_validate):
        """Тест обработки CLI режима - неуспешный случай"""
        # Мокаем зависимости
        mock_validate.return_value = (True, "")
        mock_create_dir.return_value = (True, "")
        mock_unpack.return_value = (False, "Unpack failed")

        with patch('sys.argv', ['efd_unpacker', 'unpack', 'test.efd', '-tmplts', '/output']):
            # sys.exit должен вызываться, поэтому результат не важен
            CLIProcessor.handle_cli_mode()
        
        # Проверяем, что sys.exit был вызван с кодом 1
        mock_exit.assert_called_once_with(1)

    @patch('cli_processor.CLIProcessor.parse_cli_arguments')
    @patch('sys.exit')
    def test_handle_cli_mode_no_args(self, mock_exit, mock_parse):
        """Тест обработки CLI режима - нет аргументов"""
        # Мокаем зависимости
        mock_parse.return_value = None

        result = CLIProcessor.handle_cli_mode()
        
        self.assertFalse(result)
        mock_exit.assert_not_called()

    @patch('sys.exit')
    def test_handle_cli_mode_invalid_file(self, mock_exit):
        """Тест обработки CLI режима - невалидный файл"""
        # Мокаем зависимости
        with patch('sys.argv', ['efd_unpacker', 'unpack', '', '-tmplts', '/output']):
            # sys.exit должен вызываться, поэтому результат не важен
            CLIProcessor.handle_cli_mode()
        
        # Проверяем, что sys.exit был вызван с кодом 1 (последний вызов)
        mock_exit.assert_called_with(1)


if __name__ == '__main__':
    unittest.main() 
