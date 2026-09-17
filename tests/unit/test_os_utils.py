import os
import subprocess
import sys
from unittest import mock

import pytest

from efd_unpacker.infrastructure import os_utils


def test_get_1c_configuration_location_default_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\User\AppData\Roaming")
    expected = os.path.join(r"C:\Users\User\AppData\Roaming", "1C", "1cv8", "tmplts")
    result = os_utils.get_1c_configuration_location_default()
    assert os.path.normpath(result) == os.path.normpath(expected)


def test_get_1c_configuration_location_default_windows_without_appdata(monkeypatch, tmp_path):
    """Пустой APPDATA уводит распаковку в текущий каталог — неожиданно, но так и работает."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.chdir(tmp_path)

    result = os_utils.get_1c_configuration_location_default()

    assert os.path.normpath(result) == os.path.normpath(os.path.join(str(tmp_path), "tmplts"))


def test_get_1c_configuration_location_default_unix(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os_utils.os.path, "expanduser", lambda _path: str(tmp_path))

    result = os_utils.get_1c_configuration_location_default()

    assert result == os.path.join(str(tmp_path), ".1cv8", "1C", "1cv8", "tmplts")


# --- разбор 1cestart.cfg -----------------------------------------------------

CONFIG_LINE = "ConfigurationTemplatesLocation=/opt/1c/tmplts"


def _write_config(tmp_path, monkeypatch, payload: bytes):
    """Кладёт 1cestart.cfg в поддельный HOME и настраивает expanduser."""
    home = tmp_path / "home"
    config_dir = home / ".1C" / "1cestart"
    config_dir.mkdir(parents=True)
    (config_dir / "1cestart.cfg").write_bytes(payload)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os_utils.os.path, "expanduser", lambda _path: str(home))
    return home


def test_cfg_utf8(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, (CONFIG_LINE + "\n").encode("utf-8"))

    assert os_utils.get_1c_configuration_location_from_1cestart() == ["/opt/1c/tmplts"]


def test_cfg_utf8_with_bom(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, (CONFIG_LINE + "\n").encode("utf-8-sig"))

    assert os_utils.get_1c_configuration_location_from_1cestart() == ["/opt/1c/tmplts"]


def test_cfg_missing_file_returns_empty(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os_utils.os.path, "expanduser", lambda _path: str(home))

    assert os_utils.get_1c_configuration_location_from_1cestart() == []


def test_cfg_ignores_unrelated_lines(tmp_path, monkeypatch):
    payload = ("CommonInfoBases=x\n" + CONFIG_LINE + "\nOther=y\n").encode("utf-8")
    _write_config(tmp_path, monkeypatch, payload)

    assert os_utils.get_1c_configuration_location_from_1cestart() == ["/opt/1c/tmplts"]


def test_cfg_collects_several_locations(tmp_path, monkeypatch):
    payload = (CONFIG_LINE + "\nConfigurationTemplatesLocation=/srv/tmplts\n").encode("utf-8")
    _write_config(tmp_path, monkeypatch, payload)

    assert os_utils.get_1c_configuration_location_from_1cestart() == [
        "/opt/1c/tmplts",
        "/srv/tmplts",
    ]


def test_cfg_cp1251_with_odd_length_works(tmp_path, monkeypatch):
    """Нечётная длина спасает: utf-16le на ней падает, и перебор доходит до cp1251."""
    payload = "ConfigurationTemplatesLocation=/opt/Шаблоны\r\n".encode("cp1251")
    assert len(payload) % 2 == 1
    _write_config(tmp_path, monkeypatch, payload)

    assert os_utils.get_1c_configuration_location_from_1cestart() == ["/opt/Шаблоны"]


@pytest.mark.xfail(
    strict=True,
    reason="#18: платформа 1С пишет конфиг в UTF-16, сейчас такой файл даёт пустой список",
)
@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le"], ids=["utf-16+BOM", "utf-16le без BOM"])
def test_cfg_utf16_is_not_parsed(tmp_path, monkeypatch, encoding):
    _write_config(tmp_path, monkeypatch, (CONFIG_LINE + "\r\n").encode(encoding))

    assert os_utils.get_1c_configuration_location_from_1cestart() == ["/opt/1c/tmplts"]


@pytest.mark.xfail(
    strict=True,
    reason="#18: utf-16le декодирует любую чётную последовательность без исключения и обрывает перебор",
)
def test_cfg_cp1251_with_even_length_is_lost(tmp_path, monkeypatch):
    payload = "ConfigurationTemplatesLocation=/opt/Шаблоныx\r\n".encode("cp1251")
    assert len(payload) % 2 == 0
    _write_config(tmp_path, monkeypatch, payload)

    assert os_utils.get_1c_configuration_location_from_1cestart() == ["/opt/Шаблоныx"]


def test_cfg_windows_reads_appdata_and_allusersprofile(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    for name, value in (("APPDATA", tmp_path / "roaming"), ("ALLUSERSPROFILE", tmp_path / "all")):
        config_dir = value / "1C" / "1CEStart"
        config_dir.mkdir(parents=True)
        (config_dir / "1cestart.cfg").write_text(
            f"ConfigurationTemplatesLocation=/from/{name}\n", encoding="utf-8"
        )
        monkeypatch.setenv(name, str(value))

    result = os_utils.get_1c_configuration_location_from_1cestart()

    assert result == ["/from/APPDATA", "/from/ALLUSERSPROFILE"]


# --- open_folder -------------------------------------------------------------


def test_open_folder_returns_false_for_missing_path(tmp_path):
    assert os_utils.open_folder(str(tmp_path / "nope")) is False


def test_open_folder_windows_uses_startfile(monkeypatch, tmp_path):
    target = tmp_path / "tmplts"
    target.mkdir()
    startfile = mock.Mock()

    monkeypatch.setattr(os_utils.platform, "system", lambda: "Windows")
    monkeypatch.setattr(os_utils.os, "startfile", startfile, raising=False)

    assert os_utils.open_folder(str(target)) is True
    startfile.assert_called_once_with(str(target))


@pytest.mark.parametrize(
    "system, expected_command",
    [("Darwin", "open"), ("Linux", "xdg-open")],
)
def test_open_folder_uses_platform_command(monkeypatch, tmp_path, system, expected_command):
    target = tmp_path / "tmplts"
    target.mkdir()
    run = mock.Mock()

    monkeypatch.setattr(os_utils.platform, "system", lambda: system)
    monkeypatch.setattr(os_utils.subprocess, "run", run)

    assert os_utils.open_folder(str(target)) is True
    run.assert_called_once_with([expected_command, str(target)])


def test_open_folder_swallows_launcher_failure(monkeypatch, tmp_path):
    """В headless-среде команды может не быть — падать из-за этого нельзя."""
    target = tmp_path / "tmplts"
    target.mkdir()

    def boom(*_args, **_kwargs):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(os_utils.platform, "system", lambda: "Linux")
    monkeypatch.setattr(os_utils.subprocess, "run", boom)

    assert os_utils.open_folder(str(target)) is False


def test_open_folder_real_subprocess_signature(monkeypatch, tmp_path):
    """Проверяем, что вызов действительно совместим с subprocess.run."""
    target = tmp_path / "tmplts"
    target.mkdir()
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(os_utils.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(os_utils.subprocess, "run", fake_run)

    assert os_utils.open_folder(str(target)) is True
    assert calls == [["open", str(target)]]
