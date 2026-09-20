"""
Тесты экранов меню настроек.

Главное требование к ним одно: экран не должен выдумывать. Путь, программа,
версия и лицензия — это то, по чему человек принимает решение, и
правдоподобное вместо настоящего здесь хуже пустоты. Поэтому большинство
тестов сравнивает показанное с источником, а не с ожидаемой строкой.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
os.environ.setdefault("QT_API", "pyqt5")

from pathlib import Path

import pytest
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication, QLabel, QMessageBox, QRadioButton

from efd_unpacker.infrastructure import rar
from efd_unpacker.infrastructure.settings_service import SettingsService
from efd_unpacker.presentation import screens, style

ROOT = Path(__file__).resolve().parents[2]


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return source


@pytest.fixture
def translator():
    return DummyTranslator()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Настройки на своём файле: тест не трогает профиль машины."""
    monkeypatch.setattr(
        "efd_unpacker.infrastructure.settings_service.get_1c_configuration_location_default",
        lambda: str(tmp_path / "default" / "tmplts"),
    )
    monkeypatch.setattr(
        "efd_unpacker.infrastructure.settings_service.get_1c_configuration_location_from_1cestart",
        lambda: [str(tmp_path / "from1c" / "tmplts")],
    )
    return SettingsService(
        translator=DummyTranslator(),
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat),
    )


def texts(widget, kind=QLabel):
    return [child.text() for child in widget.findChildren(kind)]


def radio(screen, path):
    """Переключатель с этой подписью. Вариантов немного, поиск по тексту честен."""
    for button in screen.findChildren(QRadioButton):
        if button.text() == path:
            return button
    raise AssertionError("нет варианта %r среди %r" % (path, texts(screen, QRadioButton)))


def named(screen, name):
    """
    Переключатель по имени: «выбрать другую папку» есть в обоих разделах, и
    поиск по подписи нашёл бы не тот.
    """
    button = screen.findChild(QRadioButton, name)
    assert button is not None, "нет переключателя %r" % name
    return button


# --- куда распаковывать ------------------------------------------------------


def test_every_variant_shows_where_it_came_from(qtbot, translator, settings, tmp_path):
    """
    Критерий #66: происхождение пути видно у каждого варианта.

    Выбирая между тремя похожими путями, человек ориентируется не на их вид —
    все три кончаются на tmplts, — а на то, откуда каждый взялся.
    """
    settings.set_output_path(str(tmp_path / "last" / "tmplts"))
    screen = screens.PathsScreen(translator, settings)
    qtbot.addWidget(screen)

    shown = texts(screen)
    for choice in settings.get_output_path_items():
        assert choice.path in texts(screen, QRadioButton)
    assert "used last time" in shown
    assert "from 1cestart.cfg" in shown
    assert "by default" in shown


def test_picking_a_templates_variant_saves_it_and_announces(qtbot, translator, settings, tmp_path):
    """Критерий #66: выбор в экране меняет настройку и сообщает об этом окну."""
    screen = screens.PathsScreen(translator, settings)
    qtbot.addWidget(screen)
    chosen = str(tmp_path / "from1c" / "tmplts")

    with qtbot.waitSignal(screen.changed, timeout=1000):
        radio(screen, chosen).click()

    assert settings.get_output_path() == chosen


def test_distributions_follow_the_templates_until_chosen_by_hand(
    qtbot, translator, settings, tmp_path, monkeypatch
):
    """Каталог дистрибутивов вычисляется от шаблонов, пока его не задали явно."""
    settings.set_output_path(str(tmp_path / "srv" / "tmplts"))
    screen = screens.PathsScreen(translator, settings)
    qtbot.addWidget(screen)
    computed = os.path.normpath(str(tmp_path / "srv" / "dist"))
    assert settings.get_distributions_path() == computed

    chosen = str(tmp_path / "хранилище")
    monkeypatch.setattr(screen, "_ask", lambda *_args: chosen)
    named(screen, "distributions-browse").click()

    assert settings.get_distributions_path() == chosen
    assert settings.distributions_path_is_explicit() is True


def test_returning_to_the_computed_root_clears_the_explicit_one(
    qtbot, translator, settings, tmp_path
):
    """
    Возврат к вычисляемому стирает явный выбор, а не пишет то же значение.

    Записью того же пути от своего выбора нельзя было бы отказаться — только
    сменить его на такой же, — и дистрибутивы навсегда перестали бы ходить
    за шаблонами.
    """
    settings.set_output_path(str(tmp_path / "srv" / "tmplts"))
    settings.set_distributions_path(str(tmp_path / "хранилище"))
    screen = screens.PathsScreen(translator, settings)
    qtbot.addWidget(screen)
    computed = os.path.normpath(str(tmp_path / "srv" / "dist"))

    radio(screen, computed).click()

    assert settings.distributions_path_is_explicit() is False
    assert settings.get_distributions_path() == computed


def test_cancelled_dialog_changes_nothing(qtbot, translator, settings, tmp_path, monkeypatch):
    """
    Отказ от выбора папки оставляет настройку как была.

    И отметку тоже: «Выбрать другую папку…» — это действие, а не вариант, и
    отмеченной после отказа должна остаться прежняя строка.
    """
    settings.set_output_path(str(tmp_path / "srv" / "tmplts"))
    screen = screens.PathsScreen(translator, settings)
    qtbot.addWidget(screen)
    monkeypatch.setattr(screen, "_ask", lambda *_args: "")

    named(screen, "templates-browse").click()

    assert settings.get_output_path() == str(tmp_path / "srv" / "tmplts")
    assert named(screen, "templates-0").isChecked()
    assert not named(screen, "templates-browse").isChecked()


def test_space_line_shows_free_and_needed(qtbot, translator, settings):
    screen = screens.PathsScreen(translator, settings)
    qtbot.addWidget(screen)

    screen.set_needed(3 * 1024 ** 3)

    assert "free" in screen.label_space.text()
    assert "needed 3" in screen.label_space.text()


def test_space_line_warns_when_it_does_not_fit(qtbot, translator, settings):
    """
    Не влезает — единственное, что стоит сказать про место заранее.

    Отказ на середине распаковки обходится дороже, чем цвет в подвале.
    """
    screen = screens.PathsScreen(translator, settings)
    qtbot.addWidget(screen)

    screen.set_needed(1)
    calm = screen.label_space.styleSheet()
    screen.set_needed(1 << 60)

    assert style.ALERT not in calm
    assert style.ALERT in screen.label_space.styleSheet()


def test_free_space_is_read_from_an_existing_parent(tmp_path):
    """
    Каталог создаётся перед распаковкой, а место интересно до неё.

    Спросить про несуществующий путь напрямую нельзя — disk_usage отвечает
    отказом, и подвал остался бы пустым ровно тогда, когда нужен.
    """
    missing = tmp_path / "нет" / "такого" / "каталога"

    assert screens.free_bytes(str(missing)) == screens.free_bytes(str(tmp_path))


def test_free_space_gives_up_instead_of_looping(monkeypatch):
    """Том без ответа — не повод крутиться вечно в поиске предка."""
    monkeypatch.setattr(screens.shutil, "disk_usage", _refuse)

    assert screens.free_bytes(os.path.join(os.sep, "a", "b")) is None


def _refuse(_path):
    raise OSError("нет такого тома")


# --- инструменты для .rar ----------------------------------------------------


def tool(path="/usr/bin/bsdtar", family=rar.LIBARCHIVE, version="bsdtar 3.5.3 - libarchive 3.7.4"):
    return rar.Tool(path=path, family=family, version=version)


def tools_screen(qtbot, translator, found=()):
    """Экран с подменённым поиском: без потока и без запуска чужих программ."""
    screen = screens.ToolsScreen(translator, discover=lambda: found, start_search=lambda: None)
    qtbot.addWidget(screen)
    screen.show_tools(found)
    return screen


def test_found_program_is_shown_with_its_path(qtbot, translator):
    """Критерий #66: экран показывает найденное на этой машине."""
    screen = tools_screen(qtbot, translator, found=(tool(),))

    shown = texts(screen)
    assert any("/usr/bin/bsdtar" in line for line in shown)
    assert "IN USE" in shown


def test_long_version_banner_is_cut_down_to_the_number(qtbot, translator):
    """
    Ответ bsdtar длиной в семьдесят знаков вытесняет путь — то единственное,
    ради чего строку и читают.
    """
    screen = tools_screen(qtbot, translator, found=(tool(),))

    assert any("libarchive 3.7.4" in line for line in texts(screen))
    assert not any("zlib" in line for line in texts(screen))


@pytest.mark.parametrize(
    "version, family, expected",
    [
        ("bsdtar 3.5.3 - libarchive 3.7.4 zlib/1.2.12", rar.LIBARCHIVE, "libarchive 3.7.4"),
        ("7-Zip (z) 23.01 (x64) : Copyright (c) 1999-2023", rar.SEVENZIP, "7-Zip 23.01"),
        ("", rar.LIBARCHIVE, ""),
        ("bsdtar без номера", rar.LIBARCHIVE, ""),
    ],
    ids=["libarchive", "7zip", "молчит", "без номера"],
)
def test_short_version_on_real_banners(version, family, expected):
    assert screens.short_version(tool(family=family, version=version)) == expected


def test_missing_family_names_what_was_searched(qtbot, translator):
    """
    «Не найден» несёт смысл только рядом с именем того, кого искали.

    Иначе человеку нечего набрать в поисковике и нечего проверить в PATH.
    """
    screen = tools_screen(qtbot, translator, found=())

    shown = texts(screen)
    assert "not found" in shown
    for family in rar.known_families():
        assert rar.FAMILY_TITLES[family] in shown
        assert any(name in line for name in rar.searched_names(family) for line in shown)


def test_second_program_is_spare_not_in_use(qtbot, translator):
    """
    Используется первая по очереди: оглавление читает первая, которая
    справится, остальные остаются про запас.
    """
    screen = tools_screen(
        qtbot, translator,
        found=(tool(), tool(path="/usr/local/bin/7zz", family=rar.SEVENZIP, version="7-Zip 23.01")),
    )

    shown = texts(screen)
    assert shown.count("IN USE") == 1
    assert "spare" in shown


def test_install_command_is_shown_but_never_run(qtbot, translator, monkeypatch):
    """
    Решение из #54: установку показываем, но не запускаем.

    winget и brew просят повышения прав и задают свои вопросы, а человек
    вправе знать, что ставится в его систему, до того как это произойдёт.
    """
    monkeypatch.setattr(screens.rar.subprocess, "run", _forbidden)
    monkeypatch.setattr(screens.rar.subprocess, "Popen", _forbidden)
    screen = tools_screen(qtbot, translator, found=())

    assert rar.install_hint() in texts(screen)

    screen.copy_command()
    assert QApplication.clipboard().text() == rar.install_hint()


def _forbidden(*_args, **_kwargs):
    raise AssertionError("экран настроек не запускает установку")


def test_install_command_is_absent_when_everything_is_found(qtbot, translator):
    """Нечего ставить — незачем и предлагать."""
    found = tuple(tool(path="/x/" + family, family=family) for family in rar.known_families())

    screen = tools_screen(qtbot, translator, found=found)

    assert rar.install_hint() not in texts(screen)


def test_probe_line_belongs_to_the_program_that_read_the_archive(qtbot, translator, monkeypatch):
    """
    «Проверена на вашем архиве» — запись о настоящей проверке, а не украшение.

    Пригодность проверяется на самом архиве, и приписать её другой программе
    значит соврать ровно о том, ради чего экран и открывают.
    """
    reader = tool()
    other = tool(path="/usr/local/bin/7zz", family=rar.SEVENZIP, version="7-Zip 23.01")
    monkeypatch.setattr(
        rar, "last_probe",
        lambda: rar.Probe(tool=reader, archive="setuptc64.rar", entries=44),
    )

    screen = tools_screen(qtbot, translator, found=(reader, other))

    probed = [line for line in texts(screen) if "setuptc64.rar" in line]
    assert probed == ["checked on setuptc64.rar: 44 entries"]


def test_nothing_is_claimed_about_a_program_that_was_never_probed(qtbot, translator, monkeypatch):
    monkeypatch.setattr(rar, "last_probe", lambda: None)

    screen = tools_screen(qtbot, translator, found=(tool(),))

    # Подстрока «checked on» есть и в пояснении внизу экрана, поэтому ищем
    # ровно ту форму, которой отчитывается о проверке строка программы.
    assert not any(line.startswith("checked on ") for line in texts(screen))


def test_search_again_forgets_what_was_known(qtbot, translator, monkeypatch):
    """
    Критерий #66: «Искать заново» действительно ищет, а не перерисовывает.

    Поиск кешируется на весь запуск, и без сброса кнопка показывала бы тот же
    список даже после установки программы.
    """
    forgotten = []
    monkeypatch.setattr(rar, "forget", lambda: forgotten.append(True))
    screen = tools_screen(qtbot, translator, found=())

    screen.rescan()

    assert forgotten == [True]


def test_screen_says_it_is_searching_until_the_answer_arrives(qtbot, translator):
    """Поиск уходит в поток, и до ответа экрану есть что сказать."""
    screen = screens.ToolsScreen(translator, discover=lambda: (), start_search=lambda: None)
    qtbot.addWidget(screen)

    assert "Searching…" in texts(screen)
    assert not screen.button_rescan.isEnabled()

    screen.show_tools(())
    assert "Searching…" not in texts(screen)
    assert screen.button_rescan.isEnabled()


def test_search_runs_in_a_thread_not_in_the_window(qtbot, translator):
    """
    Поиск запускает каждого кандидата за номером версии, а предел ожидания
    такого запуска — двадцать секунд. В потоке окна это двадцать секунд
    замершего окна.
    """
    marker = tool(path="/из/потока")
    screen = screens.ToolsScreen(translator, discover=lambda: (marker,))
    qtbot.addWidget(screen)

    qtbot.waitUntil(lambda: not screen.button_rescan.isEnabled() is False, timeout=2000)
    qtbot.waitUntil(lambda: "/из/потока" in " ".join(texts(screen)), timeout=2000)
    screen.wait()


# --- о программе -------------------------------------------------------------


def test_link_failure_is_reported_not_swallowed(qtbot, translator, monkeypatch):
    """
    Критерий #66: отказ открытия сообщается.

    openUrl возвращает ложь, когда обработчика нет вовсе — на голой Linux без
    xdg-utils это обычное дело. Промолчать значит оставить человека с
    кнопкой, которая ничего не делает и не объясняет почему.
    """
    warned = []
    monkeypatch.setattr(screens.QDesktopServices, "openUrl", lambda _url: False)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warned.append(args[2])
    )
    screen = screens.AboutScreen(translator, "2.0.0")
    qtbot.addWidget(screen)

    screen._open_url(screens.COMPANY_URL)

    assert warned and screens.COMPANY_URL in warned[0]


def test_link_opens_in_the_system_browser(qtbot, translator, monkeypatch):
    """Критерий #66: ссылка на сайт открывается системным браузером."""
    opened = []
    monkeypatch.setattr(
        screens.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) is None
    )
    monkeypatch.setattr(QMessageBox, "warning", _unexpected_warning)
    screen = screens.AboutScreen(translator, "2.0.0")
    qtbot.addWidget(screen)

    screen._open_url(screens.COMPANY_URL)

    assert opened == [screens.COMPANY_URL]


def _unexpected_warning(*_args, **_kwargs):
    raise AssertionError("удачное открытие не должно ни о чём предупреждать")


def test_about_shows_version_and_licenses(qtbot, translator):
    screen = screens.AboutScreen(translator, "2.0.0")
    qtbot.addWidget(screen)

    shown = texts(screen)
    assert "2.0.0" in shown
    for name, license_name in screens.LICENSES:
        assert name in shown
        assert license_name in shown


def test_license_list_covers_every_runtime_dependency():
    """
    Зависимость добавят, а в экран дописать забудут — и он начнёт умалчивать.

    Сверка идёт с requirements.txt: именно он попадает в сборку, и именно его
    правят, добавляя библиотеку.
    """
    from packaging.requirements import Requirement

    listed = {name.lower() for name, _license in screens.LICENSES}
    required = {
        Requirement(line).name.lower()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert not required - listed, "нет в списке лицензий: %s" % sorted(required - listed)


def test_licenses_document_exists_where_the_screen_points():
    """Ссылка «Полные тексты» ведёт в документ, а не в четыреста четвёртую."""
    assert screens.LICENSES_URL.endswith("docs/LICENSES.md")
    assert (ROOT / "docs" / "LICENSES.md").is_file()


def test_logo_ships_with_the_application(qtbot, translator):
    """
    Логотип берётся из resources, а те кладутся в сборку целиком.

    Забытый файл виден только глазами на собранном приложении: QPixmap на
    отсутствующем пути молча отдаёт пустую картинку.
    """
    from efd_unpacker.runtime import resource_path

    assert os.path.isfile(resource_path("resources", screens.LOGO))

    screen = screens.AboutScreen(translator, "2.0.0")
    qtbot.addWidget(screen)
    logos = [label for label in screen.findChildren(QLabel) if label.pixmap() is not None]
    assert logos, "логотип не отрисован"
    assert logos[0].pixmap().height() == screens.LOGO_HEIGHT * screens._ratio()


def test_system_line_names_the_system_not_the_kernel(monkeypatch):
    """
    На macOS platform.release() отдаёт версию Darwin, и «macOS 25.5.0» не
    значит ничего: пользователь знает свою систему как «macOS 15».
    """
    monkeypatch.setattr(screens.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(screens.platform, "release", lambda: "25.5.0")
    monkeypatch.setattr(screens.platform, "mac_ver", lambda: ("15.5", ("", "", ""), "arm64"))
    monkeypatch.setattr(screens.platform, "machine", lambda: "arm64")

    assert screens.system_line() == "macOS 15.5 · arm64"


@pytest.mark.parametrize(
    "system, release, expected",
    [("Windows", "11", "Windows 11 · x86_64"), ("Linux", "6.8.0-generic", "Linux · x86_64")],
    ids=["windows", "linux"],
)
def test_system_line_on_other_systems(monkeypatch, system, release, expected):
    """Номер ядра в этой строке не к месту: программы ищутся в PATH."""
    monkeypatch.setattr(screens.platform, "system", lambda: system)
    monkeypatch.setattr(screens.platform, "release", lambda: release)
    monkeypatch.setattr(screens.platform, "machine", lambda: "x86_64")

    assert screens.system_line() == expected


# --- рисование знаков --------------------------------------------------------


def ink(glyph):
    """Цвета, которыми знак действительно закрасил свои пиксели."""
    from PyQt5.QtGui import QColor, QImage, QPainter

    image = QImage(style.MARK_SIZE, style.MARK_SIZE, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    glyph.render(painter)
    painter.end()
    return {
        QColor(image.pixel(x, y)).name().upper()
        for x in range(image.width())
        for y in range(image.height())
        if QColor(image.pixelColor(x, y)).alpha() > 200
    }


@pytest.mark.parametrize(
    "kind, color",
    [
        (screens.Glyph.CHECK, style.ACCENT),
        (screens.Glyph.DASH, style.DISABLED),
        (screens.Glyph.INFO, style.MUTED),
    ],
    ids=["галочка", "прочерк", "кружок"],
)
def test_glyph_actually_puts_ink_on_the_widget(qtbot, kind, color):
    """
    Знак рисуется, а не набирается символом шрифта — и рисовать он обязан.

    Пустой paintEvent виден только глазами: виджет своего размера, место в
    разметке занимает, и ни один тест состава строк этого не замечает.
    """
    glyph = screens.Glyph(kind, color)
    qtbot.addWidget(glyph)

    assert color.upper() in ink(glyph)


def test_glyphs_differ_from_one_another(qtbot):
    """Три знака — три разных рисунка, а не один и тот же под тремя именами."""
    from PyQt5.QtGui import QImage, QPainter

    def shape(kind):
        image = QImage(style.MARK_SIZE, style.MARK_SIZE, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        glyph = screens.Glyph(kind, style.INK)
        qtbot.addWidget(glyph)
        glyph.render(painter)
        painter.end()
        return bytes(image.constBits().asstring(image.byteCount()))

    drawings = {shape(kind) for kind in (screens.Glyph.CHECK, screens.Glyph.DASH, screens.Glyph.INFO)}
    assert len(drawings) == 3


def test_about_columns_do_not_collapse(qtbot, translator):
    """
    Абзац с переносом сообщает разметке ширину по самому длинному слову.

    Через вложенные ряды это доходило как «колонка в одно слово»: текст на
    тёмной полосе вставал столбиком в полтора сантиметра, а сама полоса
    вырастала на пол-экрана. Видно только глазами, поэтому проверяем числа.
    """
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QFrame

    screen = screens.AboutScreen(translator, "2.0.0")
    qtbot.addWidget(screen)
    screen.setStyleSheet(style.window_sheet() + screen.styleSheet())
    # Разметка считается по-настоящему только у показанного окна, а плагин
    # minimal на настоящем окне падает. WA_DontShowOnScreen даёт ровно то, что
    # нужно: геометрия настоящая, окна на экране нет.
    screen.setAttribute(Qt.WA_DontShowOnScreen, True)
    screen.resize(style.WINDOW_WIDTH, style.WINDOW_HEIGHT)
    screen.show()

    band = screen.findChild(QFrame, "brand")
    texts_on_band = [
        label for label in band.findChildren(QLabel)
        if label.text().startswith("Ingvar Consulting helps")
    ]
    assert texts_on_band, "текста на полосе нет"
    assert texts_on_band[0].width() > band.width() // 2, "текст ужат в столбик"
    assert band.height() < style.WINDOW_HEIGHT // 2, "полоса заняла пол-экрана"

    about = [
        label for label in screen.findChildren(QLabel)
        if label.text().startswith("Unpacking of 1C:Enterprise")
    ]
    assert about, "описания программы нет"
    # Ровно ширина из макета: от неё зависит, где переносится описание.
    assert about[0].width() == screens.ABOUT_COLUMN_WIDTH


def test_rebuilding_does_not_pile_up_button_groups(qtbot, translator, settings):
    """
    Группа переключателей живёт на экране, а не в его теле.

    Вместе с пересобранным телом она не уходит, и каждая смена каталога
    оставляла бы на экране ещё одну пустую группу — за сеанс их набирается
    столько, сколько раз человек передумал.
    """
    from PyQt5.QtWidgets import QButtonGroup

    screen = screens.PathsScreen(translator, settings)
    qtbot.addWidget(screen)
    after_first = len(screen.findChildren(QButtonGroup))

    for _ in range(5):
        screen.refresh()
    qtbot.wait(1)

    assert len(screen.findChildren(QButtonGroup)) == after_first


@pytest.mark.parametrize(
    "draw", [screens.menu_icon, screens.back_icon], ids=["шестерёнка", "назад"]
)
def test_button_icons_are_drawn_not_typed(qtbot, draw):
    """
    «⚙», «▾» и «‹» — символы шрифта: начертание у гарнитур разное, а на
    системе без подходящего шрифта на месте кнопки остаётся пустой
    прямоугольник. Значит, рисунок обязан быть непустым.
    """
    from PyQt5.QtGui import QColor

    icon = draw(style.INK)
    sizes = icon.availableSizes()
    assert sizes, "значок пуст"

    image = icon.pixmap(sizes[0]).toImage()

    def painted(left, right):
        return {
            QColor(image.pixelColor(x, y)).name().upper()
            for x in range(left, right)
            for y in range(image.height())
            if QColor(image.pixelColor(x, y)).alpha() > 200
        }

    half = image.width() // 2
    assert style.INK.upper() in painted(0, image.width())
    if draw is screens.menu_icon:
        # Шеврон рисуется в долях высоты, а ширина картинки — тоже: иначе он
        # обрезался бы у любого размера, кроме того единственного, под который
        # ширину подобрали.
        assert style.INK.upper() in painted(half, image.width()), "шеврон обрезан"
