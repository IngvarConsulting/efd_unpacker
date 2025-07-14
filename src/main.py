import sys
import os
import urllib.parse
from ui import MainWindow
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QEvent, QTimer, QLocale
from file_validator import FileValidator
from cli_processor import CLIProcessor
from constants import URLSchemes
from typing import Optional
from tr import translator

def process_file_argument(file_path: str) -> Optional[str]:
    """Обработать аргумент файла, поддерживая URL схемы и относительные пути"""
    # Обработка URL схемы file:// (macOS может передавать файлы так)
    if file_path.startswith(URLSchemes.FILE):
        # Убираем file:// префикс и декодируем URL
        file_path = urllib.parse.unquote(file_path[7:])
    
    # Обработка URL схемы efd://
    elif file_path.startswith(URLSchemes.EFD):
        parsed = urllib.parse.urlparse(file_path)
        file_path = parsed.path
        if file_path.startswith('/'):
            file_path = file_path[1:]  # Убираем ведущий слеш
    
    # Преобразуем относительный путь в абсолютный
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)
    
    # Используем FileValidator для валидации файла
    is_valid, _ = FileValidator.validate_efd_file(file_path)
    if not is_valid:
        return None
    
    return file_path

class FileAssociationApp(QApplication):
    """Приложение с поддержкой Apple Events для файловых ассоциаций в macOS"""
    
    def __init__(self, argv: list) -> None:
        super().__init__(argv)
        self.window: Optional[MainWindow] = None
        self.pending_files: list[str] = []
        
        # Устанавливаем обработчик событий
        self.installEventFilter(self)
        
        # Таймер для обработки отложенных файлов
        self.file_timer = QTimer()
        self.file_timer.setSingleShot(True)
        self.file_timer.timeout.connect(self.process_pending_files)
    
    def set_window(self, window: MainWindow) -> None:
        """Установить главное окно"""
        self.window = window
        # Обрабатываем отложенные файлы
        if self.pending_files:
            self.process_pending_files()
    
    def process_file(self, file_path: str) -> bool:
        """Обработать файл"""
        processed_path = process_file_argument(file_path)
        if processed_path and self.window:
            try:
                self.window.set_input_file(processed_path)
                return True
            except Exception:
                pass
        return False
    
    def eventFilter(self, obj, event) -> bool:
        """Обработчик событий для получения файлов через Apple Events"""
        # В PyQt6 QEvent.Type.FileOpen доступен напрямую
        if event.type() == QEvent.Type.FileOpen:
            file_open_event = event
            file_path = file_open_event.url().toLocalFile()
            if file_path:
                if self.window:
                    self.process_file(file_path)
                else:
                    self.pending_files.append(file_path)
            return True
        return super().eventFilter(obj, event)
    
    def process_pending_files(self) -> None:
        """Обработать отложенные файлы"""
        if self.window and self.pending_files:
            for file_path in self.pending_files:
                if self.process_file(file_path):
                    break  # Обрабатываем только первый валидный файл
            self.pending_files.clear()

def main() -> None:
    # Поддержка --help без GUI
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print("""
EFD Unpacker - cross-platform EFD file unpacker

Usage:
  efd_unpacker [--help|-h]
  efd_unpacker unpack <input_file.efd> -tmplts <output_dir>

Options:
  --help, -h         Show this help message and exit

GUI mode:
  efd_unpacker [file.efd]   # Open file in GUI

CLI mode:
  efd_unpacker unpack <input_file.efd> -tmplts <output_dir>
      Unpack EFD file to output directory without GUI

Examples:
  efd_unpacker --help
  efd_unpacker unpack data.efd -tmplts outdir
  efd_unpacker data.efd
""")
        sys.exit(0)
    # Обрабатываем CLI режим
    if CLIProcessor.handle_cli_mode():
        return  # CLI режим уже обработан, выходим

    # Определяем язык приложения через QLocale
    qt_locale = QLocale.system()
    language = 'ru' if qt_locale.language() == QLocale.Language.Russian else 'en'
    # Создаем приложение
    app = FileAssociationApp(sys.argv)
    
    # Настраиваем язык для собственного переводчика
    translator.lang = language
    translator._load_translations()

    # Обрабатываем файлы из командной строки
    qt_args = app.arguments()
    window = MainWindow()
    app.set_window(window)
    
    if len(qt_args) > 1:
        for arg in qt_args[1:]:
            file_path = process_file_argument(arg)
            if file_path:
                try:
                    window.set_input_file(file_path)
                    break
                except Exception:
                    pass
    
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
