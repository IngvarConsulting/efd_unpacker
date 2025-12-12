import os
from typing import Tuple, Optional
from tr import tr


class FileValidator:
    """Класс для валидации файлов EFD"""

    @staticmethod
    def normalize_path(path: str) -> str:
        """Раскрывает ~ и приводит путь к абсолютному виду."""
        if not path:
            return path
        try:
            expanded = os.path.expanduser(path)
            return os.path.abspath(expanded)
        except (TypeError, ValueError):
            return path
    
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
        normalized_path = FileValidator.normalize_path(file_path)

        # Проверяем существование файла
        if not os.path.exists(normalized_path):
            return False, tr('FileValidator', 'File does not exist')
        
        # Проверяем, что это файл, а не директория
        if not os.path.isfile(normalized_path):
            return False, tr('FileValidator', 'Path is not a file')
        
        # Проверяем расширение файла
        if not normalized_path.lower().endswith('.efd'):
            return False, tr('FileValidator', 'Invalid file format. Expected .efd file')
        
        # Проверяем права на чтение
        if not os.access(normalized_path, os.R_OK):
            return False, tr('FileValidator', 'No permission to read file')
        
        # Проверяем размер файла (не должен быть пустым)
        try:
            file_size = os.path.getsize(normalized_path)
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
        
        normalized_dir = FileValidator.normalize_path(output_dir)

        # Проверяем существование директории
        if os.path.exists(normalized_dir):
            # Если существует, проверяем что это директория
            if not os.path.isdir(normalized_dir):
                return False, tr('FileValidator', 'Output path exists but is not a directory')
            
            # Проверяем права на запись
            if not os.access(normalized_dir, os.W_OK):
                return False, tr('FileValidator', 'No permission to write to output directory')
        else:
            # Если директория не существует, проверяем возможность создания
            try:
                parent_dir = os.path.dirname(normalized_dir)
                if not parent_dir:
                    parent_dir = os.getcwd()
                while parent_dir and not os.path.exists(parent_dir):
                    new_parent = os.path.dirname(parent_dir)
                    if new_parent == parent_dir:
                        parent_dir = ''
                        break
                    parent_dir = new_parent
                if not parent_dir:
                    parent_dir = os.getcwd()
                if not os.access(parent_dir, os.W_OK):
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
        
        normalized_dir = FileValidator.normalize_path(output_dir)
        
        # Если директория не существует, создаем её
        if not os.path.exists(normalized_dir):
            try:
                os.makedirs(normalized_dir, exist_ok=True)
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
        normalized_path = FileValidator.normalize_path(file_path)
        try:
            stat = os.stat(normalized_path)
            return {
                'size': stat.st_size,
                'modified': stat.st_mtime,
                'created': stat.st_ctime,
                'readable': os.access(normalized_path, os.R_OK),
                'writable': os.access(normalized_path, os.W_OK)
            }
        except OSError:
            return None
