"""
Обработчик командной строки для приложения EFD Unpacker
"""

import sys
from typing import Optional, Tuple
from file_validator import FileValidator
from unpack_service import UnpackService
from constants import CLICommands


class CLIProcessor:
    """Обработчик командной строки"""
    
    @staticmethod
    def parse_cli_arguments() -> Optional[Tuple[str, str]]:
        """
        Парсит CLI аргументы и возвращает (input_file, output_dir) или None.
        
        Returns:
            Optional[Tuple[str, str]]: (input_file, output_dir) или None если не CLI режим
        """
        if len(sys.argv) >= 5 and sys.argv[1] == CLICommands.UNPACK and sys.argv[3] == CLICommands.OUTPUT_FLAG:
            return sys.argv[2], sys.argv[4]
        return None
    
    @staticmethod
    def process_cli_unpack(input_file: str, output_dir: str) -> bool:
        """
        Обрабатывает CLI команду распаковки.
        
        Args:
            input_file: Путь к входному файлу
            output_dir: Путь к выходной директории
            
        Returns:
            bool: True если распаковка успешна, False иначе
        """
        normalized_input = FileValidator.normalize_path(input_file)
        normalized_output = FileValidator.normalize_path(output_dir)

        # Валидируем входной файл
        is_valid, error_message = FileValidator.validate_efd_file(normalized_input)
        if not is_valid:
            print(f"[ERROR] {error_message}")
            return False
        
        # Валидируем и создаем выходную директорию
        success, error_message = FileValidator.create_output_directory(normalized_output)
        if not success:
            print(f"[ERROR] {error_message}")
            return False
        
        # Выполняем распаковку
        success, message = UnpackService.unpack(normalized_input, normalized_output)
        if success:
            print(f"[OK] {message}")
            return True
        else:
            print(f"[ERROR] {message}")
            return False
    
    @staticmethod
    def handle_cli_mode() -> bool:
        """
        Обрабатывает CLI режим, если он активирован.
        
        Returns:
            bool: True если CLI режим был обработан, False если нужно запустить GUI
        """
        cli_args = CLIProcessor.parse_cli_arguments()
        if cli_args:
            input_file, output_dir = cli_args
            if not input_file:
                print(f"[ERROR] Invalid or missing .efd file: {sys.argv[2]}")
                sys.exit(2)
            
            success = CLIProcessor.process_cli_unpack(input_file, output_dir)
            sys.exit(0 if success else 1)
        
        return False 
