# -*- coding: utf-8 -*-
import locale
import os
from localization import loc

class LanguageManager:
    def __init__(self):
        self.available_languages = {
            'ru': 'Русский',
            'en': 'English'
        }
        self.load_system_language()
    
    def get_system_language(self):
        """Определить системный язык"""
        # Попытка получить язык из переменных окружения (более точные для Unix/macOS)
        for env_var in ['LC_ALL', 'LC_MESSAGES', 'LANG']:
            lang_env = os.environ.get(env_var)
            if lang_env:
                lang_code = lang_env.split('_')[0].lower()
                if lang_code in self.available_languages:
                    return lang_code

        try:
            # Получаем системную локаль
            system_locale = locale.getdefaultlocale()[0]
            if system_locale:
                # Извлекаем код языка (первые 2 символа)
                lang_code = system_locale.split('_')[0].lower()
                # Проверяем, поддерживается ли этот язык
                if lang_code in self.available_languages:
                    return lang_code
        except Exception:
            pass
        
        # Если не удалось определить или язык не поддерживается, используем английский
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
