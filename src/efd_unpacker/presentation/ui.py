"""
Окно массовой распаковки.

Собрано по макетам: шапка с названием и версией, список из двух ярусов,
подвал с каталогом 1С, нижняя полоса с единственной опцией и главной кнопкой,
в которой видно количество и объём.

Строка списка — это шаблон, а не файл. Иначе список врёт: demo.zip несёт два
шаблона разных продуктов, а server64_*.zip в каталог шаблонов не попадёт
вовсе. План из #51 уже так устроен, окно его показывает.

Окно не тупиковое: после распаковки список остаётся, и можно бросить ещё
файлы, не перезапуская приложение.
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..application.executor import Writers
from ..application.inspector import inspect_all
from ..application.messages import format_validation_error
from ..constants import UIConstants
from ..domain.batch import run as run_batch
from ..domain.errors import FileValidationError, UnpackError
from ..domain.file_validator import FileValidator
from ..domain.manifest import read as read_manifest
from ..domain.plan import (
    Action,
    ItemKind,
    Plan,
    PlanSettings,
    PlannedItem,
    SkipReason,
    build_plan,
    keeps_configuration,
)
from ..domain.unpack_service import UnpackService
from ..infrastructure import rar
from ..infrastructure.os_utils import open_folder
from ..infrastructure.settings_service import SettingsService
from ..localization.translator import Translator
from . import rows, screens, style
from .threads import BatchThread, PlanThread, describe_failure

APP_VERSION = "2.0.0"

#: Высота значка шестерёнки, из макета.
GEAR_HEIGHT = 15

ROLE_TEMPLATES = "templates"
ROLE_DISTRIBUTIONS = "distributions"

REASON_KEYS = {
    SkipReason.ALREADY_INSTALLED: "already installed",
    SkipReason.FILTERED_OUT: "excluded by filter",
    SkipReason.CONTAINER_UNSUPPORTED: "format is not supported",
    SkipReason.RAR_TOOL_MISSING: "no program for .rar",
    SkipReason.NOTHING_FOUND: "nothing found inside",
    SkipReason.NO_TEMPLATES: "no templates inside",
}


class MainWindow(QMainWindow):
    """Окно списка и распаковки."""

    def __init__(
        self,
        translator: Translator,
        settings_service: SettingsService,
        file_validator: FileValidator,
        unpack_service: UnpackService,
        inspect_files=inspect_all,
        build=build_plan,
        batch=run_batch,
        make_writers=Writers,
        read_manifest=read_manifest,
    ) -> None:
        super().__init__()
        self.translator = translator
        self.settings_service = settings_service
        self.file_validator = file_validator
        self.unpack_service = unpack_service
        # Осмотр, построение плана и исполнение внедряются: окно проверяется
        # без диска и без ожидания настоящей распаковки.
        self._inspect_files = inspect_files
        self._build = build
        self._batch = batch
        self._make_writers = make_writers
        self._read_manifest = read_manifest

        self._inspected: List = []
        self._plan = Plan()
        self.rows: List[rows.PlanRow] = []
        self._row_of: Dict[int, rows.PlanRow] = {}
        self._unchecked: set = set()
        self._plan_thread: Optional[PlanThread] = None
        self._batch_thread: Optional[BatchThread] = None
        self._templates_root = ""
        self._written_kinds: set = set()
        # Экраны настроек создаются при первом заходе: поиск программ для .rar
        # и чтение вариантов каталога ни к чему тому, кто в меню не заходил.
        self._paths = None
        self._tools = None
        self._about = None
        self._started_at = 0.0
        self._written_bytes = 0
        self._current_bytes = 0
        self._total_bytes = 0

        self._build_ui()
        self._refresh()

    # --- построение окна -----------------------------------------------------

    def _t(self, context: str, text: str) -> str:
        return self.translator.translate(context, text)

    def _build_ui(self) -> None:
        self.setWindowTitle(self._t("MainWindow", "EFD Unpacker"))
        self.resize(style.WINDOW_WIDTH, style.WINDOW_HEIGHT)
        self.setMinimumSize(640, 460)
        self.setAcceptDrops(True)
        self.setStyleSheet(style.window_sheet())

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._make_header())
        layout.addWidget(self._make_progress())
        layout.addWidget(self._make_summary())
        layout.addWidget(self._make_body(), 1)
        layout.addWidget(self._make_footer())
        layout.addWidget(self._make_actions())

        main_page = QWidget()
        main_page.setLayout(layout)

        # Экраны настроек занимают окно целиком, а не встают диалогом поверх:
        # диалог прячет ровно тот список, ради которого в настройки и зашли.
        self.pages = QStackedWidget()
        self.pages.addWidget(main_page)
        self.setCentralWidget(self.pages)

    def _make_header(self) -> QWidget:
        self.label_status = QLabel("")
        self.label_status.setProperty("role", "mono")

        self.button_menu = QPushButton()
        self.button_menu.setAccessibleName(self._t("MainWindow", "Settings"))
        self.button_menu.setToolTip(self._t("MainWindow", "Settings"))
        self.button_menu.setIconSize(
            QSize(int(GEAR_HEIGHT * screens.MENU_ICON_ASPECT), GEAR_HEIGHT)
        )
        self.button_menu.setCursor(Qt.PointingHandCursor)
        self.button_menu.clicked.connect(self._show_menu)
        self._set_gear(False)

        title = QLabel(self._t("MainWindow", "EFD Unpacker"))
        title.setProperty("role", "title")
        version = QLabel(APP_VERSION)
        version.setProperty("role", "mono")

        bar = QHBoxLayout()
        bar.setContentsMargins(style.SIDE_PADDING, 0, style.SIDE_PADDING, 0)
        bar.setSpacing(8)
        bar.addWidget(title)
        bar.addWidget(version)
        bar.addStretch()
        bar.addWidget(self.label_status)
        bar.addWidget(self.button_menu)

        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(style.HEADER_HEIGHT)
        header.setLayout(bar)
        header.setStyleSheet(style.band_sheet("header", bottom=style.LINE))
        return header

    def _make_progress(self) -> QWidget:
        self.progress_total = QProgressBar()
        self.progress_total.setTextVisible(False)
        self.progress_total.setFixedHeight(style.PROGRESS_HEIGHT)
        self.progress_total.setStyleSheet(
            "QProgressBar { border: 0; background: %s; }"
            "QProgressBar::chunk { background: %s; }" % (style.LINE_SOFT, style.ACCENT)
        )
        self.progress_total.hide()
        return self.progress_total

    def _make_summary(self) -> QWidget:
        self.label_counts = QLabel("")
        self.label_counts.setProperty("role", "mono")
        self.button_clear_marks = QPushButton(self._t("MainWindow", "Clear all marks"))
        self.button_clear_marks.setStyleSheet(style.link_sheet())
        self.button_clear_marks.setCursor(Qt.PointingHandCursor)
        self.button_clear_marks.clicked.connect(self._clear_marks)

        bar = QHBoxLayout()
        bar.setContentsMargins(style.SIDE_PADDING, 11, style.SIDE_PADDING, 11)
        bar.addWidget(self.label_counts)
        bar.addStretch()
        bar.addWidget(self.button_clear_marks)

        self.summary = QFrame()
        self.summary.setObjectName("summary")
        self.summary.setLayout(bar)
        self.summary.setStyleSheet(style.band_sheet("summary", bottom=style.LINE_SOFT))
        self.summary.hide()
        return self.summary

    def _make_body(self) -> QWidget:
        self.drop_zone = self._make_drop_zone()

        self.rows_box = QVBoxLayout()
        self.rows_box.setContentsMargins(style.SIDE_PADDING, 0, style.SIDE_PADDING, 0)
        self.rows_box.setSpacing(0)
        self.rows_box.addStretch()
        holder = QWidget()
        holder.setLayout(self.rows_box)

        self.scroll = QScrollArea()
        self.scroll.setWidget(holder)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.body = QStackedWidget()
        self.body.addWidget(self.drop_zone)
        self.body.addWidget(self.scroll)
        return self.body

    def _make_drop_zone(self) -> QWidget:
        self.label_drop = QLabel(self._t("MainWindow", "Drag files here"))
        self.label_drop.setAlignment(Qt.AlignCenter)
        self.label_drop.setStyleSheet("font-size: 16px; font-weight: 600;")
        hint = QLabel(".efd  ·  .zip  ·  .tar.gz  ·  .tar.bz2  ·  .rar  ·  .dmg")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            "font-family: %s; font-size: 12px; color: %s;" % (style.mono_stack(), style.MUTED)
        )
        choose = QPushButton(self._t("MainWindow", "Select files"))
        choose.setStyleSheet(style.secondary_button_sheet())
        choose.setCursor(Qt.PointingHandCursor)
        choose.clicked.connect(self.open_file_dialog)

        inner = QVBoxLayout()
        inner.setContentsMargins(32, 40, 32, 40)
        inner.setSpacing(14)
        inner.addWidget(self.label_drop)
        inner.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(choose)
        row.addStretch()
        inner.addLayout(row)

        self.zone = QFrame()
        self.zone.setObjectName("zone")
        self.zone.setLayout(inner)
        self.zone.setStyleSheet(style.drop_zone_sheet())
        self.zone.setMaximumWidth(440)

        outer = QHBoxLayout()
        outer.addStretch()
        outer.addWidget(self.zone)
        outer.addStretch()
        wrapper = QVBoxLayout()
        wrapper.addStretch()
        wrapper.addLayout(outer)
        wrapper.addStretch()
        holder = QWidget()
        holder.setLayout(wrapper)
        return holder

    def _make_footer(self) -> QWidget:
        self.label_root_caption = QLabel(self._t("MainWindow", "1C folder"))
        self.label_root_caption.setProperty("role", "muted")
        self.label_root = QLabel("")
        self.label_root.setProperty("role", "path")
        self.button_paths = QPushButton(self._t("MainWindow", "Change"))
        self.button_paths.setStyleSheet(style.link_sheet())
        self.button_paths.setCursor(Qt.PointingHandCursor)
        self.button_paths.clicked.connect(self.show_paths)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(self.label_root_caption)
        top.addWidget(self.label_root)
        top.addStretch()
        top.addWidget(self.button_paths)

        self.label_inside = QLabel("")
        self.label_inside.setProperty("role", "muted")

        box = QVBoxLayout()
        box.setContentsMargins(style.SIDE_PADDING, 12, style.SIDE_PADDING, 14)
        box.setSpacing(6)
        box.addLayout(top)
        box.addWidget(self.label_inside)

        self.footer = QFrame()
        self.footer.setObjectName("footer")
        self.footer.setLayout(box)
        self.footer.setStyleSheet(style.band_sheet("footer", top=style.LINE))
        return self.footer

    def _make_actions(self) -> QWidget:
        self.check_only_cf = QCheckBox(self._t("MainWindow", "Without demo databases"))
        self.check_only_cf.stateChanged.connect(self._rebuild_plan)

        self.button_clear = QPushButton(self._t("MainWindow", "Clear list"))
        self.button_clear.setStyleSheet(style.secondary_button_sheet())
        self.button_clear.clicked.connect(self._clear_list)
        self.button_clear.hide()

        self.button_stop = QPushButton(self._t("MainWindow", "Stop"))
        self.button_stop.setStyleSheet(style.secondary_button_sheet())
        self.button_stop.clicked.connect(self.cancel)
        self.button_stop.hide()

        self.button_unpack = QPushButton(self._t("MainWindow", "Unpack"))
        self.button_unpack.setStyleSheet(style.primary_button_sheet())
        self.button_unpack.setCursor(Qt.PointingHandCursor)
        self.button_unpack.clicked.connect(self.unpack)
        self.button_unpack.setEnabled(False)

        bar = QHBoxLayout()
        bar.setContentsMargins(style.SIDE_PADDING, 13, style.SIDE_PADDING, 13)
        bar.setSpacing(12)
        bar.addWidget(self.check_only_cf)
        bar.addStretch()
        bar.addWidget(self.button_clear)
        bar.addWidget(self.button_stop)
        bar.addWidget(self.button_unpack)

        actions = QFrame()
        actions.setObjectName("actions")
        actions.setLayout(bar)
        actions.setStyleSheet(style.band_sheet("actions", top=style.LINE_FAINT))
        return actions

    # --- меню ----------------------------------------------------------------

    def menu(self) -> QMenu:
        """
        Меню шестерёнки: три экрана, как в макетах.

        Сборка отделена от показа: exec_ не возвращает управление, пока меню
        не закроют, и проверить состав пунктов на живом меню было бы нечем.
        """
        menu = QMenu(self)
        menu.setStyleSheet(style.menu_sheet())

        paths = menu.addAction(self._t("MainWindow", "Where to unpack…"), self.show_paths)
        # Посреди распаковки менять каталог нельзя: писатели уже получили
        # корень, и смена настройки развела бы обещанное в окне и то, что
        # на самом деле пишется на диск.
        paths.setEnabled(not self._unpacking())
        menu.addAction(self._tools_title(), self.show_tools)
        menu.addSeparator()
        menu.addAction(self._t("MainWindow", "About"), self.show_about)
        return menu

    def _show_menu(self) -> None:
        menu = self.menu()
        self._set_gear(True)
        try:
            menu.exec_(self.button_menu.mapToGlobal(self.button_menu.rect().bottomLeft()))
        finally:
            # Возврат вида в finally: меню закрывается и по Esc, и щелчком
            # мимо, и оставленная подсвеченной шестерёнка обещала бы открытое
            # меню, которого нет.
            self._set_gear(False)

    def _set_gear(self, open_: bool) -> None:
        """Шестерёнка: с открытым меню — в акценте, как в макете."""
        self.button_menu.setStyleSheet(style.gear_sheet(open_))
        self.button_menu.setIcon(
            screens.menu_icon(style.ACCENT if open_ else style.INK, GEAR_HEIGHT)
        )

    def _tools_title(self) -> str:
        """
        Пункт про .rar с количеством найденного, если оно уже известно.

        Цифра берётся из кеша, а не новым поиском: меню открывается в потоке
        окна, а поиск запускает каждого кандидата за номером версии.
        """
        title = self._t("MainWindow", "Tools for .rar")
        tools = rar.found()
        return title if tools is None else "%s  %d" % (title, len(tools))

    # --- экраны настроек ------------------------------------------------------

    def show_paths(self) -> None:
        if self._paths is None:
            self._paths = screens.PathsScreen(self.translator, self.settings_service)
            self._paths.changed.connect(self._paths_changed)
            self._paths.closed.connect(self.close_screen)
            self.pages.addWidget(self._paths)
        self._paths.refresh()
        selected = self._selected()
        self._paths.set_needed(
            templates=sum(
                item.bytes_total for item in selected if item.kind is ItemKind.SUPPLY
            ),
            distributions=sum(
                item.bytes_total for item in selected if item.kind is not ItemKind.SUPPLY
            ),
        )
        self.pages.setCurrentWidget(self._paths)

    def show_tools(self) -> None:
        if self._tools is None:
            self._tools = screens.ToolsScreen(self.translator)
            self._tools.closed.connect(self.close_screen)
            self.pages.addWidget(self._tools)
        # Перерисовка на каждом заходе: между заходами могли распаковать .rar,
        # и запись о проверке иначе так и не показалась бы.
        self._tools.refresh()
        self.pages.setCurrentWidget(self._tools)

    def show_about(self) -> None:
        if self._about is None:
            self._about = screens.AboutScreen(self.translator, APP_VERSION)
            self._about.closed.connect(self.close_screen)
            self.pages.addWidget(self._about)
        self.pages.setCurrentWidget(self._about)

    def close_screen(self) -> None:
        """Возврат к списку."""
        self.pages.setCurrentIndex(0)

    def _paths_changed(self) -> None:
        """
        Смена каталога видна сразу: строки называют новый путь, подвал тоже.

        Пересборка, а не одна подпись: нижний ярус каждой строки показывает
        путь относительно корня, и без неё список говорил бы про старый
        каталог, пока окно не перезапустят.
        """
        self._rebuild_plan()

    # --- приём файлов --------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        # Расширение больше не проверяется: на вход годятся zip, dmg, rar и
        # голый .efd, а вид определяется содержимым при осмотре.
        if self._dropped_paths(event):
            event.acceptProposedAction()
            self._set_drag_active(True)

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drag_active(False)
        paths = self._dropped_paths(event)
        if paths:
            self.set_input_files(paths)

    @staticmethod
    def _dropped_paths(event) -> List[str]:
        mime = event.mimeData()
        if not mime or not hasattr(mime, "urls"):
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def _set_drag_active(self, active: bool) -> None:
        self.zone.setStyleSheet(style.drop_zone_sheet(active))
        self.label_drop.setText(
            self._t("MainWindow", "Drop files to inspect") if active
            else self._t("MainWindow", "Drag files here")
        )

    def open_file_dialog(self, _event=None) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._t("MainWindow", "Select files"), "",
            self._t(
                "MainWindow",
                "Supply and distribution files (*.efd *.zip *.rar *.dmg *.tar *.gz *.bz2 *.xz)",
            ),
        )
        if paths:
            self.set_input_files(paths)

    def set_input_file(self, file_path: str) -> bool:
        """Один файл. Оставлен для файловых ассоциаций и аргумента запуска."""
        return self.set_input_files([file_path])

    def set_input_files(self, paths: Sequence[str]) -> bool:
        """Осматривает файлы в фоне и показывает список."""
        if not paths or self._running(self._plan_thread) or self._unpacking():
            return False

        self.label_status.setText(self._t("MainWindow", "Inspecting…"))
        self.button_unpack.setEnabled(False)
        thread = PlanThread(paths, self._inspect_files)
        thread.ready.connect(self._inspection_ready)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._forget_plan_thread)
        self._plan_thread = thread
        thread.start()
        return True

    def _inspection_ready(self, inspected, error: Optional[UnpackError]) -> None:
        self._set_drag_active(False)
        self.label_status.setText("")
        if error is not None:
            QMessageBox.warning(
                self, self._t("MainWindow", "Error"),
                describe_failure(self.translator, error),
            )
            # Кнопка была погашена на время осмотра. Не вернуть её значит
            # оставить пользователя с живым списком, который нельзя запустить.
            self._rebuild_plan()
            return
        # Добавляем к уже осмотренному: окно не тупиковое, и второй набор
        # файлов дополняет список, а не стирает его.
        self._inspected = list(self._inspected) + list(inspected)
        self._rebuild_plan()

    def _forget_plan_thread(self) -> None:
        self._plan_thread = None

    # --- план ----------------------------------------------------------------

    def _settings(self) -> PlanSettings:
        return PlanSettings(
            templates_root=self.settings_service.get_output_path(),
            distributions_root=self.settings_service.get_distributions_path(),
            only_configuration=self.check_only_cf.isChecked(),
            is_installed=os.path.isdir,
        )

    def _rebuild_plan(self) -> None:
        """
        Пересобирает план из уже осмотренного.

        Осмотр стоит секунд, построение плана — микросекунд, поэтому
        переключение «без демобаз» не трогает диск.
        """
        self._plan = self._build(self._inspected, self._settings())
        self._fill_rows()
        self._refresh()

    def _fill_rows(self) -> None:
        for row in self.rows:
            self.rows_box.removeWidget(row)
            row.deleteLater()
        self.rows = []
        self._row_of = {}

        for index, item in enumerate(self._plan.items):
            row = rows.PlanRow(
                title=item.title,
                detail=self._detail(item),
                trailing=self._trailing(item),
                state=self._initial_state(item),
            )
            row.toggled.connect(self._refresh)
            if item.reason is SkipReason.RAR_TOOL_MISSING:
                # Экран инструментов достижим и по месту, а не только из меню:
                # строка сообщает, что программы нет, и здесь же говорит, где
                # про неё прочитать.
                row.offer_open(self._t("MainWindow", "Tools…"))
                row.open_requested.connect(self.show_tools)
            else:
                row.open_requested.connect(lambda item=item: self._open_item(item))
            self.rows_box.insertWidget(index, row)
            self.rows.append(row)
            self._row_of[id(item)] = row

        self.body.setCurrentIndex(1 if self.rows else 0)
        self.summary.setVisible(bool(self.rows))

    def _mark_key(self, item: PlannedItem) -> Tuple:
        """
        Ключ снятой отметки, различающий одинаковые строки.

        Один файл, брошенный дважды, даёт два совпадающих по полям элемента.
        Ключа по полям мало: снятая отметка у второго переезжала на первый при
        пересборке плана, и снятыми оказывались обе строки.

        Номер вхождения считается в порядке плана — том же, в каком строки
        стоят на экране.
        """
        key = _key(item)
        occurrence = 0
        for other in self._plan.items:
            if other is item:
                break
            if _key(other) == key:
                occurrence += 1
        return (key, occurrence)

    def _initial_state(self, item: PlannedItem) -> str:
        if item.action is Action.FAIL:
            return rows.FAILED
        if item.action is Action.SKIP:
            return rows.UNAVAILABLE
        return rows.UNCHECKED if self._mark_key(item) in self._unchecked else rows.PENDING

    def _detail(self, item: PlannedItem) -> str:
        """Нижний ярус: куда поедет или почему не поедет."""
        if item.action is Action.FAIL:
            return describe_failure(self.translator, item.failure)
        if item.action is Action.SKIP:
            key = REASON_KEYS.get(item.reason) if item.reason else None
            return self._t("Report", key) if key else ""

        role, root = (
            (ROLE_TEMPLATES, self.settings_service.get_output_path())
            if item.kind is ItemKind.SUPPLY
            else (ROLE_DISTRIBUTIONS, self.settings_service.get_distributions_path())
        )
        return "%s · %s" % (self._t("MainWindow", role), _relative_to(item.destination, root))

    def _trailing(self, item: PlannedItem) -> str:
        return style.human_size(item.bytes_total) if item.bytes_total else ""

    def _selected(self) -> List[PlannedItem]:
        return [
            item for item in self._plan.items
            if self._row_of.get(id(item)) is not None and self._row_of[id(item)].selected()
        ]

    def _clear_marks(self) -> None:
        for item in self._plan.items:
            row = self._row_of.get(id(item))
            if row is not None and row.state() == rows.PENDING:
                row.set_state(rows.UNCHECKED)
                self._unchecked.add(self._mark_key(item))
        self._refresh()

    def _clear_list(self) -> None:
        self._inspected = []
        self._unchecked = set()
        self._written_kinds = set()
        self._rebuild_plan()

    # --- показ ---------------------------------------------------------------

    def _refresh(self) -> None:
        """Пересчитывает подписи, которые зависят от выбора."""
        self._remember_marks()
        selected = self._selected()
        volume = sum(item.bytes_total for item in selected)
        self.button_unpack.setText(
            "%s %d · %s" % (self._t("MainWindow", "Unpack"), len(selected), style.human_size(volume))
            if selected else self._t("MainWindow", "Unpack")
        )
        self.button_unpack.setEnabled(bool(selected) and not self._unpacking())
        self.button_clear_marks.setVisible(bool(selected))
        self.label_counts.setText(self._counts_text())
        self.check_only_cf.setText(self._option_text())
        self._refresh_footer()

    def _remember_marks(self) -> None:
        """Снятые отметки переживают пересборку плана: выбор делал человек."""
        for item in self._plan.items:
            row = self._row_of.get(id(item))
            if row is None:
                continue
            if row.state() == rows.UNCHECKED:
                self._unchecked.add(self._mark_key(item))
            elif row.state() == rows.PENDING:
                self._unchecked.discard(self._mark_key(item))

    def _counts_text(self) -> str:
        kinds = {kind: 0 for kind in ItemKind}
        skipped = failed = 0
        for item in self._plan.items:
            if item.action is Action.FAIL:
                failed += 1
            elif item.action is Action.SKIP:
                skipped += 1
            else:
                kinds[item.kind] += 1
        parts = [
            ("files:", len(self._inspected)),
            ("templates:", kinds[ItemKind.SUPPLY]),
            ("distributions:", kinds[ItemKind.PLATFORM] + kinds[ItemKind.PACKAGES]),
            ("other:", kinds[ItemKind.CONTENT] + kinds[ItemKind.OTHER]),
            ("skipped:", skipped),
            ("errors:", failed),
        ]
        return "  ·  ".join(
            "%s %d" % (self._t("Report", key), value) for key, value in parts if value
        )

    def _option_text(self) -> str:
        saved = _demo_bytes(self._plan)
        if not saved:
            return self._t("MainWindow", "Without demo databases")
        return "%s — %s" % (
            self._t("MainWindow", "Without demo databases"),
            self._t("MainWindow", "saves %s") % style.human_size(saved),
        )

    def _refresh_footer(self) -> None:
        templates = self.settings_service.get_output_path()
        distributions = self.settings_service.get_distributions_path()
        shared = os.path.dirname(os.path.normpath(templates)) or templates
        if not _inside(distributions, shared):
            # Каталоги развели вручную — общего корня нет, показываем оба.
            self.label_root.setText(templates)
            self.label_inside.setText(distributions)
            return
        self.label_root.setText(shared)
        self.label_inside.setText(
            "%s %s %s, %s %s" % (
                self._t("MainWindow", "inside it"),
                os.path.basename(templates.rstrip("/\\")),
                self._t("MainWindow", "for templates"),
                os.path.basename(distributions.rstrip("/\\")),
                self._t("MainWindow", "for distributions"),
            )
        )

    # --- распаковка ----------------------------------------------------------

    @staticmethod
    def _running(thread) -> bool:
        return thread is not None and thread.isRunning()

    def _unpacking(self) -> bool:
        """
        Идёт ли распаковка. Только она и мешает начать новую.

        Поток осмотра сюда не входит намеренно: сигнал о готовности приходит
        из run(), а QThread до выхода из него ещё числится живым. Считая его
        занятостью, окно блокировало кнопку ровно в тот момент, когда список
        уже показан, — и разблокировать её было некому.
        """
        return self._running(self._batch_thread)

    def unpack(self) -> None:
        selected = self._selected()
        if self._unpacking() or not selected:
            return

        needs_templates = any(item.kind is ItemKind.SUPPLY for item in selected)
        needs_distributions = any(item.kind is not ItemKind.SUPPLY for item in selected)
        try:
            # Готовим только те каталоги, в которые действительно поедет:
            # иначе каталог шаблонов создавался даже для пачки из одних
            # дистрибутивов — пустым и не к месту.
            templates_root = (
                self.file_validator.prepare_output_directory(
                    self.settings_service.get_output_path()
                )
                if needs_templates
                else self.settings_service.get_output_path()
            )
            if needs_distributions:
                self.file_validator.prepare_output_directory(
                    self.settings_service.get_distributions_path()
                )
        except FileValidationError as exc:
            QMessageBox.warning(
                self, self._t("MainWindow", "Error"),
                format_validation_error(self.translator, exc),
            )
            return

        self._templates_root = templates_root
        self._started_at = time.monotonic()
        self._written_bytes = 0
        self._current_bytes = 0

        # Поток создаётся до писателей: им нужен его флаг отмены. Без него
        # «Остановить» действовала только на границе между элементами, и пачка
        # из одного архива дописывалась целиком после нажатия.
        thread = BatchThread(Plan(items=tuple(selected)), None, self._batch)
        thread.set_writers(self._make_writers(
            self.unpack_service, templates_root, self.check_only_cf.isChecked(),
            thread.cancelled, thread.report_bytes,
        ))
        thread.item_progress.connect(self._item_started)
        thread.item_bytes.connect(self._item_bytes)
        thread.item_finished.connect(self._item_finished)
        thread.completed.connect(self._batch_finished)
        # Настоящий QThread.finished, а не наш completed: он приходит после
        # фактического выхода из run(), когда объект уже можно удалять.
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._forget_batch_thread)
        self._batch_thread = thread

        self._total_bytes = sum(item.bytes_total for item in selected)
        self.progress_total.setMaximum(style.PROGRESS_STEPS)
        self.progress_total.setValue(0)
        self.progress_total.show()
        # Гасим, а не только прячем: скрытая кнопка остаётся «доступной», и
        # проверка состояния по isEnabled показывала бы неправду.
        self.button_unpack.setEnabled(False)
        self.button_unpack.hide()
        self.button_clear.hide()
        self.button_stop.show()
        self.button_stop.setEnabled(True)
        self.button_paths.setEnabled(False)
        self.check_only_cf.setEnabled(False)
        self.button_clear_marks.setEnabled(False)
        thread.start()

    def cancel(self) -> None:
        thread = self._batch_thread
        if thread is not None and thread.isRunning():
            thread.cancel()
            self.button_stop.setEnabled(False)

    def _item_started(self, item: PlannedItem) -> None:
        row = self._row_of.get(id(item))
        if row is not None:
            row.set_state(rows.RUNNING)
            row.set_progress(0, item.bytes_total)
        self._update_status(item)

    def _item_bytes(self, item: PlannedItem, done: int, name: str) -> None:
        row = self._row_of.get(id(item))
        if row is not None:
            row.set_progress(done, item.bytes_total)
            row.set_detail(name)
            row.set_trailing("%s / %s" % (style.human_size(done), style.human_size(item.bytes_total)))
        # Недописанный элемент считается тоже: пачка из одного архива на
        # полтора гигабайта иначе не показала бы остаток времени ни разу —
        # до самого конца, когда он уже не нужен.
        self._current_bytes = done
        self._update_status(item)

    def _item_finished(self, item: PlannedItem, error: Optional[UnpackError]) -> None:
        row = self._row_of.get(id(item))
        if row is not None:
            row.set_state(rows.FAILED if error is not None else rows.DONE)
            row.set_detail(
                describe_failure(self.translator, error) if error is not None
                else self._detail(item)
            )
            row.set_trailing(self._trailing(item))
            if error is None:
                row.offer_open(self._t("MainWindow", "Open Folder"))
                self._show_manifest(row, item)
        if error is None:
            self._written_bytes += item.bytes_total
        self._current_bytes = 0
        self._update_status(item)

    def _show_manifest(self, row: rows.PlanRow, item: PlannedItem) -> None:
        """
        «В 1С появится…» — строка Catalog из распакованного 1cv8.mft.

        Украшение, а не условие успеха: манифеста нет, он битый или в нём нет
        ни одной конфигурации — строка просто остаётся прежней, с путём.
        Распаковка к этому моменту уже состоялась.

        Показываются только те конфигурации, чей файл лёг на диск: с
        «без демобаз» демонстрационная база не пишется вовсе, и обещать её в
        1С значило бы соврать там, где человек пойдёт её искать.
        """
        if item.kind is not ItemKind.SUPPLY:
            return
        delivered = self._read_manifest(item.destination).delivered(item.destination)
        if delivered:
            row.set_appears(
                self._t("MainWindow", "In 1C it will appear as:"),
                [config.title for config in delivered],
            )

    def _update_status(self, _item: PlannedItem) -> None:
        """Полоса и остаток времени. Оба считаются от байтов, а не наоборот."""
        total = self._total_bytes
        done = self._written_bytes + self._current_bytes
        self.progress_total.setValue(style.progress_value(done, total))
        elapsed = max(time.monotonic() - self._started_at, 0.001)
        if done <= 0 or done >= total:
            self.label_status.setText("")
            return
        remaining = (total - done) * elapsed / done
        self.label_status.setText(
            "%s · %s %s" % (
                style.human_size(done),
                self._t("MainWindow", "about"),
                _minutes(self.translator, remaining),
            )
        )

    def _batch_finished(self, result) -> None:
        self.button_paths.setEnabled(True)
        self.check_only_cf.setEnabled(True)
        self.button_clear_marks.setEnabled(True)
        self.button_stop.hide()
        self.button_unpack.show()
        self.button_clear.setVisible(True)
        self.progress_total.hide()

        self._written_kinds = {item.kind for item in result.written}
        if any(item.kind is ItemKind.SUPPLY for item in result.written):
            # Сохраняем только когда в каталог шаблонов действительно писали.
            self.settings_service.set_output_path(self._templates_root)

        elapsed = time.monotonic() - self._started_at
        if result.written and not result.cancelled:
            self.label_status.setText(
                "%s %s %s" % (
                    style.human_size(sum(i.bytes_total for i in result.written)),
                    self._t("MainWindow", "in"),
                    _minutes(self.translator, elapsed),
                )
            )
        elif result.cancelled:
            self.label_status.setText(self._t("MainWindow", "stopped"))
        else:
            # Ничего не записано и не отменяли — значит всё отказало. Остаток
            # времени от последнего элемента здесь врёт: работы больше нет.
            self.label_status.setText("")
        self._refresh()

    def _forget_batch_thread(self) -> None:
        self._batch_thread = None

    # --- пути и папка --------------------------------------------------------

    def _open_item(self, item: PlannedItem) -> None:
        self._open(item.destination)

    def open_output_folder(self) -> None:
        self._open(self._written_root())

    def _written_root(self) -> str:
        """
        Каталог, который действительно получил файлы.

        Поставки едут в каталог шаблонов, всё прочее — в каталог
        дистрибутивов. Открывать первый после пачки из одних дистрибутивов
        значит показать пользователю пустую папку.
        """
        if ItemKind.SUPPLY in self._written_kinds:
            return self._templates_root or self.settings_service.get_output_path()
        if self._written_kinds:
            return self.settings_service.get_distributions_path()
        return self.settings_service.get_output_path()

    def _open(self, root: str) -> None:
        if not root or open_folder(root):
            return
        # QMessageBox, а не строка состояния: та прятала саму кнопку «Открыть
        # папку». Путь в тексте — чтобы его можно было скопировать.
        QMessageBox.warning(
            self, self._t("MainWindow", "Error"),
            "%s\n\n%s" % (self._t("MainWindow", "Could not open the folder"), root),
        )

    # --- закрытие ------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """
        Не даёт закрыть окно молча посреди распаковки.

        Раньше окно закрывалось сразу, поток продолжал писать в уже
        разрушаемом приложении, и пользователь получал каталог шаблона,
        в котором часть файлов отсутствует.
        """
        thread = self._batch_thread
        if thread is None or not thread.isRunning():
            # Осмотр не спрашивает: он ничего не пишет и быстро кончается.
            # Но дождаться его обязательно — QThread, разрушенный на ходу,
            # роняет приложение при выходе. То же и с поиском программ.
            self._stop(self._plan_thread)
            self._stop_tools()
            event.accept()
            return

        answer = QMessageBox.question(
            self,
            self._t("MainWindow", "Unpacking in progress"),
            self._t("MainWindow", "Unpacking is not finished. Stop it and close the window?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            event.ignore()
            return

        thread.cancel()
        self._stop(thread)
        self._stop(self._plan_thread)
        self._stop_tools()
        event.accept()

    def _stop_tools(self) -> None:
        """Дожидается поиска программ, если экран инструментов его начал."""
        if self._tools is not None:
            self._tools.wait()

    @staticmethod
    def _stop(thread) -> None:
        """
        Дожидается потока, в крайнем случае снимая его.

        Уже записанные файлы при этом целы — каждый ставится на место через
        os.replace, — а незавершённый остаётся временным .part. Снятие потока
        осмотра может оставить смонтированный образ, но альтернатива —
        разрушенный на ходу QThread и падение при выходе.
        """
        if thread is None or not thread.isRunning():
            return
        if not thread.wait(UIConstants.THREAD_STOP_TIMEOUT_MS):
            thread.terminate()
            thread.wait()


def _key(item: PlannedItem) -> Tuple[str, ...]:
    """Устойчивый ключ снятой отметки: он должен пережить пересборку плана."""
    return (item.origin,) + item.source + (item.destination,)


def _minutes(translator: Translator, seconds: float) -> str:
    """Оставшееся время округлённо: точность здесь никому не нужна."""
    if seconds < 60:
        return "%d %s" % (max(int(seconds), 1), translator.translate("MainWindow", "sec"))
    return "%d %s" % (round(seconds / 60), translator.translate("MainWindow", "min"))


def _inside(path: str, root: str) -> bool:
    """
    Лежит ли путь внутри корня. По частям пути, а не по префиксу строки.

    startswith считает «/tmp/dist» лежащим внутри «/t»: ровно та ошибка, от
    которой уходили в resolve_entry_path, и здесь она повторилась.
    """
    try:
        return os.path.commonpath(
            [os.path.normpath(root), os.path.normpath(path)]
        ) == os.path.normpath(root)
    except ValueError:
        # Разные диски на Windows или смесь абсолютного и относительного пути.
        return False


def _relative_to(destination: str, root: str) -> str:
    """Путь внутри каталога роли, без общего начала."""
    normalized_root = os.path.normpath(root).replace("\\", "/").rstrip("/")
    normalized = os.path.normpath(destination).replace("\\", "/")
    if normalized_root and normalized.startswith(normalized_root + "/"):
        return normalized[len(normalized_root) + 1:]
    return normalized


def _demo_bytes(plan: Plan) -> int:
    """
    Сколько весят выгрузки .dt во всём плане.

    Цифра заслуживает места в подписи: у исследованных поставок .cf занимает
    50.5% объёма, .dt — 48.3%, всё остальное 1.2%.
    """
    total = 0
    for item in plan.items:
        if item.template is None:
            continue
        total += sum(
            entry.size for entry in item.template.entries if not keeps_configuration(entry.path)
        )
    return total
