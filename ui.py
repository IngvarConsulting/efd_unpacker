import os
from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QCoreApplication
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QMessageBox, QHBoxLayout, QComboBox
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMovie, QCursor
from os_utils import open_folder
from unpack_service import UnpackService
from settings_service import SettingsService


class UnpackThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, input_file, output_dir):
        super().__init__()
        self.input_file = input_file
        self.output_dir = output_dir

    def run(self):
        success, message = UnpackService.unpack(self.input_file, self.output_dir)
        self.finished.emit(success, message)


class MainWindow(QMainWindow):
    def __init__(self, language='en'):
        super().__init__()
        self.setWindowTitle(self.tr('EFD Unpacker'))
        self.resize(500, 250)
        self.setAcceptDrops(True)

        self.drag_active = False
        self.input_file = None
        self.thread: UnpackThread | None = None # Инициализируем поток
        self.settings_service = SettingsService()
        self.output_path = self.settings_service.get_output_path()
        self.manual_selected_path = None  # путь, выбранный вручную через Select folder

        self.label_input = QLabel(self.tr('Drag .efd file here or click to choose'))
        self.label_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_input.setStyleSheet("border: 2px dashed #aaa; padding: 20px; text-decoration: underline; color: #0078d7;")
        self.label_input.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.label_input.mousePressEvent = self.open_file_dialog

        self.combo_output_paths = QComboBox()
        self.combo_output_paths.setToolTip(self.tr('Reset to Default'))
        self.combo_output_paths.setEditable(False)
        self.combo_output_paths.setMinimumWidth(200)
        self.combo_output_paths.activated.connect(self.on_output_path_selected)
        self.update_output_paths_combobox()
        self.btn_browse = QPushButton(self.tr('Select Folder'))
        self.btn_unpack = QPushButton(self.tr('Unpack'))
        self.btn_unpack.setEnabled(False)
        
        self.loading_label = QLabel()
        self.loading_movie = QMovie("resources/loading.gif")
        
        # Настраиваем качественное масштабирование
        self.loading_movie.setCacheMode(QMovie.CacheMode.CacheAll)  # Кэшируем все кадры для лучшего качества
        self.loading_movie.setScaledSize(QSize(96, 96))  # Оптимальный размер для качества
        
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Добавляем CSS для сглаживания и центрирования
        self.loading_label.setStyleSheet("""
            QLabel { 
                margin: 20px; 
            }
        """)
        self.loading_label.setVisible(False)

        self.label_message = QLabel()
        self.label_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        layout = QVBoxLayout()
        layout.addWidget(self.label_input)
        
        # Новая строка: label + поле + кнопка
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.combo_output_paths)
        output_layout.addWidget(self.btn_browse)
        layout.addLayout(output_layout)
        
        layout.addWidget(self.btn_unpack)
        layout.addWidget(self.loading_label) # Добавляем анимированную иконку
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

        self.btn_browse.clicked.connect(self.browse_output_path)
        self.btn_unpack.clicked.connect(self.unpack_file)

    def update_output_paths_combobox(self):
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

    def on_output_path_selected(self, index):
        path = self.combo_output_paths.itemData(index)
        if path:
            self.output_path = path
            # Если выбран не вручную выбранный путь, сбрасываем manual_selected_path
            if self.manual_selected_path and os.path.normpath(path) != os.path.normpath(self.manual_selected_path):
                self.manual_selected_path = None
                self.update_output_paths_combobox()

    def hide_interface_elements(self):
        """Скрыть все элементы интерфейса кроме анимированной иконки загрузки"""
        self.label_input.setVisible(False)
        self.combo_output_paths.setVisible(False)
        self.btn_browse.setVisible(False)
        self.btn_unpack.setVisible(False)
        self.loading_label.setVisible(True)
        self.loading_movie.start()  # Запускаем анимацию
        self.label_message.setVisible(False)
        self.btn_retry.setVisible(False)
        self.btn_open_folder.setVisible(False)
        self.btn_close.setVisible(False)

    def show_interface_elements(self):
        """Показать все элементы интерфейса"""
        self.label_input.setVisible(True)
        self.combo_output_paths.setVisible(True)
        self.btn_browse.setVisible(True)
        self.btn_unpack.setVisible(True)
        self.loading_movie.stop()  # Останавливаем анимацию
        self.loading_label.setVisible(False)
        self.label_message.setVisible(False)
        self.btn_retry.setVisible(False)
        self.btn_open_folder.setVisible(False)
        self.btn_close.setVisible(False)

    def show_message(self, text, is_error=False):
        """Показать сообщение в основном окне"""
        self.label_input.setVisible(False)
        self.combo_output_paths.setVisible(False)
        self.btn_browse.setVisible(False)
        self.btn_unpack.setVisible(False)
        self.loading_movie.stop()  # Останавливаем анимацию
        self.loading_label.setVisible(False)
        self.label_message.setText(text)
        self.label_message.setStyleSheet("color: #4caf50; font-size: 16px;" if not is_error else "color: #d32f2f; font-size: 16px;")
        self.label_message.setVisible(True)
        self.btn_retry.setVisible(is_error)
        self.btn_open_folder.setVisible(not is_error)
        self.btn_close.setVisible(not is_error)

    def reset_ui(self) -> None:
        self.input_file = None
        self.label_input.setText(self.tr('Drag .efd file here or click to choose'))
        self.label_input.setStyleSheet("border: 2px dashed #aaa; padding: 20px; text-decoration: underline; color: #0078d7;")
        self.show_interface_elements()
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(True)
        self.combo_output_paths.setEnabled(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        mime = event.mimeData()
        if mime and hasattr(mime, "urls"):
            for url in mime.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith('.efd'):
                    event.acceptProposedAction()
                    self.set_drag_active(True)
                    break

    def dragLeaveEvent(self, event):
        self.set_drag_active(False)

    def dropEvent(self, event: QDropEvent):
        self.set_drag_active(False)
        mime = event.mimeData()
        if mime and hasattr(mime, "urls"):
            for url in mime.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith('.efd'):
                    self.set_input_file(url.toLocalFile())
                    break

    def set_drag_active(self, active):
        self.drag_active = active
        if active:
            self.label_input.setText(self.tr('Drop file to upload'))
            self.label_input.setStyleSheet("border: 2px dashed #0078d7; background: #e6f2ff; color: #000000; padding: 20px;")
        else:
            self.label_input.setText(self.tr('Drag .efd file here or click to choose'))
            self.label_input.setStyleSheet("border: 2px dashed #aaa; color: inherit; padding: 20px;")

    def set_input_file(self, file_path):
        if not os.path.exists(file_path):
            QMessageBox.warning(self, self.tr('Error'), self.tr('File does not exist'))
            self.btn_unpack.setEnabled(False)
            return
        if not file_path.lower().endswith('.efd'):
            QMessageBox.warning(self, self.tr('Error'), self.tr('Invalid file format'))
            self.btn_unpack.setEnabled(False)
            return
        self.input_file = file_path
        self.label_input.setText(file_path)
        self.label_input.setStyleSheet("border: 2px solid #4caf50; padding: 20px; background: #f1fff1; color: #000000;")
        self.btn_unpack.setEnabled(True)

    def browse_output_path(self):
        from PyQt6.QtWidgets import QFileDialog
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

    def open_file_dialog(self, ev):
        from PyQt6.QtWidgets import QFileDialog
        file_filter = self.tr('EFD Files (*.efd)')
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr('Select .efd file'), "", file_filter)
        if file_path:
            self.set_input_file(file_path)

    def unpack_file(self, skip_clear_check=False):
        if not self.input_file:
            QMessageBox.warning(self, self.tr('Error'), self.tr('No .efd file selected'))
            return
        output_dir = self.combo_output_paths.currentData()
        if not os.path.isdir(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, self.tr('Error'), self.tr('Invalid output folder'))
                return
        self.hide_interface_elements()
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.combo_output_paths.setEnabled(False)
        self.thread = UnpackThread(self.input_file, output_dir)
        self.thread.finished.connect(self.unpack_finished)
        self.thread.start()

    def unpack_finished(self, success, message):
        if success:
            # Сохраняем путь только после успешной распаковки
            self.settings_service.set_output_path(self.combo_output_paths.currentData())
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

    def open_output_folder(self):
        """Открыть папку с распакованными файлами"""
        output_dir = self.combo_output_paths.currentData()
        open_folder(output_dir)
