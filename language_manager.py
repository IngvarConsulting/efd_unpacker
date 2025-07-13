# -*- coding: utf-8 -*-

from localization import loc
from os_utils import get_default_language # Импортируем новую функцию

class LanguageManager:
    def __init__(self):
        self.available_languages = {
            'ru': 'Русский',
            'en': 'English'
        }
        self.load_system_language()
    
    def get_system_language(self):
        """Определить системный язык"""
        # Используем новую платформо-зависимую функцию из os_utils
        lang_code = get_default_language()
        
        # Проверяем, поддерживается ли этот язык
        if lang_code in self.available_languages:
            return lang_code
        
        # Если язык не поддерживается, используем английский
        return 'en'
    
    def load_system_language(self):
        """Загрузить системный язык"""
        language = self.get_system_language()
        loc.set_language(language)
    
    def set_language(self, language):
        """Установить язык (для совместимости)"""
        if language in self.available_languages:
            loc.set_language(language)
    
    def get_current_language(self):
        """Получить текущий язык"""
        return loc.language
    
    def get_available_languages(self):
        """Получить список доступных языков"""
        return self.available_languages
    
    def get_language_name(self, language_code):
        """Получить название языка по коду"""
        return self.available_languages.get(language_code, language_code)

# Глобальный экземпляр менеджера языков
language_manager = LanguageManager()
