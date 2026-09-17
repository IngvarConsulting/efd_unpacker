import os

os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
os.environ.setdefault("QT_API", "pyqt5")

import threading
import time

import pytest
from PyQt5.QtCore import QObject
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QMessageBox, QWidget

from efd_unpacker.domain.file_validator import FileValidator
from efd_unpacker.domain.unpack_service import UnpackService
from efd_unpacker.presentation.ui import MainWindow, UnpackThread


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return source


class DummySettingsService:
    def __init__(self) -> None:
        self.path = "/tmp"

    def get_output_path(self) -> str:
        return self.path

    def set_output_path(self, path: str) -> None:
        self.path = path

    def get_output_path_items(self, manual_selected_path=None):
        base = manual_selected_path or self.path
        return [(base, base)]


class DummyUnpackService(UnpackService):
    def __init__(self) -> None:
        pass

    def unpack(self, input_file: str, output_dir: str) -> None:
        self.last_call = (input_file, output_dir)


@pytest.mark.parametrize("initial_path", ["/tmp/test"])
def test_main_window_initializes(qtbot, initial_path, monkeypatch):
    translator = DummyTranslator()
    settings = DummySettingsService()
    settings.path = initial_path
    window = MainWindow(
        translator=translator,
        settings_service=settings,
        file_validator=FileValidator(),
        unpack_service=DummyUnpackService(),
    )
    qtbot.addWidget(window)
    assert window.combo_output_paths.count() == 1


def test_unpack_finished_persists_actual_output_path(qtbot, monkeypatch):
    translator = DummyTranslator()
    settings = DummySettingsService()
    chosen_output = "/chosen/output"

    window = MainWindow(
        translator=translator,
        settings_service=settings,
        file_validator=FileValidator(),
        unpack_service=DummyUnpackService(),
    )
    qtbot.addWidget(window)

    window.output_path = chosen_output
    monkeypatch.setattr(window, "show_message", lambda *args, **kwargs: None)

    window.unpack_finished(True, "done")

    assert settings.path == chosen_output


class BlockingUnpackService(UnpackService):
    """Распаковка, которая крутится, пока её не попросят остановиться."""

    def __init__(self) -> None:
        self.started = threading.Event()

    def unpack(self, input_file: str, output_dir: str, cancel_check=None) -> None:
        self.started.set()
        while cancel_check is None or not cancel_check():
            time.sleep(0.005)


def _window_with_running_unpack(qtbot, tmp_path):
    window = MainWindow(
        translator=DummyTranslator(),
        settings_service=DummySettingsService(),
        file_validator=FileValidator(),
        unpack_service=BlockingUnpackService(),
    )
    qtbot.addWidget(window)

    source = tmp_path / "sample.efd"
    source.write_text("payload", encoding="utf-8")
    window.input_file = str(source)
    window.combo_output_paths.clear()
    window.combo_output_paths.addItem(str(tmp_path), str(tmp_path))

    window.unpack_file()
    assert window.unpack_service.started.wait(5)
    return window


def test_window_stays_open_when_closing_is_declined(qtbot, tmp_path, monkeypatch):
    window = _window_with_running_unpack(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)

    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted()
    assert window._unpack_thread.isRunning()

    window._unpack_thread.cancel()
    window._unpack_thread.wait(5000)


def test_confirmed_close_waits_for_the_thread(qtbot, tmp_path, monkeypatch):
    window = _window_with_running_unpack(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    thread = window._unpack_thread

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert not thread.isRunning()


def test_close_without_running_thread_is_accepted(qtbot):
    window = MainWindow(
        translator=DummyTranslator(),
        settings_service=DummySettingsService(),
        file_validator=FileValidator(),
        unpack_service=DummyUnpackService(),
    )
    qtbot.addWidget(window)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()


def test_qobject_thread_method_is_not_shadowed(qtbot):
    """Поле self.thread затеняло встроенный QObject.thread() и давало TypeError."""
    window = MainWindow(
        translator=DummyTranslator(),
        settings_service=DummySettingsService(),
        file_validator=FileValidator(),
        unpack_service=DummyUnpackService(),
    )
    qtbot.addWidget(window)

    assert window.thread() is QObject.thread(window)


def test_second_unpack_is_ignored_while_the_first_runs(qtbot, tmp_path, monkeypatch):
    window = _window_with_running_unpack(qtbot, tmp_path)
    thread = window._unpack_thread

    window.unpack_file()

    assert window._unpack_thread is thread

    thread.cancel()
    thread.wait(5000)


def test_custom_signal_does_not_shadow_qthread_finished(qtbot):
    thread = UnpackThread(DummyUnpackService(), DummyTranslator(), "in.efd", "/tmp")
    qtbot.addWidget(QWidget())

    assert hasattr(thread, "completed")
    # Встроенный finished остался без аргументов, поэтому на него можно
    # безопасно вешать deleteLater.
    assert thread.metaObject().indexOfSignal("finished()") != -1
