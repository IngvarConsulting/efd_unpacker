import os
from typing import Tuple, Optional
from tr import tr


class FileValidator:
    """Класс для валидации файлов EFD"""
    
    @staticmethod
    def validate_efd_file(file_path: str) -> Tuple[bool, str]:
        """
        Валидирует EFD файл.
        
        Args:
            file_path: Путь к файлу для валидации
            
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
            - is_valid: True если файл валиден, False иначе
            - error_message: Сообщение об ошибке (пустая строка если файл валиден)
        """
        # Проверяем существование файла
        if not os.path.exists(file_path):
            return False, tr('FileValidator', 'File does not exist')
        
        # Проверяем, что это файл, а не директория
        if not os.path.isfile(file_path):
            return False, tr('FileValidator', 'Path is not a file')
        
        # Проверяем расширение файла
        if not file_path.lower().endswith('.efd'):
            return False, tr('FileValidator', 'Invalid file format. Expected .efd file')
        
        # Проверяем права на чтение
        if not os.access(file_path, os.R_OK):
            return False, tr('FileValidator', 'No permission to read file')
        
        # Проверяем размер файла (не должен быть пустым)
        try:
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return False, tr('FileValidator', 'File is empty')
        except OSError:
            return False, tr('FileValidator', 'Cannot access file size')
        
        return True, ""
    
    @staticmethod
    def validate_output_directory(output_dir: str) -> Tuple[bool, str]:
        """
        Валидирует директорию для вывода.
        
        Args:
            output_dir: Путь к директории для валидации
            
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
            - is_valid: True если директория валидна, False иначе
            - error_message: Сообщение об ошибке (пустая строка если директория валидна)
        """
        # Проверяем, что путь не пустой
        if not output_dir or not output_dir.strip():
            return False, tr('FileValidator', 'Output directory path is empty')
        
        # Проверяем существование директории
        if os.path.exists(output_dir):
            # Если существует, проверяем что это директория
            if not os.path.isdir(output_dir):
                return False, tr('FileValidator', 'Output path exists but is not a directory')
            
            # Проверяем права на запись
            if not os.access(output_dir, os.W_OK):
                return False, tr('FileValidator', 'No permission to write to output directory')
        else:
            # Если директория не существует, проверяем возможность создания
            try:
                # Проверяем права на создание в родительской директории
                parent_dir = os.path.dirname(output_dir)
                if parent_dir and not os.access(parent_dir, os.W_OK):
                    return False, tr('FileValidator', 'No permission to create output directory')
            except OSError:
                return False, tr('FileValidator', 'Invalid output directory path')
        
        return True, ""
    
    @staticmethod
    def create_output_directory(output_dir: str) -> Tuple[bool, str]:
        """
        Создает директорию для вывода, если она не существует.
        
        Args:
            output_dir: Путь к директории для создания
            
        Returns:
            Tuple[bool, str]: (success, error_message)
            - success: True если директория создана или существует, False иначе
            - error_message: Сообщение об ошибке (пустая строка если успешно)
        """
        # Сначала валидируем директорию
        is_valid, error_message = FileValidator.validate_output_directory(output_dir)
        if not is_valid:
            return False, error_message
        
        # Если директория не существует, создаем её
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as e:
                return False, tr('FileValidator', 'Failed to create output directory: %1').replace('%1', str(e))
        
        return True, ""
    
    @staticmethod
    def get_file_info(file_path: str) -> Optional[dict]:
        """
        Получает информацию о файле.
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            Optional[dict]: Информация о файле или None если файл недоступен
        """
        try:
            stat = os.stat(file_path)
            return {
                'size': stat.st_size,
                'modified': stat.st_mtime,
                'created': stat.st_ctime,
                'readable': os.access(file_path, os.R_OK),
                'writable': os.access(file_path, os.W_OK)
            }
        except OSError:
            return None 