import os
from PyQt6.QtCore import Qt, QSettings, QThread, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QFileDialog, QMessageBox, QHBoxLayout, QComboBox
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMovie, QCursor
from localization import loc
from os_utils import get_1c_configuration_location_default, get_1c_configuration_location_from_1cestart, open_folder
from unpack_service import UnpackService


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
    def __init__(self):
        super().__init__()
        self.setWindowTitle(loc.get('window_title'))
        self.resize(500, 250)
        self.setAcceptDrops(True)

        self.drag_active = False
        self.settings = QSettings('efd_unpacker', 'settings')
        self.input_file = None
        self.thread: UnpackThread | None = None # Инициализируем поток
        default_output_path = get_1c_configuration_location_default()
        self.output_path = self.settings.value('output_path', default_output_path)
        self.manual_selected_path = None  # путь, выбранный вручную через Select folder

        self.label_input = QLabel(loc.get('drag_drop_hint'))
        self.label_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_input.setStyleSheet("border: 2px dashed #aaa; padding: 20px; text-decoration: underline; color: #0078d7; cursor: pointer;")
        self.label_input.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.label_input.mousePressEvent = self.open_file_dialog

        self.combo_output_paths = QComboBox()
        self.combo_output_paths.setToolTip(loc.get('reset_folder_button'))
        self.combo_output_paths.setEditable(False)
        self.combo_output_paths.setMinimumWidth(200)
        self.combo_output_paths.activated.connect(self.on_output_path_selected)
        self.update_output_paths_combobox()
        self.btn_browse = QPushButton(loc.get('select_folder_button'))
        self.btn_unpack = QPushButton(loc.get('unpack_button'))
        self.btn_unpack.setEnabled(False)
        
        # Заменяем прогресс бар на анимированную иконку загрузки
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
                image-rendering: -webkit-optimize-contrast;
                image-rendering: crisp-edges;
            }
        """)
        self.loading_label.setVisible(False)

        self.label_message = QLabel()
        self.label_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        last_used = self.settings.value('output_path', '')
        from_1cestart = get_1c_configuration_location_from_1cestart()
        default_path = get_1c_configuration_location_default()
        seen = set()
        items = []
        # 1. Вручную выбранный путь (если есть и не совпадает с последним использованным)
        if self.manual_selected_path and os.path.normpath(self.manual_selected_path) != os.path.normpath(last_used):
            label = f"{self.manual_selected_path}"
            items.append((self.manual_selected_path, label))
            seen.add(os.path.normpath(self.manual_selected_path))
        # 2. Последний использованный
        if last_used:
            label = f"{last_used} {loc.get('last_used_label')}"
            if os.path.normpath(last_used) not in seen:
                items.append((last_used, label))
                seen.add(os.path.normpath(last_used))
        # 3. Пути из 1cestart
        for path in from_1cestart:
            norm = os.path.normpath(path)
            if norm not in seen:
                items.append((path, path))
                seen.add(norm)
        # 4. По умолчанию
        norm_default = os.path.normpath(default_path)
        if norm_default not in seen:
            items.append((default_path, f"{default_path} {loc.get('default_label')}"))
            seen.add(norm_default)
        for path, label in items:
            self.combo_output_paths.addItem(label, path)
        # Установить выбранный путь
        current_path = self.manual_selected_path or last_used
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
        self.label_input.setText(loc.get('drag_drop_hint'))
        self.label_input.setStyleSheet("border: 2px dashed #aaa; padding: 20px; text-decoration: underline; color: #0078d7; cursor: pointer;")
        self.show_interface_elements()
        self.btn_unpack.setEnabled(False)
        self.btn_browse.setEnabled(True)
        self.combo_output_paths.setEnabled(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData() is not None and event.mimeData().hasUrls(): # Добавлена проверка на None
            event.acceptProposedAction()
            self.set_drag_active(True)

    def dragLeaveEvent(self, event):
        self.set_drag_active(False)

    def dropEvent(self, event: QDropEvent):
        self.set_drag_active(False)
        if event.mimeData() is not None: # Добавлена проверка на None
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
        directory = QFileDialog.getExistingDirectory(self, loc.get('select_folder_dialog_title'), self.combo_output_paths.currentData())
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
        options = QFileDialog.Option(0)
        file_filter = loc.get('efd_files_filter')
        file_path, _ = QFileDialog.getOpenFileName(self, loc.get('select_efd_file'), "", file_filter, options=options)
        if file_path:
            self.set_input_file(file_path)

    def unpack_file(self, skip_clear_check=False):
        if not self.input_file:
            QMessageBox.warning(self, loc.get('error_title'), loc.get('no_file_selected'))
            return
        output_dir = self.combo_output_paths.currentData()
        if not os.path.isdir(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, loc.get('error_title'), loc.get('invalid_output_folder'))
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
            self.settings.setValue('output_path', self.combo_output_paths.currentData())
            # После успешной распаковки manual_selected_path сбрасывается
            self.manual_selected_path = None
            self.update_output_paths_combobox()
        self.btn_unpack.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.combo_output_paths.setEnabled(True)
        if success:
            self.show_message(message, is_error=False)
        else:
            self.show_message(loc.get('unpack_error', error_message=message), is_error=True)

    def open_output_folder(self):
        """Открыть папку с распакованными файлами"""
        output_dir = self.combo_output_paths.currentData()
        open_folder(output_dir)
        
