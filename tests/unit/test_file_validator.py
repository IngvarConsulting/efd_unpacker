"""
Юнит тесты для FileValidator
"""

import os
import tempfile
import unittest
from unittest.mock import patch, mock_open
import sys

# Добавляем src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from file_validator import FileValidator


class TestFileValidator(unittest.TestCase):
    """Тесты для класса FileValidator"""

    def setUp(self):
        """Настройка перед каждым тестом"""
        self.temp_dir = tempfile.mkdtemp()
        self.valid_efd_file = os.path.join(self.temp_dir, "test.efd")
        self.invalid_file = os.path.join(self.temp_dir, "test.txt")
        self.non_existent_file = os.path.join(self.temp_dir, "nonexistent.efd")

    def tearDown(self):
        """Очистка после каждого теста"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_validate_efd_file_valid(self):
        """Тест валидации корректного EFD файла"""
        # Создаем тестовый файл
        with open(self.valid_efd_file, 'w') as f:
            f.write("EFD test content")

        is_valid, error_message = FileValidator.validate_efd_file(self.valid_efd_file)
        
        self.assertTrue(is_valid)
        self.assertEqual(error_message, "")

    def test_validate_efd_file_not_exists(self):
        """Тест валидации несуществующего файла"""
        is_valid, error_message = FileValidator.validate_efd_file(self.non_existent_file)
        
        self.assertFalse(is_valid)
        self.assertIn("does not exist", error_message)

    def test_validate_efd_file_wrong_extension(self):
        """Тест валидации файла с неправильным расширением"""
        # Создаем файл с неправильным расширением
        with open(self.invalid_file, 'w') as f:
            f.write("test content")

        is_valid, error_message = FileValidator.validate_efd_file(self.invalid_file)
        
        self.assertFalse(is_valid)
        self.assertIn("Invalid file format", error_message)

    def test_validate_efd_file_empty(self):
        """Тест валидации пустого файла"""
        # Создаем пустой файл
        with open(self.valid_efd_file, 'w') as f:
            pass

        is_valid, error_message = FileValidator.validate_efd_file(self.valid_efd_file)
        
        self.assertFalse(is_valid)
        self.assertIn("empty", error_message)

    @patch('os.access')
    def test_validate_efd_file_no_permission(self, mock_access):
        """Тест валидации файла без прав доступа"""
        # Создаем файл сначала
        with open(self.valid_efd_file, 'w') as f:
            f.write("test content")
        
        mock_access.return_value = False
        
        is_valid, error_message = FileValidator.validate_efd_file(self.valid_efd_file)
        
        self.assertFalse(is_valid)
        self.assertIn("permission", error_message)

    def test_validate_output_directory_valid(self):
        """Тест валидации корректной выходной директории"""
        output_dir = os.path.join(self.temp_dir, "output")
        
        is_valid, error_message = FileValidator.validate_output_directory(output_dir)
        
        self.assertTrue(is_valid)
        self.assertEqual(error_message, "")

    def test_validate_output_directory_empty_path(self):
        """Тест валидации пустого пути"""
        is_valid, error_message = FileValidator.validate_output_directory("")
        
        self.assertFalse(is_valid)
        self.assertIn("empty", error_message)

    def test_validate_output_directory_whitespace_path(self):
        """Тест валидации пути из пробелов"""
        is_valid, error_message = FileValidator.validate_output_directory("   ")
        
        self.assertFalse(is_valid)
        self.assertIn("empty", error_message)

    def test_validate_output_directory_exists_as_file(self):
        """Тест валидации когда путь существует как файл"""
        # Создаем файл
        with open(self.invalid_file, 'w') as f:
            f.write("test")

        is_valid, error_message = FileValidator.validate_output_directory(self.invalid_file)
        
        self.assertFalse(is_valid)
        self.assertIn("not a directory", error_message)

    @patch('os.access')
    def test_validate_output_directory_no_write_permission(self, mock_access):
        """Тест валидации директории без прав на запись"""
        mock_access.return_value = False
        
        is_valid, error_message = FileValidator.validate_output_directory(self.temp_dir)
        
        self.assertFalse(is_valid)
        self.assertIn("permission", error_message)

    def test_create_output_directory_success(self):
        """Тест успешного создания выходной директории"""
        output_dir = os.path.join(self.temp_dir, "new_output")
        
        success, error_message = FileValidator.create_output_directory(output_dir)
        
        self.assertTrue(success)
        self.assertEqual(error_message, "")
        self.assertTrue(os.path.exists(output_dir))
        self.assertTrue(os.path.isdir(output_dir))

    def test_create_output_directory_already_exists(self):
        """Тест создания директории которая уже существует"""
        # Создаем директорию заранее
        os.makedirs(self.temp_dir, exist_ok=True)
        
        success, error_message = FileValidator.create_output_directory(self.temp_dir)
        
        self.assertTrue(success)
        self.assertEqual(error_message, "")

    def test_get_file_info_success(self):
        """Тест получения информации о файле"""
        # Создаем тестовый файл
        with open(self.valid_efd_file, 'w') as f:
            f.write("test content")

        file_info = FileValidator.get_file_info(self.valid_efd_file)
        
        self.assertIsNotNone(file_info)
        self.assertIn('size', file_info)
        self.assertIn('modified', file_info)
        self.assertIn('created', file_info)
        self.assertIn('readable', file_info)
        self.assertIn('writable', file_info)
        self.assertGreater(file_info['size'], 0)

    def test_get_file_info_nonexistent(self):
        """Тест получения информации о несуществующем файле"""
        file_info = FileValidator.get_file_info(self.non_existent_file)
        
        self.assertIsNone(file_info)


if __name__ == '__main__':
    unittest.main() 