# -*- coding: utf-8 -*-

class Localization:
    def __init__(self, language='ru'):
        self.language = language
        self.translations = {
            'ru': {
                # Основные элементы интерфейса
                'window_title': 'EFD Unpacker',
                'drag_drop_hint': 'Перетащите .efd сюда или нажмите для выбора',
                'output_folder_label': 'Распаковать в',
                'select_folder_button': 'Выбрать папку',
                'unpack_button': 'Распаковать',
                
                # Сообщения о состоянии
                'drop_file_hint': 'Отпустите файл для загрузки',
                'file_selected': '{file_path}',
                
                # Диалоги
                'select_folder_dialog_title': 'Выбрать папку для распаковки',
                'error_title': 'Ошибка',
                
                # Сообщения об ошибках
                'no_file_selected': 'Не выбран файл .efd',
                'invalid_output_folder': 'Неверная папка для распаковки',
                'unpack_error': 'Ошибка при распаковке:\n{error_message}',
                'file_not_found_error': 'Файл не найден',
                'permission_error': 'Ошибка доступа к файлу',
                'file_does_not_exist': 'Файл не существует',
                'invalid_file_format': 'Неверный формат файла',
                'select_efd_file': 'Выбрать .efd файл',
                'efd_files_filter': 'EFD Files (*.efd)',
                'unexpected_error': 'Неожиданная ошибка: {error}',
                
                # Сообщения об успехе
                'unpack_success': 'Распаковка завершена успешно',
                'open_folder_button': 'Открыть папку',
                'close_button': 'Закрыть',
                'reset_folder_button': 'Восстановить по-умолчанию',
                
                # Выпадающее меню путей
                'last_used_label': '(последний использованный)',
                'default_label': '(по-умолчанию)',
            },
            'en': {
                # Main interface elements
                'window_title': 'EFD Unpacker',
                'drag_drop_hint': 'Drag .efd file here or click to chose',
                'output_folder_label': 'Unpack into:',
                'select_folder_button': 'Select Folder',
                'unpack_button': 'Unpack',
                
                # Status messages
                'drop_file_hint': 'Drop file to upload',
                'file_selected': '{file_path}',
                
                # Dialogs
                'select_folder_dialog_title': 'Select output folder',
                'error_title': 'Error',
                
                # Error messages
                'no_file_selected': 'No .efd file selected',
                'invalid_output_folder': 'Invalid output folder',
                'unpack_error': 'Error during unpacking:\n{error_message}',
                'file_not_found_error': 'File not found',
                'permission_error': 'Permission error',
                'file_does_not_exist': 'File does not exist',
                'invalid_file_format': 'Invalid file format',
                'select_efd_file': 'Select .efd file',
                'efd_files_filter': 'EFD Files (*.efd)',
                'unexpected_error': 'Unexpected error: {error}',
                
                # Success messages
                'unpack_success': 'Unpacking completed successfully',
                'open_folder_button': 'Open Folder',
                'close_button': 'Close',
                'reset_folder_button': 'Reset to Default',
                
                # Dropdown menu paths
                'last_used_label': '(last used)',
                'default_label': '(default)',
            }
        }
    
    def get(self, key, **kwargs):
        """Получить переведенную строку по ключу"""
        if self.language not in self.translations:
            self.language = 'en'
        
        if key not in self.translations[self.language]:
            if key in self.translations['en']:
                text = self.translations['en'][key]
            else:
                return key 
        
        text = self.translations[self.language][key]
        
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError:
                pass
        
        return text
    
    def set_language(self, language):
        """Установить язык"""
        if language in self.translations:
            self.language = language

loc = Localization()
