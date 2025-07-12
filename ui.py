import os
import onec_dtools
from PyQt5.QtCore import Qt, QSettings, QThread, pyqtSignal, QSize
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QFileDialog, QLineEdit, QMessageBox, QHBoxLayout, QStyle
)
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QMovie, QTransform
from localization import loc
import sys
from os_utils import get_default_unpack_dir, open_folder


class UnpackThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, input_file, output_dir):
        super().__init__()
        self.input_file = input_file
        self.output_dir = output_dir

    def run(self):
        try:
            with open(self.input_file, 'rb') as f:
                supply_reader = onec_dtools.SupplyReader(f)
                supply_reader.unpack(self.output_dir)
            self.finished.emit(True, loc.get('unpack_success'))
        except FileNotFoundError:
            self.finished.emit(False, loc.get('file_not_found_error'))
        except PermissionError:
            self.finished.emit(False, loc.get('permission_error'))
        except Exception as e:
            self.finished.emit(False, loc.get('unexpected_error', error=str(e)))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(loc.get('window_title'))
        self.resize(500, 250)
        self.setAcceptDrops(True)

        self.drag_active = False
        self.settings = QSettings('efd_unpacker', 'settings')
        self.input_file = None
        default_output_path = get_default_unpack_dir()
        self.output_path = self.settings.value('output_path', default_output_path)

        self.label_input = QLabel(loc.get('drag_drop_hint'))
        self.label_input.setAlignment(Qt.AlignCenter)
        self.label_input.setStyleSheet("border: 2px dashed #aaa; padding: 20px; text-decoration: underline; color: #0078d7; cursor: pointer;")
        self.label_input.setCursor(Qt.PointingHandCursor)
        self.label_input.mousePressEvent = self.open_file_dialog

        self.edit_output = QLineEdit(self.output_path)
        self.edit_output.setReadOnly(True)
        self.btn_browse = QPushButton(loc.get('select_folder_button'))
        self.btn_reset_path = QPushButton()
        self.btn_reset_path.setToolTip(loc.get('reset_folder_button'))
        self.btn_reset_path.setIcon(self.style().standardIcon(QStyle.SP_FileDialogBack))
        self.btn_unpack = QPushButton(loc.get('unpack_button'))
        self.btn_unpack.setEnabled(False)
        
        # Заменяем прогресс бар на анимированную иконку загрузки
        self.loading_label = QLabel()
        self.loading_movie = QMovie("resources/loading.gif")
        
        # Настраиваем качественное масштабирование
        self.loading_movie.setCacheMode(QMovie.CacheAll)  # Кэшируем все кадры для лучшего качества
        self.loading_movie.setScaledSize(QSize(96, 96))  # Оптимальный размер для качества
        
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.setAlignment(Qt.AlignCenter)
        # Добавляем CSS для сглаживания и центрирования
        self.loading_label.setStyleSheet("""
            QLabel { 
                margin: 20px; 
                image-rendering: -webkit-optimize-contrast;
                image-rendering: crisp-edges;
            }
        """)
        self.loading_label.setVisible(False)

        self.label_message = QLabel()
        self.label_message.setAlignment(Qt.AlignCenter)
        self.label_message.setWordWrap(True)
        self.label_message.setVisible(False)
        self.btn_retry = QPushButton(loc.get('retry_button'))
        self.btn_retry.setVisible(False)
        self.btn_retry.clicked.connect(self.reset_ui)

        self.btn_open_folder = QPushButton(loc.get('open_folder_button'))
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        self.btn_close = QPushButton(loc.get('close_button'))
        self.btn_close.setVisible(False)
        self.btn_close.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(self.label_input)
        
        # Новая строка: label + поле + кнопка
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.edit_output)
        output_layout.addWidget(self.btn_browse)
        output_layout.addWidget(self.btn_reset_path)
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
        self.btn_reset_path.clicked.connect(self.reset_output_path)

    def hide_interface_elements(self):
        """Скрыть все элементы интерфейса кроме анимированной иконки загрузки"""
        self.label_input.setVisible(False)
        self.edit_output.setVisible(False)
        self.btn_browse.setVisible(False)
        self.btn_reset_path.setVisible(False)
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
        self.edit_output.setVisible(True)
        self.btn_browse.setVisible(True)
        self.btn_reset_path.setVisible(True)
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
        self.edit_output.setVisible(False)
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

    def reset_ui(self):
        self.input_file = None
        self.label_input.setText(loc.get('drag_drop_hint'))
        self.label_input.setStyleSheet("border: 2px dashed #aaa; padding: 20px; text-decoration: underline; color: #0078d7; cursor: pointer;")
        self.edit_output.setText(self.output_path)
        self.show_interface_elements()
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(True)
        self.btn_reset_path.setEnabled(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.set_drag_active(True)

    def dragLeaveEvent(self, event):
        self.set_drag_active(False)

    def dropEvent(self, event: QDropEvent):
        self.set_drag_active(False)
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith('.efd'):
                self.set_input_file(url.toLocalFile())
                break

    def set_drag_active(self, active):
        self.drag_active = active
        if active:
            self.label_input.setText(loc.get('drop_file_hint'))
            self.label_input.setStyleSheet("border: 2px dashed #0078d7; background: #e6f2ff; color: #000000; padding: 20px;")
        else:
            self.label_input.setText(loc.get('drag_drop_hint'))
            self.label_input.setStyleSheet("border: 2px dashed #aaa; color: inherit; padding: 20px;")

    def set_input_file(self, file_path):
        if not os.path.exists(file_path):
            QMessageBox.warning(self, loc.get('error_title'), loc.get('file_does_not_exist'))
            self.btn_unpack.setEnabled(False)
            return
        if not file_path.lower().endswith('.efd'):
            QMessageBox.warning(self, loc.get('error_title'), loc.get('invalid_file_format'))
            self.btn_unpack.setEnabled(False)
            return
        self.input_file = file_path
        self.label_input.setText(loc.get('file_selected', file_path=file_path))
        self.label_input.setStyleSheet("border: 2px solid #4caf50; padding: 20px; background: #f1fff1; color: #000000;")
        self.btn_unpack.setEnabled(True)

    def browse_output_path(self):
        directory = QFileDialog.getExistingDirectory(self, loc.get('select_folder_dialog_title'), self.output_path)
        if directory:
            self.output_path = directory
            self.edit_output.setText(directory)
            self.settings.setValue('output_path', directory)
        self.btn_browse.setEnabled(True)
        self.btn_reset_path.setEnabled(True)

    def open_file_dialog(self, event):
        file_path, _ = QFileDialog.getOpenFileName(self, loc.get('select_efd_file'), os.getcwd(), loc.get('efd_files_filter'))
        if file_path:
            self.set_input_file(file_path)

    def unpack_file(self, skip_clear_check=False):
        if not self.input_file:
            QMessageBox.warning(self, loc.get('error_title'), loc.get('no_file_selected'))
            return
        output_dir = self.edit_output.text()
        if not os.path.isdir(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, loc.get('error_title'), loc.get('invalid_output_folder'))
                return

        self.hide_interface_elements()
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.btn_reset_path.setEnabled(False)

        self.thread = UnpackThread(self.input_file, output_dir)
        self.thread.finished.connect(self.unpack_finished)
        self.thread.start()

    def unpack_finished(self, success, message):
        self.btn_unpack.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.btn_reset_path.setEnabled(True)
        if success:
            self.show_message(message, is_error=False)
        else:
            self.show_message(loc.get('unpack_error', error_message=message), is_error=True)

    def open_output_folder(self):
        """Открыть папку с распакованными файлами"""
        output_dir = self.edit_output.text()
        open_folder(output_dir)

    def reset_output_path(self):
        default_output_path = get_default_unpack_dir()
        if not os.path.exists(default_output_path):
            os.makedirs(default_output_path, exist_ok=True)
        self.output_path = default_output_path
        self.edit_output.setText(default_output_path)
        self.settings.setValue('output_path', default_output_path)
