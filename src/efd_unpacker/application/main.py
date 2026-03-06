"""
Точка входа приложения: сначала пытаемся обработать CLI, затем запускаем GUI.
"""

from __future__ import annotations

import sys
import urllib.parse
from typing import Optional

from PyQt5.QtCore import QEvent, QTimer
from PyQt5.QtWidgets import QApplication

from ..constants import URLSchemes
from ..domain.errors import FileValidationError
from ..domain.file_validator import FileValidator
from ..domain.unpack_service import UnpackService
from ..infrastructure.settings_service import SettingsService
from ..localization.translator import create_translator
from ..presentation.ui import MainWindow
from ..runtime import detect_system_language, install_cli_launcher
from .cli import CLIApplication
from .messages import format_validation_error


def process_file_argument(file_path: str, validator: FileValidator) -> Optional[str]:
    """Обработать аргумент файла, поддерживая URL схемы и относительные пути."""
    if file_path.startswith(URLSchemes.FILE):
        file_path = urllib.parse.unquote(file_path[7:])
    elif file_path.startswith(URLSchemes.EFD):
        parsed = urllib.parse.urlparse(file_path)
        file_path = parsed.path.lstrip("/")

    try:
        return validator.validate_input_file(file_path)
    except FileValidationError:
        return None


class FileAssociationApp(QApplication):
    """Приложение с поддержкой Apple Events для файловых ассоциаций в macOS."""

    def __init__(self, argv: list[str], validator: FileValidator) -> None:
        super().__init__(argv)
        self.validator = validator
        self.window: Optional[MainWindow] = None
        self.pending_files: list[str] = []
        self.installEventFilter(self)

        self.file_timer = QTimer()
        self.file_timer.setSingleShot(True)
        self.file_timer.timeout.connect(self.process_pending_files)

    def set_window(self, window: MainWindow) -> None:
        self.window = window
        if self.pending_files:
            self.process_pending_files()

    def process_file(self, file_path: str) -> bool:
        processed_path = process_file_argument(file_path, self.validator)
        if processed_path and self.window:
            try:
                self.window.set_input_file(processed_path)
                return True
            except Exception:
                return False
        return False

    def eventFilter(self, obj, event) -> bool:  # pragma: no cover - Qt binding
        if event.type() == QEvent.Type.FileOpen:
            file_path = event.url().toLocalFile()
            if file_path:
                if self.window:
                    self.process_file(file_path)
                else:
                    self.pending_files.append(file_path)
            return True
        return super().eventFilter(obj, event)

    def process_pending_files(self) -> None:
        if self.window and self.pending_files:
            for file_path in self.pending_files:
                if self.process_file(file_path):
                    break
            self.pending_files.clear()


def main() -> None:  # pragma: no cover - интеграция с PyQt
    install_cli_launcher()

    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(
            """
EFD Unpacker - cross-platform EFD file unpacker

CLI modes:
  1. GUI mode: open the window and preselect the input file
  2. Headless mode: unpack directly in the console

Usage:
  efd_unpacker [--help|-h]
  efd_unpacker <input_file.efd>
  efd_unpacker unpack <input_file.efd> -tmplts <output_dir>
"""
        )
        sys.exit(0)

    validator = FileValidator()
    translator = create_translator(detect_system_language())

    cli_app = CLIApplication(validator, UnpackService(), translator)
    cli_result = cli_app.run(sys.argv)
    if cli_result.handled:
        sys.exit(cli_result.exit_code)

    app = FileAssociationApp(sys.argv, validator)
    settings_service = SettingsService(translator)
    window = MainWindow(
        translator=translator,
        settings_service=settings_service,
        file_validator=validator,
        unpack_service=UnpackService(),
    )
    app.set_window(window)

    qt_args = app.arguments()
    if len(qt_args) > 1:
        for arg in qt_args[1:]:
            file_path = process_file_argument(arg, validator)
            if file_path:
                try:
                    window.set_input_file(file_path)
                    break
                except FileValidationError as exc:
                    error_message = format_validation_error(translator, exc)
                    window.show_message(error_message, is_error=True)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":  # pragma: no cover
    main()
