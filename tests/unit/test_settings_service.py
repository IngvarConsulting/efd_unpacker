import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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
