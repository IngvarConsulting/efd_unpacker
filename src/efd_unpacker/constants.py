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
    # Сколько ждём остановки распаковки при закрытии окна.
    THREAD_STOP_TIMEOUT_MS = 10000


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
    INFO = "info"
    OUTPUT_FLAG = "-tmplts"
    DIST_FLAG = "-dist"
    JSON_FLAG = "--json"
    HELP_FLAGS = ("--help", "-h")
    # Код 2 для ошибки синтаксиса — соглашение getopt и argparse; 1 остаётся
    # за содержательным отказом (файл не найден, архив повреждён).
    EXIT_USAGE = 2


class FileExtensions:
    """Расширения файлов"""
    EFD = ".efd"


class URLSchemes:
    """URL схемы"""
    FILE = "file://"
    EFD = "efd://"
