"""
Окно массовой распаковки.

Строка списка — это шаблон, а не файл. Иначе список врёт: demo.zip несёт два
шаблона разных продуктов, а server64_*.zip в каталог шаблонов не попадёт
вовсе. План из #51 уже устроен так же, окно просто его показывает.

Окно не тупиковое: после распаковки список остаётся, и можно бросить ещё
файлы, не перезапуская приложение.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..application.executor import Writers
from ..application.inspector import inspect_all
from ..application.messages import format_validation_error
from ..application.report import human_bytes
from ..constants import Styles, UIConstants
from ..domain.batch import run as run_batch
from ..domain.errors import FileValidationError, UnpackError
from ..domain.file_validator import FileValidator
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
from ..infrastructure.os_utils import open_folder
from ..infrastructure.settings_service import SettingsService
from ..localization.translator import Translator
from .threads import BatchThread, PlanThread, describe_failure

#: Состояние строки кодируется формой, а не только цветом: залитый квадрат
#: будет распакован, пустой — отфильтрован, прочерк — пропуск по делу,
#: круг — отказ. Пропуск и отказ намеренно разные: «уже установлено» —
#: нормальный исход, а не проблема.
MARK_WRITE = "■"
MARK_FILTERED = "□"
MARK_SKIP = "—"
MARK_FAIL = "●"
MARK_RUNNING = "▶"
MARK_DONE = "✓"

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

COLUMNS = ("", "name", "version", "size", "where")


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

        self._inspected: List = []
        self._plan = Plan()
        self._outcomes: Dict[int, Tuple[str, Optional[UnpackError]]] = {}
        self._plan_thread: Optional[PlanThread] = None
        self._batch_thread: Optional[BatchThread] = None
        self._templates_root = ""
        self._written_kinds: set = set()

        self._build_ui()
        self._refresh_footer()

    # --- построение окна -----------------------------------------------------

    def _t(self, context: str, text: str) -> str:
        return self.translator.translate(context, text)

    def _build_ui(self) -> None:
        self.setWindowTitle(self._t("MainWindow", "EFD Unpacker"))
        self.setMinimumSize(UIConstants.WINDOW_WIDTH + 420, UIConstants.WINDOW_HEIGHT + 240)
        self.setAcceptDrops(True)

        self.label_input = QLabel(self._t("MainWindow", "Drag files here or click to choose"))
        self.label_input.setAlignment(Qt.AlignCenter)
        self.label_input.setStyleSheet(Styles.INPUT_NORMAL)
        self.label_input.mousePressEvent = self.open_file_dialog

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [self._t("Report", key) if key else "" for key in COLUMNS]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)

        self.check_only_cf = QCheckBox(self._t("MainWindow", "Without demo databases"))
        self.check_only_cf.stateChanged.connect(self._rebuild_plan)

        self.label_roots = QLabel("")
        self.label_roots.setStyleSheet("color: #5E6A72;")
        self.label_roots.setWordWrap(True)

        self.btn_paths = QPushButton(self._t("MainWindow", "Change folders…"))
        self.btn_paths.clicked.connect(self.browse_output_path)
        self.btn_unpack = QPushButton(self._t("MainWindow", "Unpack"))
        self.btn_unpack.clicked.connect(self.unpack)
        self.btn_unpack.setEnabled(False)
        self.btn_cancel = QPushButton(self._t("MainWindow", "Cancel"))
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.setEnabled(False)
        self.btn_open = QPushButton(self._t("MainWindow", "Open Folder"))
        self.btn_open.clicked.connect(self.open_output_folder)
        self.btn_open.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_paths)
        buttons.addStretch()
        buttons.addWidget(self.btn_open)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_unpack)

        layout = QVBoxLayout()
        layout.addWidget(self.label_input)
        layout.addWidget(self.table)
        layout.addWidget(self.check_only_cf)
        layout.addWidget(self.label_roots)
        layout.addLayout(buttons)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

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
        if active:
            self.label_input.setText(self._t("MainWindow", "Drop files to inspect"))
            self.label_input.setStyleSheet(Styles.INPUT_DRAG)
        else:
            self.label_input.setText(self._t("MainWindow", "Drag files here or click to choose"))
            self.label_input.setStyleSheet(Styles.INPUT_NORMAL)

    def open_file_dialog(self, _event) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._t("MainWindow", "Select files"), "",
            self._t("MainWindow", "Supply and distribution files (*.efd *.zip *.rar *.dmg *.tar *.gz *.bz2 *.xz)"),
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

        self.label_input.setText(self._t("MainWindow", "Inspecting…"))
        self.btn_unpack.setEnabled(False)
        thread = PlanThread(paths, self._inspect_files)
        thread.ready.connect(self._inspection_ready)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._forget_plan_thread)
        self._plan_thread = thread
        thread.start()
        return True

    def _inspection_ready(self, inspected, error: Optional[UnpackError]) -> None:
        self._set_drag_active(False)
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
        self._outcomes = {}
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
        previous = self._plan
        self._plan = self._build(self._inspected, self._settings())
        if self._plan.items != previous.items:
            # Исходы привязаны к объектам прежнего плана. Оставить их значит
            # рисковать совпадением id у нового объекта на месте старого.
            self._outcomes = {}
        self._fill_table()
        self._refresh_footer()
        self.btn_unpack.setEnabled(bool(self._plan.to_write) and not self._unpacking())

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self._plan.items))
        for row, item in enumerate(self._plan.items):
            for column, text in enumerate(self._row_cells(item)):
                cell = QTableWidgetItem(text)
                if column in (0, 3):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column, cell)

    def _row_cells(self, item: PlannedItem) -> Tuple[str, ...]:
        return (
            self._mark(item),
            item.title,
            item.version,
            human_bytes(item.bytes_total) if item.bytes_total else "",
            self._where(item),
        )

    def _mark(self, item: PlannedItem) -> str:
        outcome, _error = self._outcomes.get(_key(item), (None, None))
        if outcome == "running":
            return MARK_RUNNING
        if outcome == "written":
            return MARK_DONE
        if outcome == "failed":
            return MARK_FAIL
        if item.action is Action.FAIL:
            return MARK_FAIL
        if item.action is Action.SKIP:
            return MARK_FILTERED if item.reason is SkipReason.FILTERED_OUT else MARK_SKIP
        return MARK_WRITE

    def _where(self, item: PlannedItem) -> str:
        """
        Роль каталога и путь внутри него, без общего начала.

        Повторять «/Users/…/tmplts» в каждой строке незачем: оно одно на все
        и вынесено в подвал.
        """
        _outcome, error = self._outcomes.get(_key(item), (None, None))
        if error is not None:
            return describe_failure(self.translator, error)
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

    def _refresh_footer(self) -> None:
        saved = _demo_bytes(self._plan)
        self.check_only_cf.setText(
            "%s — %s" % (
                self._t("MainWindow", "Without demo databases"),
                self._t("MainWindow", "saves %s") % human_bytes(saved),
            )
            if saved
            else self._t("MainWindow", "Without demo databases")
        )
        self.label_roots.setText(
            "%s → %s\n%s → %s" % (
                self._t("MainWindow", ROLE_TEMPLATES),
                self.settings_service.get_output_path(),
                self._t("MainWindow", ROLE_DISTRIBUTIONS),
                self.settings_service.get_distributions_path(),
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
        занятостью, окно блокировало кнопку «Распаковать» ровно в тот момент,
        когда список уже показан, — и разблокировать её было некому.
        """
        return self._running(self._batch_thread)

    def unpack(self) -> None:
        if self._unpacking() or not self._plan.to_write:
            return

        needs_templates = any(item.kind is ItemKind.SUPPLY for item in self._plan.to_write)
        needs_distributions = any(item.kind is not ItemKind.SUPPLY for item in self._plan.to_write)
        try:
            # Готовим только те каталоги, в которые действительно поедет:
            # раньше каталог шаблонов создавался даже для пачки из одних
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
        self._outcomes = {}

        # Поток создаётся до писателей: им нужен его флаг отмены. Без него
        # «Отмена» действовала только на границе между элементами, и пачка из
        # одного архива дописывалась целиком после нажатия.
        thread = BatchThread(self._plan, None, self._batch)
        thread.set_writers(self._make_writers(
            self.unpack_service, templates_root, self.check_only_cf.isChecked(),
            thread.cancelled,
        ))
        thread.item_progress.connect(self._item_started)
        thread.item_finished.connect(self._item_finished)
        thread.completed.connect(self._batch_finished)
        # Настоящий QThread.finished, а не наш completed: он приходит после
        # фактического выхода из run(), когда объект уже можно удалять.
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._forget_batch_thread)
        self._batch_thread = thread

        self.btn_unpack.setEnabled(False)
        self.btn_paths.setEnabled(False)
        self.check_only_cf.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        thread.start()

    def cancel(self) -> None:
        thread = self._batch_thread
        if thread is not None and thread.isRunning():
            thread.cancel()
            self.btn_cancel.setEnabled(False)

    def _item_started(self, item: PlannedItem) -> None:
        self._outcomes[_key(item)] = ("running", None)
        self._fill_table()

    def _item_finished(self, item: PlannedItem, error: Optional[UnpackError]) -> None:
        self._outcomes[_key(item)] = ("failed" if error is not None else "written", error)
        self._fill_table()

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

    def _batch_finished(self, result) -> None:
        self.btn_paths.setEnabled(True)
        self.check_only_cf.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_open.setEnabled(bool(result.written))
        # Кнопка распаковки снова доступна: окно не тупиковое, и повтор после
        # отмены или отказа не требует перезапуска.
        self.btn_unpack.setEnabled(bool(self._plan.to_write))
        self.label_input.setText(self._t("MainWindow", "Drag files here or click to choose"))

        self._written_kinds = {item.kind for item in result.written}
        if any(item.kind is ItemKind.SUPPLY for item in result.written):
            # Сохраняем только когда в каталог шаблонов действительно писали.
            self.settings_service.set_output_path(self._templates_root)

    def _forget_batch_thread(self) -> None:
        self._batch_thread = None

    # --- пути и папка --------------------------------------------------------

    def browse_output_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self._t("MainWindow", "Select output folder"),
            self.settings_service.get_output_path(),
        )
        if not directory:
            return
        self.settings_service.set_output_path(directory)
        self._rebuild_plan()

    def open_output_folder(self) -> None:
        root = self._written_root()
        if not root:
            return
        if open_folder(root):
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
            # роняет приложение при выходе.
            self._stop(self._plan_thread)
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
        event.accept()

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


def _key(item: PlannedItem) -> int:
    """
    Ключ исхода — тождество объекта, а не его поля.

    В отчёте CLI хватает пары «источник плюс назначение»: там каждый файл
    осматривается один раз. В окне тот же файл можно бросить дважды, и тогда
    план несёт два одинаковых по полям элемента — отметка об исполнении одного
    ставилась бы сразу на оба.

    Исход привязан к текущему плану: при пересборке объекты создаются заново,
    и `_outcomes` очищается вместе с ними.
    """
    return id(item)


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
