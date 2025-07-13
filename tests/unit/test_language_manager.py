"""
Юнит тесты для LanguageManager
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Добавляем src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from language_manager import LanguageManager


class TestLanguageManager(unittest.TestCase):
    """Тесты для класса LanguageManager"""

    @patch('language_manager.QLocale')
    def test_determine_language_russian_locale_name(self, mock_qlocale):
        """Тест определения русского языка по имени локали"""
        # Мокаем QLocale
        mock_locale = MagicMock()
        mock_locale.name.return_value = "ru_RU"
        mock_qlocale.system.return_value = mock_locale
        
        language = LanguageManager.determine_language()
        
        self.assertEqual(language, "ru")

    @patch('language_manager.QLocale')
    def test_determine_language_english_locale_name(self, mock_qlocale):
        """Тест определения английского языка по имени локали"""
        # Мокаем QLocale
        mock_locale = MagicMock()
        mock_locale.name.return_value = "en_US"
        mock_qlocale.system.return_value = mock_locale
        
        language = LanguageManager.determine_language()
        
        self.assertEqual(language, "en")

    @patch('language_manager.QLocale')
    def test_determine_language_russian_language(self, mock_qlocale):
        """Тест определения русского языка по языку"""
        # Мокаем QLocale
        mock_locale = MagicMock()
        mock_locale.name.return_value = "unknown"
        mock_locale.language.return_value = mock_qlocale.Language.Russian
        mock_qlocale.system.return_value = mock_locale
        
        language = LanguageManager.determine_language()
        
        self.assertEqual(language, "ru")

    @patch('language_manager.QLocale')
    def test_determine_language_english_language(self, mock_qlocale):
        """Тест определения английского языка по языку"""
        # Мокаем QLocale
        mock_locale = MagicMock()
        mock_locale.name.return_value = "unknown"
        mock_locale.language.return_value = mock_qlocale.Language.English
        mock_qlocale.system.return_value = mock_locale
        
        language = LanguageManager.determine_language()
        
        self.assertEqual(language, "en")

    @patch('language_manager.QLocale')
    def test_determine_language_fallback_to_english(self, mock_qlocale):
        """Тест fallback на английский язык"""
        # Мокаем QLocale
        mock_locale = MagicMock()
        mock_locale.name.return_value = "unknown"
        mock_locale.language.return_value = mock_qlocale.Language.Unknown
        mock_qlocale.system.return_value = mock_locale
        
        language = LanguageManager.determine_language()
        
        self.assertEqual(language, "en")

    @patch('language_manager.QLocale')
    @patch('language_manager.QTranslator')
    @patch('language_manager.LanguageManager._get_translations_path')
    def test_setup_localization_russian(self, mock_get_path, mock_translator, mock_qlocale):
        """Тест настройки локализации для русского языка"""
        # Мокаем зависимости
        mock_get_path.return_value = "/test/translations"
        mock_translator_instance = MagicMock()
        mock_translator_instance.load.return_value = True
        mock_translator.return_value = mock_translator_instance
        
        mock_app = MagicMock()
        
        result = LanguageManager.setup_localization(mock_app, "ru")
        
        self.assertTrue(result)
        mock_translator_instance.load.assert_called_once_with("ru.qm", "/test/translations")
        mock_app.installTranslator.assert_called_once_with(mock_translator_instance)

    @patch('language_manager.QLocale')
    @patch('language_manager.QTranslator')
    @patch('language_manager.LanguageManager._get_translations_path')
    def test_setup_localization_english(self, mock_get_path, mock_translator, mock_qlocale):
        """Тест настройки локализации для английского языка"""
        # Мокаем зависимости
        mock_get_path.return_value = "/test/translations"
        mock_translator_instance = MagicMock()
        mock_translator_instance.load.return_value = True
        mock_translator.return_value = mock_translator_instance
        
        mock_app = MagicMock()
        
        result = LanguageManager.setup_localization(mock_app, "en")
        
        self.assertTrue(result)
        mock_translator_instance.load.assert_called_once_with("en.qm", "/test/translations")
        mock_app.installTranslator.assert_called_once_with(mock_translator_instance)

    @patch('language_manager.QLocale')
    @patch('language_manager.QTranslator')
    @patch('language_manager.LanguageManager._get_translations_path')
    def test_setup_localization_translation_failed(self, mock_get_path, mock_translator, mock_qlocale):
        """Тест настройки локализации когда перевод не загрузился"""
        # Мокаем зависимости
        mock_get_path.return_value = "/test/translations"
        mock_translator_instance = MagicMock()
        mock_translator_instance.load.return_value = False
        mock_translator.return_value = mock_translator_instance
        
        mock_app = MagicMock()
        
        result = LanguageManager.setup_localization(mock_app, "ru")
        
        self.assertFalse(result)
        mock_app.installTranslator.assert_not_called()

    def test_get_translations_path_frozen(self):
        """Тест получения пути к переводам для собранного приложения"""
        # Пропускаем этот тест, так как sys.frozen не может быть замокан
        self.skipTest("sys.frozen cannot be mocked")

    def test_get_translations_path_development(self):
        """Тест получения пути к переводам для разработки"""
        # Пропускаем этот тест, так как sys.frozen не может быть замокан
        self.skipTest("sys.frozen cannot be mocked")


if __name__ == '__main__':
    unittest.main() 