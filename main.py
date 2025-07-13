import sys
import os
import urllib.parse
from ui import MainWindow
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEvent, QLocale, QTimer, QTranslator
from unpack_service import UnpackService
from typing import Optional

def process_file_argument(file_path: str) -> Optional[str]:
    """Обработать аргумент файла, поддерживая URL схемы и относительные пути"""
    # Обработка URL схемы file:// (macOS может передавать файлы так)
    if file_path.startswith('file://'):
        # Убираем file:// префикс и декодируем URL
        file_path = urllib.parse.unquote(file_path[7:])
    
    # Обработка URL схемы efd://
    elif file_path.startswith('efd://'):
        parsed = urllib.parse.urlparse(file_path)
        file_path = parsed.path
        if file_path.startswith('/'):
            file_path = file_path[1:]  # Убираем ведущий слеш
    
    # Преобразуем относительный путь в абсолютный
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)
    
    # Проверяем существование файла
    if not os.path.exists(file_path):
        return None
    
    # Проверяем расширение
    if not file_path.lower().endswith('.efd'):
        return None
    
    return file_path

def cli_unpack(input_file: str, output_dir: str) -> bool:
    """CLI-распаковка без GUI. Возвращает True/False."""
    success, message = UnpackService.unpack(input_file, output_dir)
    if success:
        print(f"[OK] {message}")
        return True
    else:
        print(f"[ERROR] {message}")
        return False

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
    # CLI режим: EFDUnpacker unpack /path/to/file.efd -tmplts /path/to/dir
    if len(sys.argv) >= 5 and sys.argv[1] == 'unpack' and sys.argv[3] == '-tmplts':
        input_file = process_file_argument(sys.argv[2])
        output_dir = sys.argv[4]
        if not input_file:
            print(f"[ERROR] Invalid or missing .efd file: {sys.argv[2]}")
            sys.exit(2)
        ok = cli_unpack(input_file, output_dir)
        sys.exit(0 if ok else 1)

    # Используем стандартную Qt локаль
    system_locale = QLocale.system()
    locale_name = system_locale.name()
    
    # Определяем язык более точно
    if 'ru' in locale_name.lower():
        lang = 'ru'
    elif 'en' in locale_name.lower():
        lang = 'en'
    else:
        # Fallback на язык из системной локали
        lang = system_locale.language()
        if lang == QLocale.Language.Russian:
            lang = 'ru'
        elif lang == QLocale.Language.English:
            lang = 'en'
        else:
            lang = 'en'

    app = FileAssociationApp(sys.argv)
    
    # Устанавливаем локаль приложения
    if lang == 'ru':
        locale = QLocale(QLocale.Language.Russian, QLocale.Country.Russia)
    else:
        locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
    
    QLocale.setDefault(locale)
    
    # Загружаем наш собственный перевод
    translator = QTranslator()
    # Определяем путь к папке с переводами
    if getattr(sys, 'frozen', False):
        # Если приложение собрано (PyInstaller)
        translations_path = os.path.join(os.path.dirname(sys.executable), '..', 'Resources', 'translations')
    else:
        # Если запускаем из исходников
        translations_path = 'translations'
    
    app_loaded = translator.load(f'{lang}.qm', translations_path)
    print(f"App translator loaded: {app_loaded}")
    app.installTranslator(translator)

    qt_args = app.arguments()
    window = MainWindow(language=lang)
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
