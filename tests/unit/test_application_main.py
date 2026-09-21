"""
Тесты разбора аргументов запуска.

process_file_argument больше не валидирует: он приводит аргумент к пути на
диске, а причину отказа показывает MainWindow.set_input_file — до правки она
терялась вместе с кодом ошибки, и GUI открывался пустым.
"""

import inspect
from pathlib import Path

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from efd_unpacker.application import main as app_main
from efd_unpacker.application.main import (
    enable_high_dpi_pixmaps,
    looks_like_input,
    process_file_argument,
    should_install_launcher,
)
from efd_unpacker.application.help_text import format_help_text


def assert_same_path(result: str, expected: Path) -> None:
    """
    Сравнение через Path, а не строкой.

    URL всегда несёт прямые слэши, а str(Path) на Windows — обратные:
    C:/Users/x/a.efd и C:\\Users\\x\\a.efd указывают на один файл, но как
    строки не равны. Разделители приводит к системным os.path.abspath уже
    внутри валидатора, поэтому на поведение это не влияет — влияло только
    на строгость самого теста.
    """
    assert Path(result) == expected


class StubTranslator:
    def __init__(self, mapping) -> None:
        self.mapping = mapping

    def translate(self, context: str, source: str) -> str:
        return self.mapping.get((context, source), source)


    def translate_n(self, context: str, source: str, n: int) -> str:
        """Множественная форма: двойнику достаточно подставить число."""
        return self.translate(context, source).replace("%n", str(n))
def test_plain_path_is_returned_unchanged(tmp_path):
    """Обычный путь — не URL, разбирать нечего. Абсолютным его сделает валидатор."""
    assert process_file_argument("input.efd") == "input.efd"
    assert process_file_argument(str(tmp_path / "a.efd")) == str(tmp_path / "a.efd")


def test_file_url_becomes_an_absolute_path(tmp_path):
    input_file = tmp_path / "input.efd"

    assert_same_path(process_file_argument(input_file.as_uri()), input_file)


def test_file_url_decodes_percent_encoding(tmp_path):
    input_file = tmp_path / "файл с пробелом.efd"

    assert_same_path(process_file_argument(input_file.as_uri()), input_file)


# --- схема efd:// ------------------------------------------------------------
#
# Регресс #15: ветка efd:// делала parsed.path.lstrip("/"), поэтому абсолютный
# путь становился относительным, а unquote не вызывался вовсе. Не работала ни
# одна реалистичная форма, включая команду прямо из FILE_ASSOCIATION_GUIDE.


@pytest.mark.parametrize(
    "name",
    ["sample.efd", "файл.efd", "файл с пробелом.efd", "a+b.efd", "100%.efd"],
    ids=["ascii", "кириллица", "пробел", "плюс", "процент"],
)
def test_efd_scheme_matches_the_file_scheme(tmp_path, name):
    """Критерий #15: efd:// обязан давать ровно то же, что эквивалентный file://."""
    input_file = tmp_path / name
    file_url = input_file.as_uri()
    efd_url = _efd_uri(input_file)

    assert process_file_argument(efd_url) == process_file_argument(file_url)
    assert_same_path(process_file_argument(efd_url), input_file)


def _efd_uri(path: Path) -> str:
    """
    efd://-форма того же файла: три слэша, как в документации.

    Собираем из as_uri(), а не из as_posix(): на Windows as_posix() начинается
    с буквы диска, и склейка дала бы efd://C:/... — форму с authority, то есть
    другую ветку разбора, чем на Linux и macOS.
    """
    return "efd://" + path.as_uri()[len("file://"):]


def test_efd_scheme_from_the_documentation(tmp_path, monkeypatch):
    """Форма из docs/FILE_ASSOCIATION_GUIDE.md: efd:///abs/path.efd."""
    input_file = tmp_path / "sample.efd"
    monkeypatch.chdir(tmp_path.parent)

    result = process_file_argument(_efd_uri(input_file))

    assert result.count("/") >= 1
    assert_same_path(result, input_file)


def test_efd_scheme_decodes_percent_encoding(tmp_path):
    input_file = tmp_path / "файл.efd"
    # as_uri() уже даёт percent-encoding для не-ASCII; quote поверх него
    # экранировал бы сами знаки % и проверял бы не то.
    url = _efd_uri(input_file)

    assert "%D1%84" in url, "иначе тест не проверяет декодирование"
    assert_same_path(process_file_argument(url), input_file)


@pytest.mark.parametrize("scheme", ["file", "efd"], ids=["file", "efd"])
def test_windows_drive_letter_is_not_treated_as_a_host(scheme):
    """
    efd://C:/dir/f.efd — буква диска, а не UNC-хост.

    urlparse кладёт «C:» в netloc, и без отдельной ветки путь превратился бы
    в мусор //C:/dir/f.efd.
    """
    assert process_file_argument(f"{scheme}://C:/dir/f.efd") == "C:/dir/f.efd"


def test_localhost_host_is_dropped(tmp_path):
    input_file = tmp_path / "a.efd"
    # Вставляем хост в готовый file://-URL: склейка с as_posix() даёт на
    # Windows "file://localhostC:/..." — netloc "localhostC:" вместо localhost.
    with_localhost = input_file.as_uri().replace("file://", "file://localhost", 1)

    assert_same_path(process_file_argument(with_localhost), input_file)


# --- отбор аргументов, похожих на ввод ---------------------------------------


@pytest.mark.parametrize(
    "argument",
    ["/tmp/a.efd", "A.EFD", "file:///tmp/a.efd", "efd:///tmp/a.efd", "efd://host/x"],
)
def test_input_like_arguments_are_recognized(argument):
    assert looks_like_input(argument) is True


@pytest.mark.parametrize(
    "argument",
    ["-platform", "--style=fusion", "offscreen", "/tmp/a.zip", ""],
)
def test_other_arguments_are_left_to_qt(argument):
    """
    Посторонние флаги запуска не должны порождать «файл не существует».

    main намеренно пропускает нераспознанные аргументы в Qt, а показ причины
    отказа теперь живой — без отбора он бы сработал на каждом таком флаге.
    """
    assert looks_like_input(argument) is False


def test_format_help_text_localizes_headings_and_descriptions():
    translator = StubTranslator(
        {
            ("CLIHelp", "EFD Unpacker - cross-platform EFD file unpacker"): "EFD Unpacker - кроссплатформенный распаковщик файлов EFD",
            ("CLIHelp", "CLI modes:"): "Режимы CLI:",
            ("CLIHelp", "1. GUI mode: open the window and preselect the input file"): "1. Режим GUI: открыть окно и заранее выбрать входной файл",
            ("CLIHelp", "2. Headless mode: unpack directly in the console"): "2. Консольный режим: распаковать напрямую в консоли",
            ("CLIHelp", "Usage:"): "Использование:",
        }
    )

    help_text = format_help_text(translator)

    assert "Режимы CLI:" in help_text
    assert "Использование:" in help_text
    assert "GUI mode: open the window and preselect the input file" not in help_text
    assert "efd_unpacker unpack <file>... -tmplts <dir>" in help_text


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["efd_unpacker", "info", "a.zip"], False),
        (["efd_unpacker", "INFO", "a.zip"], False),
        (["efd_unpacker", "info", "a.zip", "--json"], False),
        (["efd_unpacker", "unpack", "a.efd", "-tmplts", "out"], True),
        (["efd_unpacker", "a.efd"], True),
        (["efd_unpacker"], True),
    ],
)
def test_read_only_command_does_not_register_the_launcher(argv, expected):
    """
    info обещает не создавать ни байта — обещание держится и на бандле.

    install_cli_launcher() создаёт launcher и дописывает экспорт PATH в профили
    оболочки, а зовётся он в main() ДО разбора аргументов. На dev-запуске это
    не видно: resolve_cli_launcher_target() вне бандла отдаёт None.
    """
    assert should_install_launcher(argv) is expected


def test_qt_is_asked_not_to_downscale_icons():
    """
    Без AA_UseHighDpiPixmaps значки кнопок пикселизуются на Retina.

    Рисуются они правильно — вдвое крупнее и с пометкой
    devicePixelRatio=2, — но QIcon.pixmap() без этого атрибута отдаёт кнопке
    копию по ЛОГИЧЕСКОМУ размеру и с dpr=1, а экран растягивает её обратно.
    Замер на настоящем Retina: в значке шестерёнки 54×30 точек, кнопке
    доставалось 24×13; с атрибутом — 48×26.

    Проверяется именно атрибут, а не размер отданного pixmap: тесты идут на
    QT_QPA_PLATFORM=minimal, где devicePixelRatio всегда 1, и уменьшения там
    не происходит ни с атрибутом, ни без. Сравнение пикселей проходило бы
    вхолостую на любой машине, включая ту, где дефект видно глазами.
    """
    enable_high_dpi_pixmaps()

    assert QApplication.testAttribute(Qt.AA_UseHighDpiPixmaps)


def test_startup_asks_for_high_dpi_pixmaps_before_anything_else():
    """
    Атрибут действует только на приложение, созданное ПОСЛЕ него, поэтому
    вызов обязан стоять в main до FileAssociationApp.

    Сам main под pragma: no cover — он поднимает GUI, — так что связь
    проверяется по исходнику. Без этой проверки вызов можно было бы убрать
    из main, и тест выше продолжал бы проходить: он зовёт функцию сам.
    """
    source = inspect.getsource(app_main.main)
    call = source.index("enable_high_dpi_pixmaps()")
    creation = source.index("FileAssociationApp(")

    assert call < creation, "атрибут ставится после создания приложения — он не подействует"
