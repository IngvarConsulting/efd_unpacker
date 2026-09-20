"""
Экраны меню шестерёнки: куда распаковывать, инструменты для .rar, о программе.

Экран, а не диалог. В макетах это целое окно со стрелкой «назад» в шапке, и
причина не в красоте: диалог поверх списка прячет то, ради чего в него зашли,
а выбор каталога виден в подвале и в каждой строке списка сразу за возвратом.

Ничего не выдумывают. Пути берутся из SettingsService вместе с происхождением
каждого, программы — из rar.discover() на этой машине, лицензии — из
requirements. Экран, показывающий правдоподобное вместо настоящего, хуже
отсутствующего: по нему принимают решения.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
from typing import Callable, List, Optional, Sequence, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..constants import UIConstants
from ..infrastructure import rar
from ..infrastructure.os_utils import get_distributions_location_default
from ..infrastructure.settings_service import ORIGIN_KEYS, SettingsService
from ..runtime import resource_path
from . import style

#: Роли каталогов, те же, что в окне: подпись про место идёт по ним.
ROLE_TEMPLATES = "templates"
ROLE_DISTRIBUTIONS = "distributions"

#: Ссылки экрана «О программе». Все три ведут в один репозиторий, потому что
#: обратная связь у проекта одна — его трекер.
HOME_URL = "https://github.com/IngvarConsulting/efd_unpacker"
ISSUE_URL = "https://github.com/IngvarConsulting/efd_unpacker/issues/new"
RELEASES_URL = "https://github.com/IngvarConsulting/efd_unpacker/releases"
LICENSES_URL = "https://github.com/IngvarConsulting/efd_unpacker/blob/main/docs/LICENSES.md"
COMPANY_URL = "https://ingvar.pro"

#: Что из чего собрано. Список сверяется с requirements.txt тестом: зависимость
#: добавят, а сюда дописать забудут — и экран начнёт умалчивать о лицензии.
LICENSES = (
    ("EFD Unpacker", "MIT"),
    ("PyQt5", "GPL v3"),
    ("onec_dtools", "MIT"),
)

#: Логотип партнёра. Нарисован белым по тёмному, поэтому и лежит на тёмной
#: полосе, а не на белом фоне окна.
LOGO = "ingvar-consulting.png"
#: Во сколько раз значок меню шире своей высоты: шестерёнка плюс шеврон.
#: Доля, а не пиксели: шеврон рисуется в долях size, и постоянная добавка
#: обрезала бы его у любого размера, кроме одного.
MENU_ICON_ASPECT = 1.8

LOGO_WIDTH = 186
LOGO_HEIGHT = 33

#: Ширина левой колонки «О программе», из макета.
ABOUT_COLUMN_WIDTH = 400


# --- мелкие знаки ------------------------------------------------------------


class Glyph(QWidget):
    """
    Значок 16×16 слева от строки: галочка, прочерк или кружок с «i».

    Рисуется, а не набирается символом шрифта, по той же причине, что и знак
    состояния в строке списка: начертание «✓» и «—» у гарнитур разное, а
    выглядеть одинаково на трёх системах они обязаны.
    """

    CHECK = "check"
    DASH = "dash"
    INFO = "info"

    def __init__(self, kind: str, color: str) -> None:
        super().__init__()
        self._kind = kind
        self._color = color
        self.setFixedSize(style.MARK_SIZE, style.MARK_SIZE)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self._color)
        middle = style.MARK_SIZE / 2.0

        if self._kind == Glyph.CHECK:
            path = QPainterPath()
            scale = style.MARK_SIZE / 24.0
            path.moveTo(5 * scale, 13 * scale)
            path.lineTo(9 * scale, 17 * scale)
            path.lineTo(19 * scale, 7 * scale)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color, 2.6 * scale, cap=Qt.RoundCap, join=Qt.RoundJoin))
            painter.drawPath(path)
        elif self._kind == Glyph.DASH:
            painter.setPen(QPen(color, 2.4, cap=Qt.RoundCap))
            painter.drawLine(3, int(middle), style.MARK_SIZE - 3, int(middle))
        else:
            box = QRectF(1.0, 1.0, style.MARK_SIZE - 2.0, style.MARK_SIZE - 2.0)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color, 1.3))
            painter.drawEllipse(box)
            painter.setPen(QPen(color, 1.6, cap=Qt.RoundCap))
            painter.drawLine(int(middle), 7, int(middle), 12)
            painter.drawPoint(int(middle), 4)


def menu_icon(color: str, size: int = 15) -> QIcon:
    """
    Шестерёнка с шевроном для кнопки меню.

    Рисуется по той же причине, что и знак состояния строки: «⚙» и «▾» —
    символы шрифта, начертание у гарнитур разное, а на системе без
    подходящего шрифта на месте кнопки остаётся пустой прямоугольник.

    Возвращается QIcon, а не виджет: кнопке нужна именно картинка.
    """
    ratio = _ratio()
    pixmap = QPixmap(int(size * MENU_ICON_ASPECT * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)

    middle = QPointF(size / 2.0, size / 2.0)
    gear = QPainterPath()
    gear.addEllipse(middle, size * 0.36, size * 0.36)
    for index in range(8):
        tooth = QPainterPath()
        tooth.addRoundedRect(
            QRectF(-size * 0.08, -size * 0.50, size * 0.16, size * 0.24),
            size * 0.04, size * 0.04,
        )
        turn = QTransform().translate(middle.x(), middle.y()).rotate(index * 45)
        gear = gear.united(turn.map(tooth))
    hole = QPainterPath()
    hole.addEllipse(middle, size * 0.155, size * 0.155)

    chevron = QPainterPath()
    chevron.moveTo(size + size * 0.23, size * 0.42)
    chevron.lineTo(size + size * 0.47, size * 0.62)
    chevron.lineTo(size + size * 0.71, size * 0.42)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    # Силуэт с вырезанной серединой, а не кольцо со спицами: на пятнадцати
    # пикселях спицы читаются солнцем, а не шестерёнкой.
    painter.fillPath(gear.subtracted(hole), QColor(color))
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(color), size * 0.12, cap=Qt.RoundCap, join=Qt.RoundJoin))
    painter.drawPath(chevron)
    painter.end()
    return QIcon(pixmap)


def back_icon(color: str, size: int = 16) -> QIcon:
    """Стрелка «назад». Рисуется по той же причине, что и шестерёнка."""
    ratio = _ratio()
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)

    path = QPainterPath()
    path.moveTo(size * 0.62, size * 0.25)
    path.lineTo(size * 0.37, size * 0.50)
    path.lineTo(size * 0.62, size * 0.75)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(color), 1.8, cap=Qt.RoundCap, join=Qt.RoundJoin))
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def _note(text: str, kind: str = Glyph.INFO) -> QWidget:
    """Пояснение со значком: значок сверху, текст в несколько строк рядом."""
    label = QLabel(text)
    label.setProperty("role", "note")
    label.setWordWrap(True)

    box = QHBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(10)
    box.addWidget(Glyph(kind, style.MUTED), 0, Qt.AlignTop)
    box.addWidget(label, 1)

    holder = QWidget()
    holder.setLayout(box)
    return holder


def _section(text: str) -> QLabel:
    """Заголовок раздела: прописные с разрядкой, как в макетах."""
    label = QLabel(text.upper())
    label.setProperty("role", "section")
    font = label.font()
    font.setLetterSpacing(font.PercentageSpacing, style.SECTION_SPACING)
    label.setFont(font)
    return label


def _paragraph(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "note")
    label.setWordWrap(True)
    return label


def _rule() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background: %s;" % style.LINE_FAINT)
    return line


# --- общий каркас ------------------------------------------------------------


class Screen(QWidget):
    """Шапка со стрелкой «назад», тело и нижняя полоса."""

    closed = pyqtSignal()

    def __init__(self, translator, title: str) -> None:
        super().__init__()
        self.translator = translator

        self.button_back = QPushButton()
        self.button_back.setIcon(back_icon(style.MUTED))
        self.button_back.setAccessibleName(self._t("Screens", "Back"))
        self.button_back.setToolTip(self._t("Screens", "Back"))
        self.button_back.setCursor(Qt.PointingHandCursor)
        self.button_back.setFixedWidth(22)
        self.button_back.setStyleSheet(
            "QPushButton { border: 0; background: transparent; }"
        )
        self.button_back.clicked.connect(self.closed.emit)

        self.label_title = QLabel(title)
        self.label_title.setProperty("role", "screen-title")
        self.label_trailing = QLabel("")
        self.label_trailing.setProperty("role", "mono")

        bar = QHBoxLayout()
        bar.setContentsMargins(style.SIDE_PADDING - 6, 0, style.SIDE_PADDING, 0)
        bar.setSpacing(6)
        bar.addWidget(self.button_back)
        bar.addWidget(self.label_title)
        bar.addStretch()
        bar.addWidget(self.label_trailing)

        header = QFrame()
        header.setObjectName("screenHeader")
        header.setFixedHeight(style.HEADER_HEIGHT)
        header.setLayout(bar)
        header.setStyleSheet(style.band_sheet("screenHeader", bottom=style.LINE))

        self.body = QVBoxLayout()
        self.body.setContentsMargins(style.SIDE_PADDING, 15, style.SIDE_PADDING, 12)
        self.body.setSpacing(0)
        content = QWidget()
        content.setLayout(self.body)
        self.scroll = QScrollArea()
        self.scroll.setWidget(content)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.foot = QHBoxLayout()
        self.foot.setContentsMargins(style.SIDE_PADDING, 13, style.SIDE_PADDING, 13)
        self.foot.setSpacing(16)
        self.footer = QFrame()
        self.footer.setObjectName("screenFooter")
        self.footer.setLayout(self.foot)
        self.footer.setStyleSheet(style.band_sheet("screenFooter", top=style.LINE))

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.footer)
        self.setLayout(layout)

    def _t(self, context: str, text: str) -> str:
        return self.translator.translate(context, text)

    def _open_url(self, url: str) -> None:
        """
        Открывает ссылку системным браузером и не проглатывает отказ.

        openUrl возвращает ложь, когда обработчика нет вовсе — на голой Linux
        без xdg-utils это обычное дело. Промолчать значит оставить человека с
        кнопкой, которая ничего не делает и не объясняет почему; адрес в
        сообщении для того, чтобы его можно было скопировать руками.
        """
        if QDesktopServices.openUrl(QUrl(url)):
            return
        QMessageBox.warning(
            self, self._t("Screens", "Error"),
            "%s\n\n%s" % (self._t("Screens", "Could not open the link"), url),
        )

    def _clear_body(self) -> None:
        """Опустошает тело экрана перед пересборкой."""
        while self.body.count():
            entry = self.body.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


# --- куда распаковывать ------------------------------------------------------


def free_bytes(path: str) -> Optional[int]:
    """
    Свободное место на томе пути, даже если самого пути ещё нет.

    Каталог создаётся только перед распаковкой, поэтому спрашивать про него
    напрямую нельзя: disk_usage отвечает отказом, и подвал остался бы пустым
    ровно в тот момент, когда место интереснее всего. Поднимаемся до
    существующего предка — том у них один.
    """
    probe = os.path.normpath(path) if path else os.sep
    while True:
        try:
            return shutil.disk_usage(probe).free
        except OSError:
            parent = os.path.dirname(probe)
            if parent == probe:
                return None
            probe = parent


def volume_of(path: str) -> Optional[int]:
    """
    Устройство, на котором лежит путь, — как и free_bytes, по ближайшему
    существующему предку. None, если не удалось спросить ни у кого.
    """
    probe = os.path.normpath(path) if path else os.sep
    while True:
        try:
            return os.stat(probe).st_dev
        except OSError:
            parent = os.path.dirname(probe)
            if parent == probe:
                return None
            probe = parent


class PathsScreen(Screen):
    """Каталог шаблонов и каталог дистрибутивов."""

    changed = pyqtSignal()

    def __init__(self, translator, settings_service: SettingsService) -> None:
        super().__init__(translator, translator.translate("Screens", "Where to unpack"))
        self.settings_service = settings_service
        self._needed = {ROLE_TEMPLATES: 0, ROLE_DISTRIBUTIONS: 0}
        self._groups: List[QButtonGroup] = []

        self.setStyleSheet(style.radio_sheet())

        self.label_space = QLabel("")
        self.label_space.setProperty("role", "mono")
        button_done = QPushButton(self._t("Screens", "Done"))
        button_done.setStyleSheet(style.primary_button_sheet())
        button_done.setCursor(Qt.PointingHandCursor)
        button_done.clicked.connect(self.closed.emit)
        self.foot.addWidget(self.label_space)
        self.foot.addStretch()
        self.foot.addWidget(button_done)

        self.refresh()

    def set_needed(self, templates: int, distributions: int = 0) -> None:
        """
        Объём отмеченного, раздельно по каталогам.

        Раздельно, потому что каталоги бывают на разных томах: одна цифра на
        оба означала бы «свободно» с того тома, куда поедет меньшая часть, —
        и пачка дистрибутивов на полный диск выглядела бы благополучно.
        """
        self._needed = {ROLE_TEMPLATES: templates, ROLE_DISTRIBUTIONS: distributions}
        self._refresh_space()

    def refresh(self) -> None:
        self._clear_body()
        # Прежние группы удаляются явно. QButtonGroup — не виджет, и вместе с
        # телом экрана он не уходит: живёт он на самом экране, и каждая
        # пересборка оставляла бы на нём ещё одну пустую группу.
        for group in self._groups:
            group.deleteLater()
        self._groups = []

        templates = self.settings_service.get_output_path()
        self.body.addWidget(_section(self._t("Screens", "Configuration templates")))
        self.body.addSpacing(5)
        self.body.addWidget(_paragraph(
            self._t(
                "Screens",
                "The folder is dictated by 1C. Inside it the application creates "
                "1c/<product>/<version> — that is what the supply standard requires.",
            )
        ))
        self.body.addSpacing(5)
        self._add_group(
            "templates",
            [(choice.path, self._origin_text(choice.origin)) for choice
             in self.settings_service.get_output_path_items()],
            selected=templates,
            on_pick=self._pick_templates,
            on_browse=self._browse_templates,
        )

        self.body.addSpacing(13)
        self.body.addWidget(_rule())
        self.body.addSpacing(13)
        self.body.addWidget(_section(self._t("Screens", "Platform and DBMS distributions")))
        self.body.addSpacing(5)
        self.body.addWidget(_paragraph(
            self._t(
                "Screens",
                "Here 1C dictates nothing. By default it sits next to the templates, "
                "in a neighbouring folder: change the templates folder and this one follows.",
            )
        ))
        self.body.addSpacing(5)
        computed = get_distributions_location_default(templates)
        options = [(computed, self._t("Screens", "next to the templates"))]
        if self.settings_service.distributions_path_is_explicit():
            options.append((
                self.settings_service.get_distributions_path(),
                self._t("Screens", "chosen manually"),
            ))
        self._add_group(
            "distributions",
            options,
            selected=self.settings_service.get_distributions_path(),
            on_pick=self._pick_distributions,
            on_browse=self._browse_distributions,
        )
        self.body.addStretch()
        self._refresh_space()

    # --- построение списка вариантов -----------------------------------------

    def _add_group(
        self,
        section: str,
        options: Sequence[Tuple[str, str]],
        selected: str,
        on_pick: Callable[[str], None],
        on_browse: Callable[[], None],
    ) -> None:
        group = QButtonGroup(self)
        self._groups.append(group)
        for index, (path, origin) in enumerate(options):
            button = QRadioButton(path)
            # Имя — адрес переключателя для тестов и средств доступности:
            # подписи это пути, и они у обоих разделов складываются похоже.
            button.setObjectName("%s-%d" % (section, index))
            button.setChecked(_same_path(path, selected))
            button.clicked.connect(lambda _checked, value=path: on_pick(value))
            group.addButton(button)

            label = QLabel(origin)
            label.setProperty("role", "muted")

            row = QHBoxLayout()
            row.setContentsMargins(0, 6, 0, 6)
            row.setSpacing(12)
            row.addWidget(button, 1)
            row.addWidget(label)
            holder = QWidget()
            holder.setLayout(row)
            self.body.addWidget(holder)

        browse = QRadioButton(self._t("Screens", "Choose another folder…"))
        browse.setObjectName("%s-browse" % section)
        browse.setProperty("role", "action")
        browse.setCursor(Qt.PointingHandCursor)
        # Выбор папки начинается с нажатия, а отметка на этом переключателе
        # не значит ничего: сразу после диалога список пересобирается, и
        # отмеченным оказывается выбранный путь, а не эта строка.
        browse.clicked.connect(lambda _checked: on_browse())
        group.addButton(browse)
        self.body.addSpacing(6)
        self.body.addWidget(browse)
        self.body.addSpacing(6)

    def _origin_text(self, origin: str) -> str:
        key = ORIGIN_KEYS.get(origin)
        return self.translator.translate("SettingsService", key) if key else ""

    # --- выбор ---------------------------------------------------------------

    def _pick_templates(self, path: str) -> None:
        if _same_path(path, self.settings_service.get_output_path()):
            return
        self.settings_service.set_output_path(path)
        self._announce()

    def _pick_distributions(self, path: str) -> None:
        templates = self.settings_service.get_output_path()
        if _same_path(path, get_distributions_location_default(templates)):
            # Возврат к вычисляемому, а не запись того же значения: иначе от
            # своего выбора нельзя было бы отказаться — только сменить его на
            # такой же, и дистрибутивы перестали бы ходить за шаблонами.
            self.settings_service.set_distributions_path("")
        else:
            self.settings_service.set_distributions_path(path)
        self._announce()

    def _browse_templates(self) -> None:
        directory = self._ask(
            self._t("Screens", "Select the templates folder"),
            self.settings_service.get_output_path(),
        )
        if directory:
            self.settings_service.set_output_path(directory)
        self._announce()

    def _browse_distributions(self) -> None:
        directory = self._ask(
            self._t("Screens", "Select the distributions folder"),
            self.settings_service.get_distributions_path(),
        )
        if directory:
            self.settings_service.set_distributions_path(directory)
        self._announce()

    def _ask(self, title: str, start: str) -> str:
        return QFileDialog.getExistingDirectory(self, title, start)

    def _announce(self) -> None:
        """Пересобирает список вариантов и сообщает окну о смене каталога."""
        self.refresh()
        self.changed.emit()

    # --- место на диске -------------------------------------------------------

    def _volumes(self) -> List[Tuple[str, int, Optional[int]]]:
        """
        Тома назначения: путь, нужно на него, свободно на нём.

        Один том, когда каталоги соседи (обычный случай), и два, когда их
        развели по разным дискам. Считается по устройству, а не по виду пути:
        соседние каталоги с непохожими именами всё равно лежат на одном томе.
        """
        roots = [
            (ROLE_TEMPLATES, self.settings_service.get_output_path()),
            (ROLE_DISTRIBUTIONS, self.settings_service.get_distributions_path()),
        ]
        volumes: List[Tuple[str, int, Optional[int]]] = []
        by_device: dict = {}
        for role, path in roots:
            device = volume_of(path)
            if device is not None and device in by_device:
                index = by_device[device]
                known, needed, free = volumes[index]
                volumes[index] = (known, needed + self._needed[role], free)
                continue
            by_device[device] = len(volumes)
            volumes.append((path, self._needed[role], free_bytes(path)))
        return volumes

    def _refresh_space(self) -> None:
        # Тома считаются один раз: каждый вызов ходит на диск.
        volumes = self._volumes()
        split = len(volumes) > 1
        parts = []
        tight = False
        for path, needed, free in volumes:
            if free is None:
                continue
            if split and not needed:
                # На этот том ничего не поедет: место на нём сейчас не новость.
                continue
            room = "%s %s" % (self._t("Screens", "free"), style.human_size(free))
            if split:
                room = "%s: %s" % (os.path.basename(os.path.normpath(path)) or path, room)
            parts.append(room)
            if needed:
                parts.append("%s %s" % (self._t("Screens", "needed"), style.human_size(needed)))
            tight = tight or needed > free
        self.label_space.setText("  ·  ".join(parts))
        # Не влезает — это единственное, что стоит сказать про место заранее:
        # отказ на середине распаковки обходится дороже, чем предупреждение.
        self.label_space.setStyleSheet(
            "font-family: %s; font-size: 11.5px; color: %s;"
            % (style.mono_stack(), style.ALERT if tight else style.MUTED)
        )


def _same_path(left: str, right: str) -> bool:
    return bool(left) and bool(right) and os.path.normpath(left) == os.path.normpath(right)


# --- инструменты для .rar ----------------------------------------------------


def system_line() -> str:
    """
    Система и разрядность в шапке: то, от чего зависит и поиск, и команда.

    Ядро на Linux в этой строке не к месту: программы ищутся по имени в PATH,
    а не по версии ядра, и его номер только съел бы место. На macOS берём
    именно версию системы — platform.release() там отдаёт версию Darwin, и
    «macOS 25.5.0» не значит ничего.
    """
    machine = platform.machine()
    system = platform.system()
    if system == "Darwin":
        return "macOS %s · %s" % (platform.mac_ver()[0], machine)
    if system == "Windows":
        return "Windows %s · %s" % (platform.release(), machine)
    return "%s · %s" % (system or "?", machine)


#: Номер версии в ответе программы. Первая группа — после слова libarchive,
#: если оно есть: bsdtar печатает сразу две версии, свою и библиотеки, а
#: формат читает именно библиотека.
_VERSION = re.compile(r"(libarchive\s+)?(\d+(?:\.\d+)+)", re.IGNORECASE)


def short_version(tool) -> str:
    """
    Версия одной строкой: «libarchive 3.7.4», «7-Zip 23.01».

    Целиком ответ показывать нельзя: bsdtar отвечает строкой в семьдесят с
    лишним знаков, где после нужного номера идут версии zlib, liblzma и
    bz2lib. В окне шириной 760 она вытесняет собой путь к программе — то
    единственное, ради чего эту строку и читают.
    """
    title = rar.FAMILY_TITLES.get(tool.family, tool.family)
    preferred = None
    for anchor, number in _VERSION.findall(tool.version or ""):
        if anchor:
            return "%s %s" % (title, number)
        preferred = preferred or number
    return "%s %s" % (title, preferred) if preferred else ""


class ToolsScreen(Screen):
    """Что нашлось для .rar на этой машине."""

    def __init__(self, translator, discover=None, start_search=None) -> None:
        super().__init__(translator, translator.translate("Screens", "Unpacking tools"))
        self._discover = discover or rar.discover
        # Поиск уходит в поток: он запускает каждого кандидата за версией, а
        # предел ожидания такого запуска — двадцать секунд. Зависшая программа
        # подвесила бы окно ровно на столько же.
        self._start_search = start_search or self._search_in_thread
        self._thread = None
        self._tools: Tuple = ()
        self._searching = False
        self._copy_buttons: List[QPushButton] = []

        self.label_trailing.setText(system_line())

        self.label_hint = QLabel(self._t(
            "Screens", "Without such a program .rar files are simply skipped"
        ))
        self.label_hint.setProperty("role", "note")
        self.button_rescan = QPushButton(self._t("Screens", "Search again"))
        self.button_rescan.setStyleSheet(style.secondary_button_sheet())
        self.button_rescan.setCursor(Qt.PointingHandCursor)
        self.button_rescan.clicked.connect(self.rescan)
        self.foot.addWidget(self.label_hint, 1)
        self.foot.addWidget(self.button_rescan)

        self.search()

    # --- поиск ----------------------------------------------------------------

    def search(self) -> None:
        """Запускает поиск и показывает, что он идёт."""
        if self._searching:
            return
        self._searching = True
        self.button_rescan.setEnabled(False)
        self._render()
        self._start_search()

    def rescan(self) -> None:
        """Кнопка «Искать заново»: забываем всё, что знали, и ищем снова."""
        rar.forget()
        self.search()

    def refresh(self) -> None:
        """
        Перерисовывает экран по тому, что уже известно.

        Зовётся при каждом заходе: запись о проверке появляется, когда
        распаковали .rar, а строки собираются один раз при первом показе.
        Без этого проверка, случившаяся после, так и осталась бы невидимой —
        а «Искать заново» вместо неё не годится, она сначала всё забывает.
        """
        if not self._searching:
            self._render()

    def _search_in_thread(self) -> None:
        from .threads import ToolsThread  # noqa: PLC0415 - модуль тянет QThread

        thread = ToolsThread(self._discover)
        thread.ready.connect(self.show_tools)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._forget_thread)
        self._thread = thread
        thread.start()

    def _forget_thread(self) -> None:
        self._thread = None

    def wait(self) -> None:
        """
        Дожидается потока поиска, в крайнем случае снимая его.

        Предел ожидания обязан кончаться снятием, а не просто истекать:
        зависший кандидат держит поиск до своих двадцати секунд, а закрытие
        окна после этого разрушило бы живой QThread — то есть уронило бы
        приложение на выходе. Поиск ничего не пишет, снимать его безопасно.
        """
        thread = self._thread
        if thread is None or not thread.isRunning():
            return
        if not thread.wait(UIConstants.THREAD_STOP_TIMEOUT_MS):
            thread.terminate()
            thread.wait()

    def show_tools(self, tools) -> None:
        self._tools = tuple(tools)
        self._searching = False
        self.button_rescan.setEnabled(True)
        self._render()

    # --- показ ----------------------------------------------------------------

    def _render(self) -> None:
        self._clear_body()
        self.body.addWidget(_paragraph(self._t(
            "Screens",
            "Archives in .rar are unpacked by an external program. The application "
            "neither installs it nor ships it — it only finds it and calls it.",
        )))
        self.body.addSpacing(14)

        if self._searching:
            self.body.addWidget(_paragraph(self._t("Screens", "Searching…")))
            self.body.addStretch()
            return

        # Кто в деле, решает запись о проверке, а не порядок поиска: первая
        # программа могла не справиться именно с этим архивом, и дальше по
        # списку нашлась другая — ради этого запасные и перечисляются.
        probe = rar.last_probe()
        used = probe.tool.path if probe is not None else None

        missing = False
        for family in rar.known_families():
            found = [tool for tool in self._tools if tool.family == family]
            self.body.addWidget(_rule())
            if found:
                for tool in found:
                    self.body.addWidget(self._found_row(
                        tool, used=used, first=self._tools[0] is tool,
                    ))
            else:
                missing = True
                self.body.addWidget(self._missing_row(family))
        self.body.addWidget(_rule())

        if missing:
            self.body.addSpacing(12)
            self.body.addWidget(self._install_block())
        self.body.addSpacing(14)
        self.body.addWidget(_note(self._t(
            "Screens",
            "Fitness is checked on the archive itself, not by version number: "
            "libarchive builds ship with different format sets, and the list of "
            "supported ones can lie.",
        )))
        self.body.addStretch()

    def _found_row(self, tool, used: Optional[str], first: bool) -> QWidget:
        title = QLabel(rar.FAMILY_TITLES.get(tool.family, tool.family))
        title.setStyleSheet("font-size: 13.5px; font-weight: 600;")

        # «Используется» — только про ту, что действительно прочитала архив.
        # Пока ни одного .rar не читали, использовать некого, и первая по
        # очереди — это обещание, а не факт: так и называем.
        if used is not None and tool.path == used:
            mark, accented = self._t("Screens", "IN USE"), True
        elif used is None and first:
            mark, accented = self._t("Screens", "first in line"), True
        else:
            mark, accented = self._t("Screens", "spare"), False
        badge = QLabel(mark)
        badge.setStyleSheet(
            "font-size: 11px; font-weight: 500; color: %s;"
            % (style.ACCENT if accented else style.MUTED)
        )

        version = short_version(tool)
        lines = [tool.path if not version else "%s  ·  %s" % (tool.path, version)]
        note = ""
        probe = rar.last_probe()
        if probe is not None and probe.tool.path == tool.path:
            note = self._t("Screens", "checked on %s: %d entries") % (
                probe.archive, probe.entries,
            )
        return self._row(Glyph.CHECK, style.ACCENT, title, badge, lines, note)

    def _missing_row(self, family: str) -> QWidget:
        title = QLabel(rar.FAMILY_TITLES.get(family, family))
        title.setStyleSheet("font-size: 13.5px; font-weight: 600; color: %s;" % style.MUTED)
        badge = QLabel(self._t("Screens", "not found"))
        badge.setStyleSheet("font-size: 11px; color: %s;" % style.MUTED)
        names = ", ".join(rar.searched_names(family))
        return self._row(
            Glyph.DASH, style.DISABLED, title, badge,
            [self._t("Screens", "searched as %s") % names] if names else [],
        )

    def _row(self, kind: str, glyph_color: str, title, badge, lines, note: str = "") -> QWidget:
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(title, 1)
        top.addWidget(badge)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(3)
        body.addLayout(top)
        for text in lines:
            label = QLabel(text)
            label.setStyleSheet(
                "font-family: %s; font-size: 11px; color: %s;" % (style.mono_stack(), style.MUTED)
            )
            body.addWidget(label)
        if note:
            # Не моноширинным: это фраза, а не путь и не номер версии.
            result = QLabel(note)
            result.setStyleSheet("font-size: 11.5px; color: %s;" % style.MUTED)
            body.addWidget(result)

        outer = QHBoxLayout()
        outer.setContentsMargins(0, 11, 0, 11)
        outer.setSpacing(11)
        outer.addWidget(Glyph(kind, glyph_color), 0, Qt.AlignTop)
        outer.addLayout(body, 1)
        holder = QWidget()
        holder.setLayout(outer)
        return holder

    def _install_block(self) -> QWidget:
        """
        Команды установки — по одной в строке, каждая со своей кнопкой.

        Не одной строкой: варианты равноправны, нужен ровно один из них, и
        «a | b», вставленное в оболочку, становится конвейером — вторая
        команда запустится даже после успеха первой, а её отказ человек
        примет за отказ установки.

        По семействам программ они при этом не разложены: подсказка в rar
        даётся на систему целиком, и раскладывать её обратно значило бы
        сочинять имена пакетов — у Debian и Fedora они разные, и проверить их
        мне не на чем.
        """
        self._copy_buttons = []
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        for command in rar.install_hints():
            label = QLabel(command)
            label.setStyleSheet(style.code_sheet())
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)

            button = QPushButton(self._t("Screens", "Copy"))
            button.setStyleSheet(style.small_button_sheet())
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked, text=command: self.copy_command(text))
            self._copy_buttons.append(button)

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addWidget(label)
            row.addWidget(button)
            row.addStretch()
            holder = QWidget()
            holder.setLayout(row)
            box.addWidget(holder)

        block = QWidget()
        block.setLayout(box)
        return block

    def copy_command(self, command: str) -> None:
        """
        Кладёт одну команду в буфер. Установку не запускаем.

        winget и brew просят повышения прав и задают свои вопросы, а человек
        вправе знать, что ставится в его систему, до того как это произойдёт.
        """
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(command)
        for button in self._copy_buttons:
            button.setText(
                self._t("Screens", "Copied") if button is self.sender()
                else self._t("Screens", "Copy")
            )
        QTimer.singleShot(1500, self._restore_copy)

    def _restore_copy(self) -> None:
        for button in self._copy_buttons:
            # Кнопки могли уехать вместе с пересборкой тела, пока шёл отсчёт.
            try:
                button.setText(self._t("Screens", "Copy"))
            except RuntimeError:
                pass


# --- о программе -------------------------------------------------------------


class AboutScreen(Screen):
    """Версия, ссылки, лицензии и полоса партнёра."""

    def __init__(self, translator, version: str) -> None:
        super().__init__(translator, translator.translate("Screens", "About"))
        self.version = version
        # Нижняя полоса — часть экрана, а не подвал: в макете у неё поля со
        # всех сторон и скруглённые углы, а подвал идёт от края до края.
        self.footer.hide()

        left = QWidget()
        left.setLayout(self._about_column())
        # Ширина из макета, а не по содержимому: в макете колонки 400 и
        # остаток, и от ширины зависит, где переносится описание.
        left.setFixedWidth(ABOUT_COLUMN_WIDTH)
        right = QWidget()
        right.setLayout(self._licenses_column())

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(26)
        columns.addWidget(left, 0, Qt.AlignTop)
        columns.addWidget(right, 1, Qt.AlignTop)
        holder = QWidget()
        holder.setLayout(columns)

        self.body.addWidget(holder)
        self.body.addSpacing(16)
        self.body.addWidget(self._brand())
        self.body.addStretch()

    def _about_column(self) -> QVBoxLayout:
        name = QLabel("EFD Unpacker")
        name.setStyleSheet("font-size: 18px; font-weight: 600;")
        version = QLabel(self.version)
        version.setStyleSheet(
            "font-family: %s; font-size: 14px; color: %s;" % (style.mono_stack(), style.MUTED)
        )
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(9)
        heading.addWidget(name)
        heading.addWidget(version)
        heading.addStretch()

        system = QLabel(system_line())
        system.setProperty("role", "mono")

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addLayout(heading)
        column.addSpacing(3)
        column.addWidget(system)
        column.addSpacing(10)
        column.addWidget(_paragraph(self._t(
            "Screens",
            "Unpacking of 1C:Enterprise supply files and laying out platform "
            "distributions into folders.",
        )))
        column.addSpacing(14)
        for text, url in (
            (self._t("Screens", "Source code on GitHub"), HOME_URL),
            (self._t("Screens", "Report a problem"), ISSUE_URL),
            (self._t("Screens", "Check for updates"), RELEASES_URL),
        ):
            column.addWidget(self._link(text, url))
            column.addSpacing(7)
        column.addStretch()
        return column

    def _licenses_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(_section(self._t("Screens", "Licenses")))
        column.addSpacing(9)
        for name, license_name in LICENSES:
            label = QLabel(name)
            label.setProperty("role", "path")
            value = QLabel(license_name)
            value.setProperty("role", "muted")
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(label, 1)
            row.addWidget(value)
            holder = QWidget()
            holder.setLayout(row)
            column.addWidget(holder)
            column.addSpacing(6)
        column.addSpacing(3)
        column.addWidget(self._link(self._t("Screens", "Full texts"), LICENSES_URL))
        column.addSpacing(12)
        column.addWidget(_paragraph(self._t(
            "Screens",
            "Programs for .rar are not part of the package — the application "
            "calls the ones installed in the system.",
        )))
        column.addStretch()
        return column

    def _link(self, text: str, url: str) -> QPushButton:
        button = QPushButton(text)
        button.setStyleSheet(style.link_sheet())
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(url)
        button.clicked.connect(lambda: self._open_url(url))
        # Кнопка растягивается на всю ширину колонки, и щелчок по пустому месту
        # справа от короткой подписи открывал бы ссылку. Держим по содержимому.
        button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        return button

    def _brand(self) -> QWidget:
        logo = QLabel()
        ratio = _ratio()
        pixmap = QPixmap(resource_path("resources", LOGO))
        if not pixmap.isNull():
            scaled = pixmap.scaledToHeight(LOGO_HEIGHT * ratio, Qt.SmoothTransformation)
            # Плотность ставится ДО setPixmap: label хранит копию, и правка
            # того, что вернёт pixmap(), до самой картинки уже не доходит.
            scaled.setDevicePixelRatio(ratio)
            logo.setPixmap(scaled)
        else:  # pragma: no cover - в поставке файл есть, проверка на запуск из src
            logo.setText("Ingvar Consulting")
        logo.setFixedWidth(LOGO_WIDTH)

        text = QLabel(self._t(
            "Screens",
            "Ingvar Consulting helps 1C teams sort out development processes: "
            "planning, releases, reviews, onboarding, and makes the team more manageable.",
        ))
        text.setWordWrap(True)
        text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text.setStyleSheet("font-size: 12.5px; color: %s;" % style.BRAND_TEXT)

        link = QPushButton("ingvar.pro  →")
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip(COMPANY_URL)
        link.setStyleSheet(
            "QPushButton { border: 0; background: transparent; color: %s;"
            " font-size: 12.5px; font-weight: 600; padding: 0; text-align: left; }"
            % style.BRAND_LINK
        )
        link.clicked.connect(lambda: self._open_url(COMPANY_URL))
        link.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        # Сетка с явной растяжкой колонки — вместе с политикой размера у
        # абзаца выше. У абзаца с переносом высота зависит от ширины, а
        # собственная ширина заявлена по самому длинному слову; через два
        # вложенных ряда до разметки доходило именно это — текст вставал
        # колонкой в одно слово, а полоса вырастала на пол-экрана.
        # Достаточно любого из двух, но оба говорят одно и то же вслух.
        grid = QGridLayout()
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(9)
        grid.addWidget(logo, 0, 0, 2, 1, Qt.AlignTop)
        grid.addWidget(text, 0, 1)
        grid.addWidget(link, 1, 1, Qt.AlignLeft)
        grid.setColumnStretch(1, 1)

        band = QFrame()
        band.setObjectName("brand")
        band.setLayout(grid)
        band.setStyleSheet(style.brand_sheet())
        return band


def _ratio() -> int:
    """
    Множитель для логотипа на экране с удвоенной плотностью.

    Картинка растровая: без множителя она на Retina мылится, а с ним берётся
    вдвое большей и уменьшается обратно уже самим экраном.
    """
    app = QApplication.instance()
    return 2 if app is not None and app.devicePixelRatio() > 1 else 1
