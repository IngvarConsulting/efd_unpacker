"""
Константы для приложения EFD Unpacker
"""

from enum import Enum


class UIConstants:
    """Константы для пользовательского интерфейса"""
    WINDOW_WIDTH = 500
    WINDOW_HEIGHT = 250
    LOADING_ICON_SIZE = 96
    COMBO_MIN_WIDTH = 200
    LOADING_MARGIN = 20


class UIState(Enum):
    """Состояния пользовательского интерфейса"""
    NORMAL = "normal"
    LOADING = "loading"
    SUCCESS = "success"
    ERROR = "error"


class Styles:
    """CSS стили для UI элементов"""
    INPUT_NORMAL = "border: 2px dashed #aaa; padding: 20px; text-decoration: underline; color: #0078d7;"
    INPUT_DRAG = "border: 2px dashed #0078d7; background: #e6f2ff; color: #000000; padding: 20px;"
    INPUT_SUCCESS = "border: 2px solid #4caf50; padding: 20px; background: #f1fff1; color: #000000;"
    MESSAGE_SUCCESS = "color: #4caf50; font-size: 16px;"
    MESSAGE_ERROR = "color: #d32f2f; font-size: 16px;"
    LOADING_LABEL = """
        QLabel { 
            margin: 20px; 
        }
    """


class CLICommands:
    """Команды командной строки"""
    UNPACK = "unpack"
    OUTPUT_FLAG = "-tmplts"


class FileExtensions:
    """Расширения файлов"""
    EFD = ".efd"


class URLSchemes:
    """URL схемы"""
    FILE = "file://"
    EFD = "efd://" 