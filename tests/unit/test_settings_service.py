"""
Юнит тесты для SettingsService
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Добавляем src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from settings_service import SettingsService


class TestSettingsService(unittest.TestCase):
    """Тесты для класса SettingsService"""

    def setUp(self):
        """Настройка перед каждым тестом"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_path = os.path.join(self.temp_dir, "test_path")

    def tearDown(self):
        """Очистка после каждого теста"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch('settings_service.QSettings')
    @patch('settings_service.get_1c_configuration_location_default')
    def test_get_output_path_default(self, mock_default_path, mock_qsettings):
        """Тест получения пути по умолчанию"""
        # Мокаем зависимости
        mock_default_path.return_value = "/default/path"
        mock_settings = MagicMock()
        mock_settings.value.return_value = "/default/path"  # Возвращаем значение по умолчанию
        mock_qsettings.return_value = mock_settings

        service = SettingsService()
        result = service.get_output_path()
        
        self.assertEqual(result, "/default/path")
        mock_settings.value.assert_called_once_with('output_path', "/default/path")

    @patch('settings_service.QSettings')
    @patch('settings_service.get_1c_configuration_location_default')
    def test_get_output_path_saved(self, mock_default_path, mock_qsettings):
        """Тест получения сохраненного пути"""
        # Мокаем зависимости
        mock_default_path.return_value = "/default/path"
        mock_settings = MagicMock()
        mock_settings.value.return_value = "/saved/path"
        mock_qsettings.return_value = mock_settings

        service = SettingsService()
        result = service.get_output_path()
        
        self.assertEqual(result, "/saved/path")
        mock_settings.value.assert_called_once_with('output_path', "/default/path")

    @patch('settings_service.QSettings')
    def test_set_output_path(self, mock_qsettings):
        """Тест установки пути"""
        # Мокаем зависимости
        mock_settings = MagicMock()
        mock_qsettings.return_value = mock_settings

        service = SettingsService()
        service.set_output_path("/new/path")
        
        mock_settings.setValue.assert_called_once_with('output_path', "/new/path")

    @patch('settings_service.QSettings')
    @patch('settings_service.get_1c_configuration_location_default')
    @patch('settings_service.get_1c_configuration_location_from_1cestart')
    @patch('settings_service.QCoreApplication.translate')
    def test_get_output_path_items_with_manual_path(self, mock_translate, mock_from_1cestart, mock_default_path, mock_qsettings):
        """Тест получения списка путей с вручную выбранным путем"""
        # Мокаем зависимости
        mock_default_path.return_value = "/default/path"
        mock_from_1cestart.return_value = ["/1cestart/path1", "/1cestart/path2"]
        mock_translate.side_effect = lambda context, text: text
        mock_settings = MagicMock()
        mock_settings.value.return_value = "/last/used/path"
        mock_qsettings.return_value = mock_settings

        service = SettingsService()
        items = service.get_output_path_items("/manual/path")
        
        # Проверяем, что вручную выбранный путь первый
        self.assertGreater(len(items), 0)
        self.assertEqual(items[0][0], "/manual/path")
        self.assertEqual(items[0][1], "/manual/path")

    @patch('settings_service.QSettings')
    @patch('settings_service.get_1c_configuration_location_default')
    @patch('settings_service.get_1c_configuration_location_from_1cestart')
    @patch('settings_service.QCoreApplication.translate')
    def test_get_output_path_items_without_manual_path(self, mock_translate, mock_from_1cestart, mock_default_path, mock_qsettings):
        """Тест получения списка путей без вручную выбранного пути"""
        # Мокаем зависимости
        mock_default_path.return_value = "/default/path"
        mock_from_1cestart.return_value = ["/1cestart/path1", "/1cestart/path2"]
        mock_translate.side_effect = lambda context, text: text
        mock_settings = MagicMock()
        mock_settings.value.return_value = "/last/used/path"
        mock_qsettings.return_value = mock_settings

        service = SettingsService()
        items = service.get_output_path_items(None)
        
        # Проверяем, что последний использованный путь первый
        self.assertGreater(len(items), 0)
        self.assertEqual(items[0][0], "/last/used/path")
        self.assertIn("(last used)", items[0][1])

    @patch('settings_service.QSettings')
    @patch('settings_service.get_1c_configuration_location_default')
    @patch('settings_service.get_1c_configuration_location_from_1cestart')
    @patch('settings_service.QCoreApplication.translate')
    def test_get_output_path_items_duplicate_removal(self, mock_translate, mock_from_1cestart, mock_default_path, mock_qsettings):
        """Тест удаления дублирующихся путей"""
        # Мокаем зависимости
        mock_default_path.return_value = "/same/path"
        mock_from_1cestart.return_value = ["/same/path", "/different/path"]
        mock_translate.side_effect = lambda context, text: text
        mock_settings = MagicMock()
        mock_settings.value.return_value = "/same/path"
        mock_qsettings.return_value = mock_settings

        service = SettingsService()
        items = service.get_output_path_items(None)
        
        # Проверяем, что дублирующиеся пути удалены
        paths = [item[0] for item in items]
        self.assertEqual(len(paths), len(set(paths)))

    @patch('settings_service.QSettings')
    @patch('settings_service.get_1c_configuration_location_default')
    @patch('settings_service.get_1c_configuration_location_from_1cestart')
    @patch('settings_service.QCoreApplication.translate')
    def test_get_output_path_items_order(self, mock_translate, mock_from_1cestart, mock_default_path, mock_qsettings):
        """Тест порядка путей в списке"""
        # Мокаем зависимости
        mock_default_path.return_value = "/default/path"
        mock_from_1cestart.return_value = ["/1cestart/path1", "/1cestart/path2"]
        mock_translate.side_effect = lambda context, text: text
        mock_settings = MagicMock()
        mock_settings.value.return_value = "/last/used/path"
        mock_qsettings.return_value = mock_settings

        service = SettingsService()
        items = service.get_output_path_items("/manual/path")
        
        # Проверяем порядок: manual -> last_used -> from_1cestart -> default
        self.assertGreater(len(items), 0)
        
        # Первый должен быть manual path
        self.assertEqual(items[0][0], "/manual/path")
        
        # Второй должен быть last used
        self.assertEqual(items[1][0], "/last/used/path")
        self.assertIn("(last used)", items[1][1])
        
        # Последний должен быть default
        self.assertEqual(items[-1][0], "/default/path")
        self.assertIn("(default)", items[-1][1])


if __name__ == '__main__':
    unittest.main() 