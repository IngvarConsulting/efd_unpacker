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


@pytest.mark.parametrize(
    "encoding",
    ["utf-16", "utf-16-le", "utf-16-be", "utf-16-le-bom", "utf-16-be-bom"],
    ids=["utf-16+BOM", "utf-16le без BOM", "utf-16be без BOM", "utf-16le с BOM", "utf-16be с BOM"],
)
def test_cfg_utf16_in_every_shape(tmp_path, monkeypatch, encoding):
    """
    Регресс #18: utf-16le не снимает BOM, а \ufeff не пробельный, поэтому первая
    строка не проходила проверку префикса. Без BOM файл вообще не доходил до
    своей ветки: байты UTF-16LE для ASCII валидны как UTF-8, и utf-8-sig
    отрабатывал первым, ничего не находил и обрывал перебор.
    """
    if encoding.endswith("-bom"):
        base = encoding[: -len("-bom")]
        payload = (b"\xff\xfe" if base.endswith("le") else b"\xfe\xff") + (
            CONFIG_LINE + "\r\n"
        ).encode(base)
    else:
        payload = (CONFIG_LINE + "\r\n").encode(encoding)
    _write_config(tmp_path, monkeypatch, payload)

    assert os_utils.get_1c_configuration_location_from_1cestart() == ["/opt/1c/tmplts"]


def test_cfg_cp1251_with_even_length_is_parsed(tmp_path, monkeypatch):
    """
    Регресс #18: чётная длина уводила файл в utf-16le, который декодирует любую
    последовательность без исключения. Разбор cp1251 работал через раз —
    в зависимости от чётности размера файла.
    """
    payload = "ConfigurationTemplatesLocation=/opt/Шаблоныx\r\n".encode("cp1251")
    assert len(payload) % 2 == 0
    _write_config(tmp_path, monkeypatch, payload)

    assert os_utils.get_1c_configuration_location_from_1cestart() == ["/opt/Шаблоныx"]


def test_cfg_large_cp1251_file_is_not_truncated(tmp_path, monkeypatch):
    """
    Регресс #18: locations накапливался между попытками, поэтому частично
    прочитанное под utf-8-sig оставалось, utf-16le доедал остаток и делал break.
    На файле из 251 строки возвращалось 174.
    """
    lines = []
    for index in range(251):
        suffix = "Шаблоны" if index == 230 else str(index)
        lines.append("ConfigurationTemplatesLocation=/opt/%s" % suffix)
    payload = ("\r\n".join(lines) + "\r\n").encode("cp1251")
    assert len(payload) > 8192
    _write_config(tmp_path, monkeypatch, payload)

    result = os_utils.get_1c_configuration_location_from_1cestart()

    assert len(result) == 251
    assert "/opt/Шаблоны" in result


def test_cfg_without_the_key_returns_empty(tmp_path, monkeypatch):
    """Файл без ключа — не повод перебирать кодировки до иероглифов."""
    _write_config(tmp_path, monkeypatch, "CommonInfoBases=x\r\n".encode("cp1251"))

    assert os_utils.get_1c_configuration_location_from_1cestart() == []


def test_cfg_unreadable_file_does_not_raise(tmp_path, monkeypatch):
    home = _write_config(tmp_path, monkeypatch, (CONFIG_LINE + "\n").encode("utf-8"))
    config = home / ".1C" / "1cestart" / "1cestart.cfg"
    os.chmod(config, 0o000)
    try:
        if os.access(config, os.R_OK):
            pytest.skip("права не отзываются на этой платформе")
        assert os_utils.get_1c_configuration_location_from_1cestart() == []
    finally:
        os.chmod(config, 0o644)


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


def _completed(returncode=0):
    """subprocess.run-заглушка, фиксирующая аргументы и отдающая заданный код."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode)

    return fake_run, calls


@pytest.mark.parametrize(
    "system, expected_command",
    [("Darwin", "open"), ("Linux", "xdg-open")],
)
def test_open_folder_uses_platform_command(monkeypatch, tmp_path, system, expected_command):
    target = tmp_path / "tmplts"
    target.mkdir()
    fake_run, calls = _completed()

    monkeypatch.setattr(os_utils.platform, "system", lambda: system)
    monkeypatch.setattr(os_utils.subprocess, "run", fake_run)

    assert os_utils.open_folder(str(target)) is True
    assert calls[0][0] == [expected_command, str(target)]


@pytest.mark.parametrize("returncode", [1, 3, 4], ids=["rc=1", "rc=3", "rc=4"])
def test_open_folder_reports_a_nonzero_exit_code(monkeypatch, tmp_path, returncode):
    """
    Регресс #18: код возврата не читался вообще. xdg-open отвечает 3 или 4,
    когда ассоциации inode/directory нет, а пользователь видел «открыл».
    """
    target = tmp_path / "tmplts"
    target.mkdir()
    fake_run, _calls = _completed(returncode)

    monkeypatch.setattr(os_utils.platform, "system", lambda: "Linux")
    monkeypatch.setattr(os_utils.subprocess, "run", fake_run)

    assert os_utils.open_folder(str(target)) is False


def test_open_folder_passes_a_relative_path_as_absolute(monkeypatch, tmp_path):
    """
    Путь, начинающийся с дефиса, не должен уехать в команду как опция.
    Разделитель "--" тут не годится: xdg-open его не понимает.
    """
    target = tmp_path / "-tmplts"
    target.mkdir()
    fake_run, calls = _completed()

    monkeypatch.setattr(os_utils.platform, "system", lambda: "Linux")
    monkeypatch.setattr(os_utils.subprocess, "run", fake_run)

    assert os_utils.open_folder(str(target)) is True
    # Именно isabs, а не startswith(os.sep): на Windows абсолютный путь
    # начинается с буквы диска, и проверка по разделителю там всегда ложна.
    assert os.path.isabs(calls[0][0][1])
    assert "--" not in calls[0][0]


def test_open_folder_restores_the_library_path_for_the_child(monkeypatch, tmp_path):
    """
    Регресс #18: дочерний процесс наследовал LD_LIBRARY_PATH бутлоадера
    PyInstaller и подхватывал Qt из каталога распаковки вместо системного.
    """
    target = tmp_path / "tmplts"
    target.mkdir()
    fake_run, calls = _completed()

    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxxxxxx")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/x86_64-linux-gnu")
    monkeypatch.setattr(os_utils.platform, "system", lambda: "Linux")
    monkeypatch.setattr(os_utils.subprocess, "run", fake_run)

    os_utils.open_folder(str(target))

    env = calls[0][1]["env"]
    assert env["LD_LIBRARY_PATH"] == "/usr/lib/x86_64-linux-gnu"
    assert "LD_LIBRARY_PATH_ORIG" not in env


def test_child_environment_drops_the_library_path_without_an_original(monkeypatch):
    """Если ORIG нет, ключ надо убрать, а не оставить путь бутлоадера."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxxxxxx")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    env = os_utils.child_environment()

    assert "LD_LIBRARY_PATH" not in env


def test_child_environment_keeps_the_rest_of_the_environment(monkeypatch):
    monkeypatch.setenv("SOME_MARKER", "значение")

    assert os_utils.child_environment()["SOME_MARKER"] == "значение"


def test_open_folder_swallows_launcher_failure(monkeypatch, tmp_path):
    """В headless-среде команды может не быть — падать из-за этого нельзя."""
    target = tmp_path / "tmplts"
    target.mkdir()

    def boom(*_args, **_kwargs):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(os_utils.platform, "system", lambda: "Linux")
    monkeypatch.setattr(os_utils.subprocess, "run", boom)

    assert os_utils.open_folder(str(target)) is False




@pytest.mark.parametrize(
    "templates_root, expected",
    [
        # Ожидания через normpath: функция возвращает канонический путь, то есть
        # с разделителями системы. На Windows "/a/b" превращается в "\\a\\b", и
        # собранное вручную ожидание из смеси разделителей сравнивало бы не то.
        (os.path.join("/a", "b", "tmplts"), os.path.normpath("/a/b/dist")),
        # normpath убирает «./» — путь тот же, запись короче.
        (os.path.join(".", "tmplts"), "dist"),
        # Корень файловой системы: без normpath получался относительный «dist».
        (os.sep, os.path.join(os.sep, "dist")),
        # Относительный корень из одной части: откат на сам templates_root
        # давал «tmplts/dist» — каталог ВНУТРИ шаблонов вместо соседа.
        ("tmplts", "dist"),
        ("tmplts/", "dist"),
    ],
)
def test_distributions_root_is_a_sibling_of_the_templates_root(templates_root, expected):
    assert os_utils.get_distributions_location_default(templates_root) == expected


@pytest.mark.skipif(os.name != "nt", reason="разбор путей Windows")
def test_windows_drive_root_gets_dist_at_the_root():
    """
    Регресс: у "C:\\" после срезки разделителей остаётся "C:", а dirname("C:")
    снова даёт "C:" — получался относительный "C:dist", то есть каталог в
    ТЕКУЩЕМ каталоге диска C, молча не там.
    """
    assert os_utils.get_distributions_location_default("C:\\") == "C:\\dist"
    assert os_utils.get_distributions_location_default("C:\\1C\\tmplts") == "C:\\1C\\dist"
