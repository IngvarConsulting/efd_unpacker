"""
Менеджер локализации для приложения EFD Unpacker
"""

from PyQt5.QtCore import QLocale, QTranslator
import os
import sys
from typing import Optional


class LanguageManager:
    """Менеджер для определения и настройки языка приложения"""
    
    @staticmethod
    def determine_language() -> str:
        """
        Определяет язык приложения на основе системных настроек.
        
        Returns:
            str: Код языка ('ru' или 'en')
        """
        system_locale = QLocale.system()
        locale_name = system_locale.name()
        
        # Сначала проверяем по имени локали
        if 'ru' in locale_name.lower():
            return 'ru'
        elif 'en' in locale_name.lower():
            return 'en'
        
        # Fallback на язык из системной локали
        lang = system_locale.language()
        if lang == QLocale.Language.Russian:
            return 'ru'
        elif lang == QLocale.Language.English:
            return 'en'
        
        return 'en'  # Default fallback
    
    @staticmethod
    def setup_localization(app, language: str) -> bool:
        """
        Настраивает локализацию приложения.
        
        Args:
            app: QApplication instance
            language: Код языка ('ru' или 'en')
            
        Returns:
            bool: True если переводы загружены успешно
        """
        # Устанавливаем локаль приложения
        if language == 'ru':
            locale = QLocale(QLocale.Language.Russian, QLocale.Country.Russia)
        else:
            locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        
        QLocale.setDefault(locale)
        
        # Загружаем наш собственный перевод
        translator = QTranslator()
        translations_path = LanguageManager._get_translations_path()
        
        app_loaded = translator.load(f'{language}.qm', translations_path)
        print(f"App translator loaded: {app_loaded}")
        
        if app_loaded:
            app.installTranslator(translator)
        
        return app_loaded
    
    @staticmethod
    def _get_translations_path() -> str:
        """
        Получает путь к папке с переводами.
        
        Returns:
            str: Путь к папке translations
        """
        if getattr(sys, 'frozen', False):
            # Если приложение собрано (PyInstaller)
            return os.path.join(os.path.dirname(sys.executable), '..', 'Resources', 'translations')
        else:
            # Если запускаем из исходников
            return 'translations' 