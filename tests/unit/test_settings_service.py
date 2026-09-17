import unittest
from unittest.mock import MagicMock, patch

from PyQt5.QtCore import QSettings

from efd_unpacker.infrastructure import settings_service as settings_service_module
from efd_unpacker.infrastructure.settings_service import SettingsService


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return f"tr:{source}"


class TestSettingsService(unittest.TestCase):
    def setUp(self) -> None:
        self.translator = DummyTranslator()

    @patch("efd_unpacker.infrastructure.settings_service.QSettings")
    @patch("efd_unpacker.infrastructure.settings_service.get_1c_configuration_location_default")
    def test_get_output_path_default(self, mock_default, mock_settings) -> None:
        mock_default.return_value = "/default/path"
        instance = MagicMock()
        instance.value.return_value = "/default/path"
        mock_settings.return_value = instance

        service = SettingsService(self.translator)
        result = service.get_output_path()

        self.assertEqual(result, "/default/path")
        instance.value.assert_called_once()

    @patch("efd_unpacker.infrastructure.settings_service.QSettings")
    def test_set_output_path(self, mock_settings) -> None:
        instance = MagicMock()
        mock_settings.return_value = instance
        service = SettingsService(self.translator)
        service.set_output_path("/new/path")
        instance.setValue.assert_called_once_with("output_path", "/new/path")

    @patch("efd_unpacker.infrastructure.settings_service.get_1c_configuration_location_default")
    @patch("efd_unpacker.infrastructure.settings_service.get_1c_configuration_location_from_1cestart")
    @patch("efd_unpacker.infrastructure.settings_service.QSettings")
    def test_get_output_path_items(self, mock_settings, mock_from_1c, mock_default) -> None:
        instance = MagicMock()
        instance.value.return_value = "/last/path"
        mock_settings.return_value = instance
        mock_from_1c.return_value = ["/path/one"]
        mock_default.return_value = "/default/path"

        service = SettingsService(self.translator)
        items = service.get_output_path_items("/manual/path")

        labels = [label for _, label in items]
        self.assertTrue(any(label.startswith("/manual/path") for label in labels))
        self.assertTrue(any("tr:(last used)" in label for label in labels))
        self.assertTrue(any("tr:(default)" in label for label in labels))


if __name__ == "__main__":
    unittest.main()


def test_non_string_setting_falls_back_to_default(tmp_path, monkeypatch):
    """
    Регресс #18: QSettings отдаёт то, что лежит в файле. Конфиг, правленный
    извне, даёт list, а os.path.normpath дальше роняет запуск ещё до
    window.show() — без окна и без сообщения.
    """
    ini = tmp_path / "settings.ini"
    ini.write_text("[General]\noutput_path=/home/u/Templates, old/tmplts\n", encoding="utf-8")
    settings = QSettings(str(ini), QSettings.IniFormat)
    assert not isinstance(settings.value("output_path"), str), "иначе тест проверяет не то"

    monkeypatch.setattr(
        settings_service_module, "get_1c_configuration_location_default", lambda: "/default/tmplts"
    )
    monkeypatch.setattr(
        settings_service_module, "get_1c_configuration_location_from_1cestart", lambda: []
    )
    service = SettingsService(translator=_DummyTranslator(), settings=settings)

    assert service.get_output_path() == "/default/tmplts"
    # Метка именно (last used): откат отдаёт тот же путь, что и default, ветка
    # last_used срабатывает первой и занимает его. Это существующее поведение
    # разметки, а не следствие отката — трогать его здесь незачем.
    assert service.get_output_path_items() == [("/default/tmplts", "/default/tmplts (last used)")]


def test_string_setting_is_used_as_is(tmp_path, monkeypatch):
    ini = tmp_path / "settings.ini"
    ini.write_text("[General]\noutput_path=/home/u/Templates\n", encoding="utf-8")
    settings = QSettings(str(ini), QSettings.IniFormat)

    monkeypatch.setattr(
        settings_service_module, "get_1c_configuration_location_default", lambda: "/default/tmplts"
    )
    service = SettingsService(translator=_DummyTranslator(), settings=settings)

    assert service.get_output_path() == "/home/u/Templates"


class _DummyTranslator:
    def translate(self, _context, source):
        return source
