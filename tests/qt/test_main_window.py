import os

os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
os.environ.setdefault("QT_API", "pyqt5")

import pytest

from efd_unpacker.domain.file_validator import FileValidator
from efd_unpacker.domain.unpack_service import UnpackService
from efd_unpacker.presentation.ui import MainWindow


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
