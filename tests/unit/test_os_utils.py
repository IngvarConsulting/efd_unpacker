import os
import sys
from unittest import mock

from efd_unpacker.infrastructure import os_utils


def test_get_1c_configuration_location_default_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\User\AppData\Roaming")
    expected = os.path.join(r"C:\Users\User\AppData\Roaming", "1C", "1cv8", "tmplts")
    result = os_utils.get_1c_configuration_location_default()
    assert os.path.normpath(result) == os.path.normpath(expected)


def test_get_1c_configuration_location_default_unix(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    result = os_utils.get_1c_configuration_location_default()
    assert result.startswith(str(tmp_path))


def test_open_folder_windows_uses_startfile(monkeypatch, tmp_path):
    target = tmp_path / "tmplts"
    target.mkdir()
    startfile = mock.Mock()

    monkeypatch.setattr(os_utils.platform, "system", lambda: "Windows")
    monkeypatch.setattr(os_utils.os, "startfile", startfile, raising=False)

    assert os_utils.open_folder(str(target)) is True
    startfile.assert_called_once_with(str(target))
