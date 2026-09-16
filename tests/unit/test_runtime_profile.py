"""
Регрессионные тесты записи в shell-профиль пользователя.

install_cli_launcher() вызывается при каждом запуске приложения и правит
файлы, которые приложению не принадлежат. Цена ошибки здесь — потеря
пользовательских настроек, поэтому сценарии проверяются отдельно.
"""

import os
import stat
import subprocess

import pytest

from efd_unpacker import runtime

pytestmark = pytest.mark.skipif(os.name == "nt", reason="shell-профили есть только на POSIX")


def _setup_linux_appimage(monkeypatch, tmp_path, shell="/bin/bash"):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(runtime.Path, "home", classmethod(lambda cls: home))
    appimage = tmp_path / "EFD Unpacker.AppImage"
    appimage.write_text("#!/bin/sh\n", encoding="utf-8")
    appimage.chmod(0o755)
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", str(appimage))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", shell)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    return home


def test_orphan_start_marker_keeps_user_lines(monkeypatch, tmp_path):
    """
    Регулярка с DOTALL хватала всё от осиротевшего START до END следующего
    блока, унося пользовательские строки между ними.
    """
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    profile = home / ".profile"
    profile.write_text(
        f"{runtime.CLI_PROFILE_START}\n"
        "export AWS_PROFILE=prod\n"
        "alias gs='git status'\n",
        encoding="utf-8",
    )

    runtime.install_cli_launcher()
    runtime.install_cli_launcher()

    text = profile.read_text(encoding="utf-8")
    assert "export AWS_PROFILE=prod" in text
    assert "alias gs='git status'" in text
    assert text.count(runtime.CLI_PROFILE_START) == 1


def test_repeated_runs_do_not_grow_the_profile(monkeypatch, tmp_path):
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    profile = home / ".profile"
    profile.write_text("export EDITOR=vim\n", encoding="utf-8")

    runtime.install_cli_launcher()
    first = profile.read_text(encoding="utf-8")
    runtime.install_cli_launcher()
    second = profile.read_text(encoding="utf-8")

    assert first == second
    assert first.count(runtime.CLI_PROFILE_START) == 1
    assert "export EDITOR=vim" in first


def test_cp1251_profile_does_not_raise(monkeypatch, tmp_path):
    """Профиль в cp1251 с русскими комментариями ронял запуск приложения."""
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    profile = home / ".profile"
    profile.write_bytes("# мой профиль\nexport EDITOR=vim\n".encode("cp1251"))
    original = profile.read_bytes()

    assert runtime.install_cli_launcher() is False
    assert profile.read_bytes() == original


def test_symlinked_profile_stays_a_symlink(monkeypatch, tmp_path):
    """os.replace по симлинку отцепил бы профиль от dotfiles-репозитория."""
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "profile"
    real.write_text("export EDITOR=vim\n", encoding="utf-8")
    real.chmod(0o600)
    mode_before = stat.S_IMODE(real.stat().st_mode)

    profile = home / ".profile"
    profile.symlink_to(real)

    runtime.install_cli_launcher()

    assert profile.is_symlink()
    assert profile.resolve() == real.resolve()
    assert stat.S_IMODE(real.stat().st_mode) == mode_before
    assert runtime.CLI_PROFILE_START in real.read_text(encoding="utf-8")


def test_backup_is_created_once(monkeypatch, tmp_path):
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    profile = home / ".profile"
    profile.write_text("export EDITOR=vim\n", encoding="utf-8")

    runtime.install_cli_launcher()
    backup = home / (".profile" + runtime.PROFILE_BACKUP_SUFFIX)

    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "export EDITOR=vim\n"

    backup.write_text("SENTINEL\n", encoding="utf-8")
    runtime.install_cli_launcher()
    assert backup.read_text(encoding="utf-8") == "SENTINEL\n"


def test_self_referencing_symlink_launcher_is_left_alone(monkeypatch, tmp_path):
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    launcher_dir = home / ".local" / "share" / "efd_unpacker" / "bin"
    launcher_dir.mkdir(parents=True)
    launcher = launcher_dir / runtime.CLI_LAUNCHER_NAME
    launcher.symlink_to(launcher)

    runtime.install_cli_launcher()

    assert launcher.is_symlink()


def test_empty_launcher_is_repaired(monkeypatch, tmp_path):
    """Пустой файл остаётся после обрыва записи — чинить его было нечем."""
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    launcher_dir = home / ".local" / "share" / "efd_unpacker" / "bin"
    launcher_dir.mkdir(parents=True)
    launcher = launcher_dir / runtime.CLI_LAUNCHER_NAME
    launcher.write_text("", encoding="utf-8")

    runtime.install_cli_launcher()

    assert runtime.CLI_LAUNCHER_MARKER in launcher.read_text(encoding="utf-8")


def test_generated_profile_is_valid_sh_for_hostile_paths(monkeypatch, tmp_path):
    """Путь с кавычкой и $(...) ломал синтаксис профиля."""
    home = tmp_path / 'ho"me$(id)'
    home.mkdir()
    monkeypatch.setattr(runtime.Path, "home", classmethod(lambda cls: home))
    appimage = tmp_path / "app.AppImage"
    appimage.write_text("#!/bin/sh\n", encoding="utf-8")
    appimage.chmod(0o755)
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", str(appimage))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    runtime.install_cli_launcher()
    profile = home / ".profile"

    assert subprocess.run(["sh", "-n", str(profile)], capture_output=True).returncode == 0

    result = subprocess.run(
        ["sh", "-c", f'HOME={str(home)!r}; export HOME; . {str(profile)!r}; echo "$PATH"'],
        capture_output=True,
        text=True,
    )
    expected = home / ".local" / "share" / "efd_unpacker" / "bin"
    assert str(expected) in result.stdout


def test_zsh_gets_both_zprofile_and_zshrc(monkeypatch, tmp_path):
    """В обычном (не login) терминале читается только rc-файл."""
    home = _setup_linux_appimage(monkeypatch, tmp_path, shell="/bin/zsh")
    monkeypatch.delenv("ZDOTDIR", raising=False)

    runtime.install_cli_launcher()

    for name in (".zprofile", ".zshrc"):
        assert runtime.CLI_PROFILE_START in (home / name).read_text(encoding="utf-8"), name


def test_zdotdir_is_respected(monkeypatch, tmp_path):
    home = _setup_linux_appimage(monkeypatch, tmp_path, shell="/bin/zsh")
    zdotdir = tmp_path / "zdot"
    zdotdir.mkdir()
    monkeypatch.setenv("ZDOTDIR", str(zdotdir))

    runtime.install_cli_launcher()

    assert runtime.CLI_PROFILE_START in (zdotdir / ".zprofile").read_text(encoding="utf-8")
    assert not (home / ".zprofile").exists()


def test_bash_gets_bashrc_too(monkeypatch, tmp_path):
    home = _setup_linux_appimage(monkeypatch, tmp_path, shell="/bin/bash")

    runtime.install_cli_launcher()

    assert runtime.CLI_PROFILE_START in (home / ".profile").read_text(encoding="utf-8")
    assert runtime.CLI_PROFILE_START in (home / ".bashrc").read_text(encoding="utf-8")


def test_python_outside_bundle_is_not_registered_on_macos(monkeypatch, tmp_path):
    """Любой интерпретатор внутри чужого .app раньше проходил проверку."""
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        runtime.sys, "executable",
        "/Library/Frameworks/Python.framework/Versions/3.11/Resources/Python.app/Contents/MacOS/Python",
    )

    assert runtime.resolve_cli_launcher_target() is None


def test_unfrozen_interpreter_is_not_registered_on_macos(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.delattr(runtime.sys, "frozen", raising=False)
    monkeypatch.setattr(
        runtime.sys, "executable",
        "/Applications/EFDUnpacker.app/Contents/MacOS/EFDUnpacker",
    )

    assert runtime.resolve_cli_launcher_target() is None


def test_read_only_profile_is_left_untouched(monkeypatch, tmp_path):
    """
    os.replace проверяет права на каталог, а не на файл, поэтому профиль,
    намеренно оставленный только для чтения, переписывался бы молча.
    """
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    profile = home / ".profile"
    profile.write_text("export EDITOR=vim\n", encoding="utf-8")
    profile.chmod(0o444)
    before = profile.read_text(encoding="utf-8")

    runtime.install_cli_launcher()

    assert profile.read_text(encoding="utf-8") == before
    assert stat.S_IMODE(profile.stat().st_mode) == 0o444
    assert not (home / (".profile" + runtime.PROFILE_BACKUP_SUFFIX)).exists()


def test_read_only_profile_does_not_block_the_other_file(monkeypatch, tmp_path):
    """Недоступный login-профиль не должен отменять запись в rc-файл."""
    home = _setup_linux_appimage(monkeypatch, tmp_path, shell="/bin/bash")
    profile = home / ".profile"
    profile.write_text("export EDITOR=vim\n", encoding="utf-8")
    profile.chmod(0o444)

    runtime.install_cli_launcher()

    assert runtime.CLI_PROFILE_START not in profile.read_text(encoding="utf-8")
    assert runtime.CLI_PROFILE_START in (home / ".bashrc").read_text(encoding="utf-8")


def test_hard_linked_profile_keeps_its_inode(monkeypatch, tmp_path):
    """os.replace создал бы новый inode и молча разорвал связь с dotfiles."""
    home = _setup_linux_appimage(monkeypatch, tmp_path)
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    shared = dotfiles / "profile"
    shared.write_text("export EDITOR=vim\n", encoding="utf-8")

    profile = home / ".profile"
    os.link(shared, profile)
    inode_before = profile.stat().st_ino

    runtime.install_cli_launcher()

    assert profile.stat().st_ino == inode_before
    assert profile.stat().st_nlink == 2
    assert shared.stat().st_ino == inode_before
    # Правка видна через обе ссылки, а пользовательская строка на месте.
    text = shared.read_text(encoding="utf-8")
    assert runtime.CLI_PROFILE_START in text
    assert "export EDITOR=vim" in text
