import sys
import os
import urllib.parse
from ui import MainWindow
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEvent, QTimer
import onec_dtools

def process_file_argument(file_path):
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

def cli_unpack(input_file, output_dir):
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
    
    def __init__(self, argv):
        super().__init__(argv)
        self.window = None
        self.pending_files = []
        
        # Устанавливаем обработчик событий
        self.installEventFilter(self)
        
        # Таймер для обработки отложенных файлов
        self.file_timer = QTimer()
        self.file_timer.setSingleShot(True)
        self.file_timer.timeout.connect(self.process_pending_files)
    
    def set_window(self, window):
        """Установить главное окно"""
        self.window = window
        # Обрабатываем отложенные файлы
        if self.pending_files:
            self.process_pending_files()
    
    def process_file(self, file_path):
        """Обработать файл"""
        processed_path = process_file_argument(file_path)
        if processed_path and self.window:
            try:
                self.window.set_input_file(processed_path)
                return True
            except Exception:
                pass
        return False
    
    def eventFilter(self, obj, event):
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
    
    def process_pending_files(self):
        """Обработать отложенные файлы"""
        if self.window and self.pending_files:
            for file_path in self.pending_files:
                if self.process_file(file_path):
                    break  # Обрабатываем только первый валидный файл
            self.pending_files.clear()

def main():
    # CLI режим: EFDUnpacker unpack /path/to/file.efd -tmplts /path/to/dir
    if len(sys.argv) >= 5 and sys.argv[1] == 'unpack' and sys.argv[3] == '-tmplts':
        input_file = process_file_argument(sys.argv[2])
        output_dir = sys.argv[4]
        if not input_file:
            print(f"[ERROR] Invalid or missing .efd file: {sys.argv[2]}")
            sys.exit(2)
        ok = cli_unpack(input_file, output_dir)
        sys.exit(0 if ok else 1)

    app = FileAssociationApp(sys.argv)
    
    # Получаем аргументы через Qt для fallback
    qt_args = app.arguments()
    
    window = MainWindow()
    app.set_window(window)
    
    # Fallback: обрабатываем аргументы командной строки, если Apple Events не сработали
    if len(qt_args) > 1:
        for arg in qt_args[1:]:
            file_path = process_file_argument(arg)
            if file_path:
                try:
                    window.set_input_file(file_path)
                    break  # Обрабатываем только первый валидный файл
                except Exception:
                    pass  # Игнорируем ошибки при установке файла
    
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
