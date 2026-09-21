"""
Точка входа приложения: сначала пытаемся обработать CLI, затем запускаем GUI.
"""

from __future__ import annotations

import sys
import urllib.parse
from typing import Optional

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import QApplication

from ..constants import FileExtensions, URLSchemes
from ..domain.file_validator import FileValidator
from ..domain.unpack_service import UnpackService
from ..infrastructure.settings_service import SettingsService
from ..localization.translator import create_translator
from ..presentation.ui import MainWindow
from ..runtime import detect_system_language, install_cli_launcher
from .cli import CLIApplication, is_read_only_command, wants_help
from .help_text import format_help_text


def enable_high_dpi_pixmaps() -> None:
    """
    Просит Qt не срезать разрешение у значков. До создания QApplication.

    Значки шестерёнки и «назад» рисуются вдвое крупнее и помечаются
    devicePixelRatio=2 — но без этого атрибута QIcon.pixmap() отдаёт кнопке
    копию по ЛОГИЧЕСКОМУ размеру и с dpr=1, а экран растягивает её обратно
    вдвое. Замер на Retina: в значке 54×30 точек, кнопке доставалось 24×13.

    Отдельной функцией, а не строкой в main: main поднимает GUI и покрытием
    не берётся, а так шаг можно позвать и проверить.
    """
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def looks_like_input(argument: str) -> bool:
    """
    Похож ли аргумент на файл или ссылку, которую пользователь хотел открыть.

    Нужен, чтобы посторонние флаги запуска Qt (-platform, -style и прочие)
    не порождали сообщение «файл не существует»: main намеренно пропускает
    нераспознанные аргументы в Qt, а не завершается на них.
    """
    lowered = argument.lower()
    return (
        lowered.endswith(FileExtensions.EFD)
        or lowered.startswith(URLSchemes.FILE)
        or lowered.startswith(URLSchemes.EFD)
    )


def process_file_argument(file_path: str) -> str:
    """
    Приводит аргумент к пути на диске: URL-схемы, percent-encoding, буква диска.

    Валидации здесь больше нет. Раньше функция ловила FileValidationError и
    возвращала None, теряя код ошибки, а обе ветки показа причины в main()
    были мертвы: MainWindow.set_input_file сам ловит исключение и сам
    показывает локализованный QMessageBox.
    """
    for scheme in (URLSchemes.FILE, URLSchemes.EFD):
        if file_path.startswith(scheme):
            return _path_from_url(file_path)
    return file_path


def _path_from_url(url: str) -> str:
    """
    Общий разбор для file:// и efd://.

    Раньше ветка efd:// делала parsed.path.lstrip("/") — абсолютный путь
    становился относительным, netloc терялся вместе с буквой диска, а
    percent-encoding не раскрывался вовсе. Работала только форма
    efd:///относительный/путь, которой нет ни в одном документе.
    """
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path)
    netloc = urllib.parse.unquote(parsed.netloc)

    if netloc and netloc != "localhost":
        # efd://C:/dir/f.efd — буква диска, а не UNC-хост: без этой ветки
        # путь превратился бы в //C:/dir/f.efd.
        path = f"{netloc}{path}" if netloc.endswith(":") else f"//{netloc}{path}"

    if sys.platform.startswith("win") and len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


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
        if not self.window:
            return False
        try:
            # Признак успеха — результат set_input_file, а не истинность пути:
            # путь непустой и для несуществующего файла.
            return bool(self.window.set_input_file(process_file_argument(file_path)))
        except Exception:
            # Исключение из eventFilter убивает процесс по SIGABRT, поэтому
            # наружу отсюда не выпускаем ничего.
            return False

    def eventFilter(self, obj, event) -> bool:  # pragma: no cover - Qt binding
        if event.type() == QEvent.Type.FileOpen:
            # Для не-file схемы toLocalFile() пуст, и событие раньше гасилось
            # без следа: клик по efd://-ссылке на macOS не доходил до разбора.
            file_path = event.url().toLocalFile() or event.url().toString()
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


def should_install_launcher(argv: list) -> bool:
    """
    Регистрировать ли команду в PATH при этом запуске.

    Регистрация пишет на диск: создаёт launcher и дописывает экспорт PATH в
    профили оболочки, с резервной копией. Для info это недопустимо — команда
    обещает не создавать ни байта, и обещание должно держаться и на собранном
    приложении, где launcher вообще существует. Проверено на dev-запуске быть
    не может: resolve_cli_launcher_target() отдаёт None вне бандла.
    """
    return not is_read_only_command(argv)


def main() -> None:  # pragma: no cover - интеграция с PyQt
    enable_high_dpi_pixmaps()
    if should_install_launcher(sys.argv):
        try:
            install_cli_launcher()
        except Exception:
            # Регистрация команды в PATH — удобство, а не условие запуска.
            pass

    translator = create_translator(detect_system_language())

    # Помощь ищется по всему argv, а не только в argv[1]: `unpack --help`
    # раньше поднимал пустое окно. Полный argparse тут не подходит — main
    # намеренно пропускает нераспознанные аргументы в Qt и в обработку
    # файловых ассоциаций, а argparse на неизвестном аргументе делает exit(2).
    if wants_help(sys.argv[1:]):
        print(format_help_text(translator))
        sys.exit(0)

    validator = FileValidator()

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
    for arg in qt_args[1:]:
        # set_input_file сам валидирует и сам показывает локализованный
        # QMessageBox с причиной — прежние ветки показа ошибки здесь были
        # недостижимы, потому что исключение до них не доходило.
        if looks_like_input(arg) and window.set_input_file(process_file_argument(arg)):
            break

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":  # pragma: no cover
    main()
