"""
PyQt UI, использующий доменные сервисы и переводчик через DI.
"""

from __future__ import annotations

import os
from typing import Optional

from PyQt5 import QtWidgets
from PyQt5.QtCore import QThread, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QCursor, QDragEnterEvent, QDropEvent, QMovie
from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..application.messages import format_unpack_result, format_validation_error
from ..constants import FileExtensions, Styles, UIConstants, UIState
from ..domain.errors import FileValidationError, UnpackError
from ..domain.file_validator import FileValidator
from ..domain.unpack_service import UnpackService
from ..infrastructure.os_utils import open_folder
from ..infrastructure.settings_service import SettingsService
from ..localization.translator import Translator
from ..runtime import resource_path


class UnpackThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, unpack_service: UnpackService, translator: Translator, input_file: str, output_dir: str) -> None:
        super().__init__()
        self.unpack_service = unpack_service
        self.translator = translator
        self.input_file = input_file
        self.output_dir = output_dir

    def run(self) -> None:  # pragma: no cover - потоковая логика
        try:
            self.unpack_service.unpack(self.input_file, self.output_dir)
            message = format_unpack_result(self.translator, success=True)
            self.finished.emit(True, message)
        except UnpackError as exc:
            message = format_unpack_result(self.translator, success=False, error=exc)
            self.finished.emit(False, message)


class MainWindow(QMainWindow):
    def __init__(
        self,
        translator: Translator,
        settings_service: SettingsService,
        file_validator: FileValidator,
        unpack_service: UnpackService,
    ) -> None:
        super().__init__()
        self.translator = translator
        self.settings_service = settings_service
        self.file_validator = file_validator
        self.unpack_service = unpack_service

        self.output_path = self.settings_service.get_output_path()
        self.manual_selected_path: Optional[str] = None
        self.input_file: Optional[str] = None
        self.thread: Optional[UnpackThread] = None

        self._init_window_properties()
        self._init_ui_elements()
        self._init_layout()
        self._connect_signals()
        self.update_output_paths_combobox()

    def _t(self, context: str, text: str) -> str:
        return self.translator.translate(context, text)

    def _init_window_properties(self) -> None:
        self.setWindowTitle(self._t("MainWindow", "EFD Unpacker"))
        self.resize(UIConstants.WINDOW_WIDTH, UIConstants.WINDOW_HEIGHT)
        self.setAcceptDrops(True)

    def _init_ui_elements(self) -> None:
        self.label_input = QLabel(self._t("MainWindow", "Drag .efd file here or click to choose"))
        self.label_input.setAlignment(Qt.AlignCenter)
        self.label_input.setStyleSheet(Styles.INPUT_NORMAL)
        self.label_input.setCursor(QCursor(Qt.PointingHandCursor))
        self.label_input.mousePressEvent = self.open_file_dialog  # type: ignore

        self.combo_output_paths = QComboBox()
        self.combo_output_paths.setToolTip(self._t("MainWindow", "Reset to Default"))
        self.combo_output_paths.setEditable(False)
        self.combo_output_paths.setMinimumWidth(UIConstants.COMBO_MIN_WIDTH)

        self.btn_browse = QPushButton(self._t("MainWindow", "Select Folder"))
        self.btn_unpack = QPushButton(self._t("MainWindow", "Unpack"))
        self.btn_unpack.setEnabled(False)

        self.loading_label = QLabel()
        self.loading_movie = QMovie(resource_path("resources", "loading.gif"))
        self.loading_movie.setCacheMode(QMovie.CacheAll)
        self.loading_movie.setScaledSize(QSize(UIConstants.LOADING_ICON_SIZE, UIConstants.LOADING_ICON_SIZE))
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet(Styles.LOADING_LABEL)
        self.loading_label.setVisible(False)

        self.label_message = QLabel()
        self.label_message.setAlignment(Qt.AlignCenter)
        self.label_message.setWordWrap(True)
        self.label_message.setVisible(False)

        self.btn_retry = QPushButton(self._t("MainWindow", "Retry"))
        self.btn_retry.setVisible(False)

        self.btn_open_folder = QPushButton(self._t("MainWindow", "Open Folder"))
        self.btn_open_folder.setVisible(False)

        self.btn_close = QPushButton(self._t("MainWindow", "Close"))
        self.btn_close.setVisible(False)

    def _init_layout(self) -> None:
        layout = QVBoxLayout()
        layout.addWidget(self.label_input)

        output_layout = QHBoxLayout()
        output_layout.addWidget(self.combo_output_paths)
        output_layout.addWidget(self.btn_browse)
        layout.addLayout(output_layout)

        layout.addWidget(self.btn_unpack)
        layout.addWidget(self.loading_label)
        layout.addWidget(self.label_message)
        layout.addWidget(self.btn_retry)

        success_buttons_layout = QHBoxLayout()
        success_buttons_layout.addWidget(self.btn_open_folder)
        success_buttons_layout.addWidget(self.btn_close)
        layout.addLayout(success_buttons_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _connect_signals(self) -> None:
        self.combo_output_paths.activated.connect(self.on_output_path_selected)
        self.btn_browse.clicked.connect(self.browse_output_path)
        self.btn_unpack.clicked.connect(self.unpack_file)
        self.btn_retry.clicked.connect(self.reset_ui)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        self.btn_close.clicked.connect(self.close)

    def update_output_paths_combobox(self) -> None:
        self.combo_output_paths.clear()
        items = self.settings_service.get_output_path_items(self.manual_selected_path)
        for path, label in items:
            self.combo_output_paths.addItem(label, path)

        current_path = self.manual_selected_path or self.settings_service.get_output_path()
        if current_path:
            idx = self.combo_output_paths.findData(current_path)
            if idx != -1:
                self.combo_output_paths.setCurrentIndex(idx)

    def on_output_path_selected(self, index: int) -> None:
        path = self.combo_output_paths.itemData(index)
        if path:
            self.output_path = path
            if self.manual_selected_path and os.path.normpath(path) != os.path.normpath(self.manual_selected_path):
                self.manual_selected_path = None
                self.update_output_paths_combobox()

    def set_ui_state(self, state: UIState) -> None:
        for widget in [
            self.label_input,
            self.combo_output_paths,
            self.btn_browse,
            self.btn_unpack,
            self.loading_label,
            self.label_message,
            self.btn_retry,
            self.btn_open_folder,
            self.btn_close,
        ]:
            widget.setVisible(False)

        self.loading_movie.stop()

        if state == UIState.NORMAL:
            self.label_input.setVisible(True)
            self.combo_output_paths.setVisible(True)
            self.btn_browse.setVisible(True)
            self.btn_unpack.setVisible(True)
        elif state == UIState.LOADING:
            self.loading_label.setVisible(True)
            self.loading_movie.start()
        elif state == UIState.SUCCESS:
            self.label_message.setVisible(True)
            self.btn_open_folder.setVisible(True)
            self.btn_close.setVisible(True)
        elif state == UIState.ERROR:
            self.label_message.setVisible(True)
            self.btn_retry.setVisible(True)

    def show_message(self, text: str, is_error: bool = False) -> None:
        self.label_message.setText(text)
        self.label_message.setStyleSheet(Styles.MESSAGE_ERROR if is_error else Styles.MESSAGE_SUCCESS)
        self.set_ui_state(UIState.ERROR if is_error else UIState.SUCCESS)

    def reset_ui(self) -> None:
        self.input_file = None
        self.label_input.setText(self._t("MainWindow", "Drag .efd file here or click to choose"))
        self.label_input.setStyleSheet(Styles.INPUT_NORMAL)
        self.set_ui_state(UIState.NORMAL)
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(True)
        self.combo_output_paths.setEnabled(True)

    # Drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime and hasattr(mime, "urls"):
            for url in mime.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(FileExtensions.EFD):
                    event.acceptProposedAction()
                    self._set_drag_active(True)
                    break

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drag_active(False)
        mime = event.mimeData()
        if mime and hasattr(mime, "urls"):
            for url in mime.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(FileExtensions.EFD):
                    self.set_input_file(url.toLocalFile())
                    break

    def _set_drag_active(self, active: bool) -> None:
        if active:
            self.label_input.setText(self._t("MainWindow", "Drop file to upload"))
            self.label_input.setStyleSheet(Styles.INPUT_DRAG)
        else:
            self.label_input.setText(self._t("MainWindow", "Drag .efd file here or click to choose"))
            self.label_input.setStyleSheet(Styles.INPUT_NORMAL)

    def set_input_file(self, file_path: str) -> None:
        try:
            normalized = self.file_validator.validate_input_file(file_path)
        except FileValidationError as exc:
            message = format_validation_error(self.translator, exc)
            QMessageBox.warning(self, self._t("MainWindow", "Error"), message)
            self.btn_unpack.setEnabled(False)
            return

        self.input_file = normalized
        self.label_input.setText(normalized)
        self.label_input.setStyleSheet(Styles.INPUT_SUCCESS)
        self.btn_unpack.setEnabled(True)

    def browse_output_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            self._t("MainWindow", "Select output folder"),
            self.combo_output_paths.currentData(),
        )
        if directory:
            self.manual_selected_path = directory
            self.output_path = directory
            self.update_output_paths_combobox()
            idx = self.combo_output_paths.findData(directory)
            if idx != -1:
                self.combo_output_paths.setCurrentIndex(idx)

    def open_file_dialog(self, _event) -> None:
        file_filter = self._t("MainWindow", "EFD Files (*.efd)")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self._t("MainWindow", "Select .efd file"),
            "",
            file_filter,
        )
        if file_path:
            self.set_input_file(file_path)

    def unpack_file(self) -> None:
        if not self.input_file:
            QMessageBox.warning(self, self._t("MainWindow", "Error"), self._t("MainWindow", "No .efd file selected"))
            return

        try:
            prepared_output = self.file_validator.prepare_output_directory(self.combo_output_paths.currentData())
        except FileValidationError as exc:
            message = format_validation_error(self.translator, exc)
            QMessageBox.warning(self, self._t("MainWindow", "Error"), message)
            return

        self.set_ui_state(UIState.LOADING)
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.combo_output_paths.setEnabled(False)

        self.thread = UnpackThread(self.unpack_service, self.translator, self.input_file, prepared_output)
        self.thread.finished.connect(self.unpack_finished)
        self.thread.start()

    def unpack_finished(self, success: bool, message: str) -> None:
        self.btn_unpack.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.combo_output_paths.setEnabled(True)

        if success:
            self.settings_service.set_output_path(self.combo_output_paths.currentData())
            self.manual_selected_path = None
            self.update_output_paths_combobox()
            self.show_message(f"[OK] {message}", is_error=False)
        else:
            self.show_message(f"[ERROR] {message}", is_error=True)

    def open_output_folder(self) -> None:
        if self.output_path:
            open_folder(self.output_path)
