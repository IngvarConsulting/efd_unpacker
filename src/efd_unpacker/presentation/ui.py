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
from ..application import report
from ..application.messages import format_validation_error
from ..constants import UIConstants
from ..domain.batch import run as run_batch
from ..domain.errors import FileValidationError, UnpackError
from ..domain.file_validator import FileValidator
from ..domain.manifest import read as read_manifest
from ..domain.manifest import summarize as summarize_appearance
from ..domain.plan import (
    Action,
    ItemKind,
    Plan,
    PlanSettings,
    PlannedItem,
    SkipReason,
    build_plan,
    holds_data,
    keeps_configuration,
)
from ..domain.unpack_service import UnpackService
from ..infrastructure import rar
from ..infrastructure.os_utils import move_to_trash, open_folder
from ..runtime import app_version
from ..infrastructure.settings_service import SettingsService
from ..localization.translator import Translator
from . import rows, screens, style
from .threads import BatchThread, PlanThread, describe_failure

APP_VERSION = app_version()

#: Высота значка шестерёнки, из макета.
GEAR_HEIGHT = 15

#: Что перечисляет подсказка в зоне броска.
#:
#: Вокруг точки один пробел, а не два. С двумя строка занимала 404 точки в
#: Menlo при 376 доступных внутри рамки, и её срезало с обоих концов: вместо
#: «.efd» было видно «efd», вместо «.dmg» — «.dm». Ширина рамки взята из
#: макета, а ширина моноширинной гарнитуры у каждой системы своя, поэтому
#: место экономит строка, а не рамка.
FORMATS_HINT = ".efd · .zip · .tar.gz · .tar.bz2 · .rar · .dmg"

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
        #: Ключи отметок того, что записано в этом запуске ЦЕЛИКОМ. По ним
        #: кнопка «Удалить архивы» узнаёт, что исходный файл больше не нужен.
        self._written: set = set()
        #: Ключи того, что записано не целиком: часть осталась в архиве.
        #: Перевешивает «уже установлено» — см. _is_unpacked.
        self._partial: set = set()
        #: Каталоги, про которые человек сказал «всё равно распакуй».
        #: Путями, а не ключами отметок: вопрос «уже установлено?» задаётся
        #: именно каталогу, и два архива, метящие в один и тот же, спорить о
        #: нём не должны.
        self._forced: set = set()
        #: Стоял ли фильтр на старте последнего батча. См. _wrote_in_full.
        self._filtered = False
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
        self.setWindowTitle("%s %s" % (
            self._t("MainWindow", "EFD Unpacker"), APP_VERSION,
        ))
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

        # Тот же знак, что в строках, и слева — там же, где знаки строк.
        # Подпись-ссылка справа говорила только про снятие и ничем не
        # показывала нынешнее состояние: отмечено всё, ничего или часть.
        # Знак показывает это сам и работает в обе стороны.
        self.mark_all = rows.Mark(rows.PENDING)
        self.mark_all.setCursor(Qt.PointingHandCursor)
        self.mark_all.clicked.connect(self._toggle_all_marks)

        bar = QHBoxLayout()
        bar.setContentsMargins(style.SIDE_PADDING, 11, style.SIDE_PADDING, 11)
        bar.setSpacing(11)
        bar.addWidget(self.mark_all, 0, Qt.AlignVCenter)
        bar.addWidget(self.label_counts)
        bar.addStretch()

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
        self.label_formats = QLabel(FORMATS_HINT)
        self.label_formats.setAlignment(Qt.AlignCenter)
        # Переносится, а не обрезается. Укороченная строка помещается в одну
        # строку у всех известных мне гарнитур, но ширину чужого моноширинного
        # шрифта не знает никто, а QLabel по умолчанию режет текст молча — и
        # ровно так «.efd» и «.dmg» исчезли с краёв. Перенос — страховка: в
        # худшем случае список поедет на вторую строку, но целым.
        self.label_formats.setWordWrap(True)
        self.label_formats.setStyleSheet(
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
        inner.addWidget(self.label_formats)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(choose)
        row.addStretch()
        inner.addLayout(row)

        self.zone = QFrame()
        self.zone.setObjectName("zone")
        self.zone.setLayout(inner)
        self.zone.setStyleSheet(style.drop_zone_sheet())
        # Ширина из макета, и закреплена она нарочно. Раньше стоял только
        # потолок, а до потолка рамку дотягивала сама подсказка: её строка
        # просила 404 точки в Menlo и упиралась в 440. То есть ширина карточки
        # держалась на длине перечня расширений — стоило его укоротить, и
        # рамка съехала с 440 до 314. Минимальная ширина окна от этого не
        # меняется: 464 точки и с потолком, и с закреплением.
        self.zone.setFixedWidth(440)

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

        self.button_trash = QPushButton(self._t("MainWindow", "Delete archives"))
        self.button_trash.setStyleSheet(style.secondary_button_sheet())
        self.button_trash.setCursor(Qt.PointingHandCursor)
        self.button_trash.clicked.connect(self.delete_unpacked_archives)
        self.button_trash.hide()

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
        bar.addWidget(self.button_trash)
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
        # Скругление задаётся таблицей стилей, а окно под меню остаётся
        # непрозрачным — и по углам вылезают чёрные треугольники. Прозрачный
        # фон убирает их, безрамочность нужна, чтобы система не рисовала
        # собственную рамку поверх, а отказ от тени — чтобы тень не осталась
        # прямоугольной вокруг скруглённой карточки.
        menu.setAttribute(Qt.WA_TranslucentBackground)
        menu.setWindowFlags(
            menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )

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

        # Показываем ЗАНЯТОСТЬ сразу, до первого файла. Осмотр идёт в фоне, и
        # пока он шёл, в главной области не менялось ничего: на десятке
        # архивов пауза до списка читается как зависание, а человек только что
        # бросил файлы и смотрит именно туда, куда бросил.
        self._show_inspecting(self._t("MainWindow", "Inspecting…"))
        self.button_unpack.setEnabled(False)
        thread = PlanThread(paths, self._inspect_files)
        thread.started_file.connect(self._inspection_started)
        thread.ready.connect(self._inspection_ready)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._forget_plan_thread)
        self._plan_thread = thread
        thread.start()
        return True

    def _show_inspecting(self, text: str) -> None:
        """
        Одно и то же сообщение в двух местах — по одному на каждый случай.

        Список пуст — видна зона броска, и человек смотрит в неё. Список уже
        есть — видна сводка над ним, а зоны броска на экране нет вовсе.
        Писать только в подвал мало: подпись там мелкая и стоит далеко от
        того места, куда только что бросили файлы.
        """
        self.label_drop.setText(text)
        self.label_counts.setText(text)
        self.label_status.setText(text)

    def _inspection_started(self, _path: str, done: int, total: int) -> None:
        """Ход осмотра. Счёт, а не имя файла: имена длинные и прыгают."""
        self._show_inspecting("%s %s" % (
            self._t("MainWindow", "Inspecting…"),
            self._t("MainWindow", "%s of %s") % (done, total),
        ))

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
            is_installed=self._is_installed,
        )

    def _is_installed(self, destination: str) -> bool:
        """
        Считать ли каталог уже распакованным.

        Каталог на месте — ещё не ответ. Распаковка могла оборваться на
        середине: кнопкой «Остановить», отказом, закрытием окна. Снаружи это
        не отличить, а человек отличает — и, настояв на строке, говорит нам
        то, чего мы сами не видим.
        """
        return os.path.isdir(destination) and destination not in self._forced

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
            row.toggled.connect(lambda item=item: self._mark_toggled(item))
            if item.reason is SkipReason.RAR_TOOL_MISSING:
                # Экран инструментов достижим и по месту, а не только из меню:
                # строка сообщает, что программы нет, и здесь же говорит, где
                # про неё прочитать.
                row.offer_open(self._t("MainWindow", "Tools…"))
                row.open_requested.connect(self.show_tools)
            else:
                row.open_requested.connect(lambda item=item: self._open_item(item))
                if item.reason is SkipReason.ALREADY_INSTALLED:
                    # Каталог на месте — значит, есть куда смотреть, и человеку
                    # ровно это и нужно: проверить, что там лежит, прежде чем
                    # настаивать на перезаписи. У готовой строки та же кнопка;
                    # «уже установлено» и есть «готово», только прошлым запуском.
                    row.offer_open(self._t("MainWindow", "Open Folder"))
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
            # Отказ осмотра, а не распаковки. Выглядит так же, но повторять
            # нечего: исполнение такой элемент не открывает, а лишь повторяет
            # уже записанную ошибку, — см. domain/batch.run.
            return rows.BROKEN
        if item.action is Action.SKIP:
            # «Уже установлено» — наше умолчание, а не невозможность, и знак
            # у него переключается: см. TOGGLEABLE. Прочие пропуски желанием
            # не лечатся.
            if item.reason is SkipReason.ALREADY_INSTALLED:
                return rows.INSTALLED
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

    def _is_unpacked(self, item: PlannedItem) -> bool:
        """
        Лежит ли содержимое этого элемента распакованным ЦЕЛИКОМ.

        Три ответа, и первый сильнее прочих. Когда мы своими руками записали
        не всё, каталог всё равно оказывается на месте — и «уже установлено»
        отвечает «да». Знание о собственной записи перевешивает догадку по
        каталогу: без этого снятие фильтра одним щелчком возвращало кнопку
        удаления архиву, в котором осталась единственная копия демобазы.

        Ключ отметки, а не строка: строки пересобираются при смене фильтра, и
        по ним «записано в этом запуске» не переживёт ни одного переключения.
        """
        key = self._mark_key(item)
        if key in self._partial:
            return False
        if item.action is Action.SKIP and item.reason is SkipReason.ALREADY_INSTALLED:
            return True
        return key in self._written

    def _wrote_in_full(self, item: PlannedItem) -> bool:
        """
        Всё ли содержимое элемента уехало на диск.

        Спрашивается у содержимого, а не у флажка. Суди мы по одному флажку
        на всю пачку — архивы, из которых фильтру нечего было унести, не
        предлагались бы к удалению никогда, хотя терять в них нечего.

        Шаблон есть только у поставки (его ставит один _supply_item), и через
        это дистрибутив отвечает «целиком» сам собой: фильтр его не касается.
        """
        if not self._filtered or item.template is None:
            return True
        return not holds_data(item.template)

    def _unpacked_origins(self) -> List[str]:
        """
        Исходные файлы, ВСЁ содержимое которых распаковано.

        Всё, а не хоть что-нибудь: в одной поставке бывает несколько
        шаблонов, и если один записан, а другой отказал, удалять архив
        нельзя — второго взять будет неоткуда.
        """
        by_origin: Dict[str, List[PlannedItem]] = {}
        for item in self._plan.items:
            by_origin.setdefault(item.origin, []).append(item)
        return sorted(
            origin for origin, items in by_origin.items()
            if all(self._is_unpacked(item) for item in items)
        )

    def _trash_size(self, origins: Sequence[str]) -> int:
        total = 0
        for path in origins:
            try:
                total += os.path.getsize(path)
            except OSError:
                # Файла уже нет или он недоступен: в подпись он не попадёт,
                # а в корзину и так не уедет.
                continue
        return total

    def delete_unpacked_archives(self) -> None:
        """
        Переносит в корзину архивы, всё содержимое которых распаковано.

        Спрашивает до того, как трогать: файлы чужие, человек скачивал их
        сам, и список для удаления он вправе увидеть до, а не после.
        """
        origins = self._unpacked_origins()
        if not origins:
            return

        names = "\n".join("· %s" % os.path.basename(path) for path in origins[:12])
        if len(origins) > 12:
            names += "\n…"
        answer = QMessageBox.question(
            self,
            self._t("MainWindow", "Delete archives"),
            "%s\n\n%s\n\n%s" % (
                self._t("MainWindow", "Move to the trash the archives already unpacked?"),
                names,
                self._t("MainWindow", "Frees %s") % style.human_size(
                    self._trash_size(origins)
                ),
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        moved, failed = move_to_trash(origins)
        if failed:
            QMessageBox.warning(
                self, self._t("MainWindow", "Error"),
                "%s\n%s" % (
                    self._t("MainWindow", "Some archives could not be moved:"),
                    "\n".join("· %s" % os.path.basename(path) for path in failed),
                ),
            )
        # Убираем из списка то, чего больше нет: строка, чей исходный файл
        # уехал в корзину, обещала бы распаковку, которой не выйдет.
        gone = set(moved)
        self._inspected = [item for item in self._inspected if item.path not in gone]
        self._rebuild_plan()
    def _toggle_all_marks(self) -> None:
        """
        Отмечено всё — снимаем всё, иначе отмечаем всё.

        Наполовину отмеченный список по щелчку отмечается целиком, а не
        снимается: так ведут себя списки с общим флажком везде, и это
        единственное действие, которое нельзя получить щелчками по строкам
        быстрее, чем общим знаком.
        """
        if self.mark_all.state() == rows.PENDING:
            self._clear_marks()
            return
        for item in self._plan.items:
            row = self._row_of.get(id(item))
            # Всё предлагаемое, а не только снятое: отказ распаковки тоже
            # предлагается повторить (см. OFFERED), и «отметить все» обязано
            # брать и его — иначе после сплошных отказов кнопка обещала бы
            # действие и не делала ничего.
            if row is not None and row.state() in rows.OFFERED:
                if row.state() != rows.PENDING:
                    row.set_state(rows.PENDING)
                self._unchecked.discard(self._mark_key(item))
        self._refresh()

    def _mark_all_state(self) -> str:
        """
        Вид общего знака по тому, что отмечено в строках.

        Считаются предлагаемые строки (OFFERED). Отказ осмотра не отмечается
        никаким желанием, а «уже установлено» отмечается только поимённо —
        считать их значило бы никогда не показывать «отмечено всё».

        Отказ РАСПАКОВКИ при этом считается — он переключается, то есть
        просто не отмечен. Не считай мы его, смесь отмеченного и отказавшего
        выглядела бы как «отмечено всё», хотя отказавшая строка не поедет.
        """
        states = [row.state() for row in self.rows if row.state() in rows.OFFERED]
        if not states or all(state != rows.PENDING for state in states):
            return rows.UNCHECKED
        return rows.PENDING if all(state == rows.PENDING for state in states) else rows.PARTIAL

    def _mark_toggled(self, item: PlannedItem) -> None:
        """
        Щелчок по знаку строки.

        Обычной строке хватает пересчёта подписей. «Уже установлено» — другое
        дело: чтобы настоянная строка правда поехала, план обязан пересобраться
        с нею как с записью. Исполнение берёт из плана только то, у чего
        action = WRITE (см. Plan.to_write), и отметки одной ему мало.

        Пересборка здесь по карману: осмотр не повторяется, а построение плана
        из уже осмотренного стоит микросекунд — см. _rebuild_plan.
        """
        destination = item.destination
        row = self._row_of.get(id(item))
        if item.reason is SkipReason.ALREADY_INSTALLED:
            self._forced.add(destination)
        elif destination in self._forced and (row is None or row.state() != rows.PENDING):
            # Настоянное сняли — возвращаем умолчание, а с ним и честную
            # подпись «уже установлено» вместо пути, по которому никто не
            # поедет.
            self._forced.discard(destination)
        else:
            self._refresh()
            return

        # Отметку после пересборки задаёт _initial_state, и прошлое «снято»
        # ему помешало бы: настоянная строка вышла бы неотмеченной.
        self._unchecked.discard(self._mark_key(item))
        self._rebuild_plan()

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
        self._written = set()
        self._forced = set()
        # _partial переживает очистку, а _written — нет, и это не оплошность.
        # Стороны неравны: забыв «записано целиком», мы всего лишь перестанем
        # предлагать удаление. Забыв «записано не всё», мы предложим удалить
        # архив, в котором осталась единственная копия демобазы, — тот же
        # список, брошенный заново, придёт «уже установленным».
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
        state = self._mark_all_state()
        self.mark_all.set_state(state)
        # Двумя вызовами, а не тернарником внутри одного: сверку переводов
        # делает разбор исходника, и строку, спрятанную в выражение, он не
        # видит — обе записи в каталоге выглядели бы осиротевшими.
        if state == rows.PENDING:
            hint = self._t("MainWindow", "Clear all marks")
        else:
            hint = self._t("MainWindow", "Mark everything")
        self.mark_all.setToolTip(hint)
        self.mark_all.setAccessibleName(self.mark_all.toolTip())
        self.label_counts.setText(self._counts_text())
        origins = self._unpacked_origins()
        self.button_trash.setVisible(bool(origins) and not self._unpacking())
        if origins:
            self.button_trash.setText("%s · %s" % (
                self._t("MainWindow", "Delete archives"),
                style.human_size(self._trash_size(origins)),
            ))
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
            (report.COUNT_FILES, len(self._inspected)),
            (report.COUNT_TEMPLATES, kinds[ItemKind.SUPPLY]),
            (report.COUNT_DISTRIBUTIONS, kinds[ItemKind.PLATFORM] + kinds[ItemKind.PACKAGES]),
            (report.COUNT_OTHER, kinds[ItemKind.CONTENT] + kinds[ItemKind.OTHER]),
            (report.COUNT_SKIPPED, skipped),
            (report.COUNT_ERRORS, failed),
        ]
        return "  ·  ".join(
            self.translator.translate_n("Report", source, value)
            for source, value in parts if value
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
        # Снимается на старте: к концу батча человек мог переключить фильтр, а
        # писалось то, что стояло в начале.
        self._filtered = self.check_only_cf.isChecked()
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
        self.mark_all.setEnabled(False)
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

        Что именно попадёт в строку, решает summarize: дерево 1С повторяет
        само себя, и печатать его дословно значит печатать одно имя трижды.
        """
        if item.kind is not ItemKind.SUPPLY:
            return
        delivered = self._read_manifest(item.destination).delivered(item.destination)
        appearance = summarize_appearance(delivered)
        if appearance:
            row.set_appears(
                self._t("MainWindow", "In 1C it will appear as:"),
                appearance,
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
        self.mark_all.setEnabled(True)
        self.button_stop.hide()
        self.button_unpack.show()
        self.button_clear.setVisible(True)
        self.progress_total.hide()

        self._written_kinds = {item.kind for item in result.written}
        # Записанным ПОЛНОСТЬЮ считается не всё записанное. С «без демобаз»
        # из шаблона не пишется .dt, и он остаётся только внутри архива:
        # удалить такой архив значило бы потерять демобазу насовсем.
        #
        # Неполнота запоминается отдельно, а не просто не попадает в
        # записанное: каталог после такой распаковки существует, и любая
        # следующая пересборка плана назовёт элемент «уже установленным».
        for written in result.written:
            key = self._mark_key(written)
            if self._wrote_in_full(written):
                self._written.add(key)
                self._partial.discard(key)
                # Настояние отработало и больше не нужно: каталог неполон был
                # до нас, а теперь мы сами его дописали. Оставь мы его, любая
                # следующая пересборка плана — щелчок по фильтру, новый файл в
                # списке — снова объявляла бы каталог неустановленным и
                # возвращала строку ОТМЕЧЕННОЙ. Настаивали один раз, а
                # переписывалось бы при каждом запуске.
                self._forced.discard(written.destination)
            else:
                self._partial.add(key)
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
        # Обновление ОБЯЗАНО повториться здесь, а не только в конце батча.
        #
        # _batch_finished приходит по нашему completed, а тот испускается
        # изнутри run(): к моменту доставки QThread ещё числится работающим,
        # и _unpacking() отвечает «да». Всё, что _refresh гасит и прячет на
        # время распаковки — «Распаковать» и «Удалить архивы», — оставалось
        # бы таким до следующего чужого обновления, то есть до случайного
        # щелчка по строке.
        #
        # Порядок доставки здесь не гарантирован ничем: на Linux и Windows
        # completed обычно успевает прийти уже после выхода из run(), на
        # macOS — не всегда. Ловилось это как редкое падение теста кнопки
        # удаления, но на глазах у человека выглядело бы хуже: распаковка
        # кончилась, а кнопок нет.
        self._refresh()

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
