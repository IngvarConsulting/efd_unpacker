import os
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QCoreApplication
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QMessageBox, QHBoxLayout, QComboBox
)
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QMovie, QCursor
from os_utils import open_folder
from unpack_service import UnpackService
from settings_service import SettingsService
from file_validator import FileValidator
from constants import UIConstants, UIState, Styles, FileExtensions
from typing import Optional, List, Tuple


class UnpackThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, input_file: str, output_dir: str) -> None:
        super().__init__()
        self.input_file = input_file
        self.output_dir = output_dir

    def run(self) -> None:
        success, message = UnpackService.unpack(self.input_file, self.output_dir)
        self.finished.emit(success, message)


class MainWindow(QMainWindow):
    def __init__(self, language: str = 'en') -> None:
        super().__init__()
        self.language = language
        
        self._init_window_properties()
        self._init_services()
        self._init_ui_elements()
        self._init_layout()
        self._connect_signals()

    def _init_window_properties(self) -> None:
        """Инициализирует свойства окна"""
        self.setWindowTitle(self.tr('EFD Unpacker'))
        self.resize(UIConstants.WINDOW_WIDTH, UIConstants.WINDOW_HEIGHT)
        self.setAcceptDrops(True)

    def _init_services(self) -> None:
        """Инициализирует сервисы"""
        self.settings_service = SettingsService()
        self.output_path = self.settings_service.get_output_path()
        self.manual_selected_path: Optional[str] = None

    def _init_ui_elements(self) -> None:
        """Инициализирует UI элементы"""
        self._create_input_area()
        self._create_output_area()
        self._create_buttons()
        self._create_loading_area()
        self._create_message_area()

    def _create_input_area(self) -> None:
        """Создает область ввода файла"""
        self.drag_active = False
        self.input_file: Optional[str] = None
        self.thread: Optional[UnpackThread] = None
        
        self.label_input = QLabel(self.tr('Drag .efd file here or click to choose'))
        self.label_input.setAlignment(Qt.AlignCenter)
        self.label_input.setStyleSheet(Styles.INPUT_NORMAL)
        self.label_input.setCursor(QCursor(Qt.PointingHandCursor))
        self.label_input.mousePressEvent = self.open_file_dialog

    def _create_output_area(self) -> None:
        """Создает область выбора выходной папки"""
        self.combo_output_paths = QComboBox()
        self.combo_output_paths.setToolTip(self.tr('Reset to Default'))
        self.combo_output_paths.setEditable(False)
        self.combo_output_paths.setMinimumWidth(UIConstants.COMBO_MIN_WIDTH)
        self.combo_output_paths.activated.connect(self.on_output_path_selected)
        self.update_output_paths_combobox()

    def _create_buttons(self) -> None:
        """Создает кнопки"""
        self.btn_browse = QPushButton(self.tr('Select Folder'))
        self.btn_unpack = QPushButton(self.tr('Unpack'))
        self.btn_unpack.setEnabled(False)

    def _create_loading_area(self) -> None:
        """Создает область загрузки"""
        self.loading_label = QLabel()
        self.loading_movie = QMovie("resources/loading.gif")
        
        # Настраиваем качественное масштабирование
        self.loading_movie.setCacheMode(QMovie.CacheAll)
        self.loading_movie.setScaledSize(QSize(UIConstants.LOADING_ICON_SIZE, UIConstants.LOADING_ICON_SIZE))
        
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet(Styles.LOADING_LABEL)
        self.loading_label.setVisible(False)

    def _create_message_area(self) -> None:
        """Создает область сообщений"""
        self.label_message = QLabel()
        self.label_message.setAlignment(Qt.AlignCenter)
        self.label_message.setWordWrap(True)
        self.label_message.setVisible(False)
        
        self.btn_retry = QPushButton(self.tr('Retry'))
        self.btn_retry.setVisible(False)
        self.btn_retry.clicked.connect(self.reset_ui)

        self.btn_open_folder = QPushButton(self.tr('Open Folder'))
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        
        self.btn_close = QPushButton(self.tr('Close'))
        self.btn_close.setVisible(False)
        self.btn_close.clicked.connect(self.close)

    def _init_layout(self) -> None:
        """Инициализирует layout"""
        layout = QVBoxLayout()
        layout.addWidget(self.label_input)
        
        # Новая строка: label + поле + кнопка
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.combo_output_paths)
        output_layout.addWidget(self.btn_browse)
        layout.addLayout(output_layout)
        
        layout.addWidget(self.btn_unpack)
        layout.addWidget(self.loading_label)
        layout.addWidget(self.label_message)
        layout.addWidget(self.btn_retry)
        
        # Горизонтальный layout для кнопок успешного завершения
        success_buttons_layout = QHBoxLayout()
        success_buttons_layout.addWidget(self.btn_open_folder)
        success_buttons_layout.addWidget(self.btn_close)
        layout.addLayout(success_buttons_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _connect_signals(self) -> None:
        """Подключает сигналы"""
        self.btn_browse.clicked.connect(self.browse_output_path)
        self.btn_unpack.clicked.connect(self.unpack_file)

    def update_output_paths_combobox(self) -> None:
        self.combo_output_paths.clear()
        # Используем SettingsService для получения списка путей
        items = self.settings_service.get_output_path_items(self.manual_selected_path)
        
        for path, label in items:
            self.combo_output_paths.addItem(label, path)
        
        # Установить выбранный путь
        current_path = self.manual_selected_path or self.settings_service.get_output_path()
        if current_path:
            idx = self.combo_output_paths.findData(current_path)
            if idx != -1:
                self.combo_output_paths.setCurrentIndex(idx)

    def on_output_path_selected(self, index: int) -> None:
        path = self.combo_output_paths.itemData(index)
        if path:
            self.output_path = path
            # Если выбран не вручную выбранный путь, сбрасываем manual_selected_path
            if self.manual_selected_path and os.path.normpath(path) != os.path.normpath(self.manual_selected_path):
                self.manual_selected_path = None
                self.update_output_paths_combobox()

    def set_ui_state(self, state: UIState) -> None:
        """Устанавливает состояние UI"""
        # Скрываем все элементы
        self.label_input.setVisible(False)
        self.combo_output_paths.setVisible(False)
        self.btn_browse.setVisible(False)
        self.btn_unpack.setVisible(False)
        self.loading_label.setVisible(False)
        self.label_message.setVisible(False)
        self.btn_retry.setVisible(False)
        self.btn_open_folder.setVisible(False)
        self.btn_close.setVisible(False)
        
        # Останавливаем анимацию
        self.loading_movie.stop()
        
        # Показываем элементы в зависимости от состояния
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

    def hide_interface_elements(self) -> None:
        """Скрыть все элементы интерфейса кроме анимированной иконки загрузки"""
        self.set_ui_state(UIState.LOADING)

    def show_interface_elements(self) -> None:
        """Показать все элементы интерфейса"""
        self.set_ui_state(UIState.NORMAL)

    def show_message(self, text: str, is_error: bool = False) -> None:
        """Показать сообщение в основном окне"""
        self.label_message.setText(text)
        self.label_message.setStyleSheet(Styles.MESSAGE_SUCCESS if not is_error else Styles.MESSAGE_ERROR)
        self.set_ui_state(UIState.ERROR if is_error else UIState.SUCCESS)

    def reset_ui(self) -> None:
        self.input_file = None
        self.label_input.setText(self.tr('Drag .efd file here or click to choose'))
        self.label_input.setStyleSheet(Styles.INPUT_NORMAL)
        self.show_interface_elements()
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(True)
        self.combo_output_paths.setEnabled(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime and hasattr(mime, "urls"):
            for url in mime.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(FileExtensions.EFD):
                    event.acceptProposedAction()
                    self.set_drag_active(True)
                    break

    def dragLeaveEvent(self, event) -> None:
        self.set_drag_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self.set_drag_active(False)
        mime = event.mimeData()
        if mime and hasattr(mime, "urls"):
            for url in mime.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(FileExtensions.EFD):
                    self.set_input_file(url.toLocalFile())
                    break

    def set_drag_active(self, active: bool) -> None:
        self.drag_active = active
        if active:
            self.label_input.setText(self.tr('Drop file to upload'))
            self.label_input.setStyleSheet(Styles.INPUT_DRAG)
        else:
            self.label_input.setText(self.tr('Drag .efd file here or click to choose'))
            self.label_input.setStyleSheet(Styles.INPUT_NORMAL)

    def set_input_file(self, file_path: str) -> None:
        # Используем FileValidator для валидации файла
        is_valid, error_message = FileValidator.validate_efd_file(file_path)
        if not is_valid:
            QMessageBox.warning(self, self.tr('Error'), error_message)
            self.btn_unpack.setEnabled(False)
            return
        
        self.input_file = file_path
        self.label_input.setText(file_path)
        self.label_input.setStyleSheet(Styles.INPUT_SUCCESS)
        self.btn_unpack.setEnabled(True)

    def browse_output_path(self) -> None:
        from PyQt5.QtWidgets import QFileDialog
        from settings_service import SettingsService
        directory = QFileDialog.getExistingDirectory(self, self.tr('Select output folder'), self.combo_output_paths.currentData())
        if directory:
            self.manual_selected_path = directory
            self.output_path = directory
            self.update_output_paths_combobox()
            idx = self.combo_output_paths.findData(directory)
            if idx != -1:
                self.combo_output_paths.setCurrentIndex(idx)
        self.btn_browse.setEnabled(True)
        self.combo_output_paths.setEnabled(True)

    def open_file_dialog(self, ev) -> None:
        from PyQt5.QtWidgets import QFileDialog
        file_filter = self.tr('EFD Files (*.efd)')
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr('Select .efd file'), "", file_filter)
        if file_path:
            self.set_input_file(file_path)

    def unpack_file(self, skip_clear_check: bool = False) -> None:
        if not self.input_file:
            QMessageBox.warning(self, self.tr('Error'), self.tr('No .efd file selected'))
            return
        
        output_dir = self.combo_output_paths.currentData()
        
        # Используем FileValidator для валидации и создания директории
        success, error_message = FileValidator.create_output_directory(output_dir)
        if not success:
            QMessageBox.warning(self, self.tr('Error'), error_message)
            return
        
        self.hide_interface_elements()
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.combo_output_paths.setEnabled(False)
        self.thread = UnpackThread(self.input_file, output_dir)
        self.thread.finished.connect(self.unpack_finished)
        self.thread.start()

    def unpack_finished(self, success: bool, message: str) -> None:
        if success:
            # Сохраняем путь только после успешной распаковки
            from settings_service import SettingsService
            settings_service = SettingsService()
            settings_service.set_output_path(self.combo_output_paths.currentData())
            # После успешной распаковки manual_selected_path сбрасывается
            self.manual_selected_path = None
            self.update_output_paths_combobox()
        self.btn_unpack.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.combo_output_paths.setEnabled(True)
        if success:
            self.show_message(message, is_error=False)
        else:
            self.show_message(self.tr('Unpack error: %1').replace('%1', message), is_error=True)

    def open_output_folder(self) -> None:
        open_folder(self.output_path)
