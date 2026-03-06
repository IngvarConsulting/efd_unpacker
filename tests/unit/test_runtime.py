import subprocess
from types import SimpleNamespace

from efd_unpacker import runtime


def test_detect_system_language_defaults_to_english(monkeypatch):
    monkeypatch.setattr(runtime, "QLocale", None)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr(runtime.locale, "getlocale", lambda: ("en_US", "UTF-8"))

    assert runtime.detect_system_language() == "en"


def test_detect_system_language_returns_russian_for_russian_locale(monkeypatch):
    monkeypatch.setattr(runtime, "QLocale", None)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr(runtime.locale, "getlocale", lambda: ("ru_RU", "UTF-8"))

    assert runtime.detect_system_language() == "ru"


def test_resource_path_uses_project_root():
    path = runtime.resource_path("translations", "ru.ts")

    assert path.endswith("translations/ru.ts")


def test_detect_system_language_prefers_qt_locale(monkeypatch):
    class DummyQLocale:
        class Language:
            Russian = object()

        @staticmethod
        def system():
            return SimpleNamespace(language=lambda: DummyQLocale.Language.Russian)

    monkeypatch.setattr(runtime, "QLocale", DummyQLocale)

    assert runtime.detect_system_language() == "ru"


def test_resolve_cli_launcher_target_skips_macos_dmg_volume(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(
        runtime.sys,
        "executable",
        "/Volumes/EFD Unpacker/EFDUnpacker.app/Contents/MacOS/EFDUnpacker",
    )

    assert runtime.resolve_cli_launcher_target() is None


def test_install_cli_launcher_registers_macos_bundle(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(
        runtime.sys,
        "executable",
        "/Applications/EFDUnpacker.app/Contents/MacOS/EFDUnpacker",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    changed = runtime.install_cli_launcher()

    launcher_path = home / ".local" / "share" / "efd_unpacker" / "bin" / runtime.CLI_LAUNCHER_NAME
    profile_path = home / ".zprofile"
    profile_text = profile_path.read_text(encoding="utf-8")

    assert changed is True
    assert launcher_path.exists()
    assert "/Applications/EFDUnpacker.app/Contents/MacOS/EFDUnpacker" in launcher_path.read_text(
        encoding="utf-8"
    )
    assert runtime.CLI_PROFILE_START in profile_text
    assert 'EFD_UNPACKER_BIN="$HOME/.local/share/efd_unpacker/bin"' in profile_text
    assert "EFD_UNPACKER_TARGET=/Applications/EFDUnpacker.app/Contents/MacOS/EFDUnpacker" in profile_text
    assert 'if [ -x "$EFD_UNPACKER_BIN/efd_unpacker" ] && [ -x "$EFD_UNPACKER_TARGET" ]; then' in profile_text


def test_install_cli_launcher_registers_appimage(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    appimage_path = tmp_path / "EFD Unpacker.AppImage"
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", str(appimage_path))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    changed = runtime.install_cli_launcher()

    launcher_path = home / ".local" / "share" / "efd_unpacker" / "bin" / runtime.CLI_LAUNCHER_NAME
    profile_path = home / ".profile"
    profile_text = profile_path.read_text(encoding="utf-8")

    assert changed is True
    assert launcher_path.exists()
    assert f"TARGET='{appimage_path}'" in launcher_path.read_text(encoding="utf-8")
    assert f"EFD_UNPACKER_TARGET='{appimage_path}'" in profile_text
    assert 'EFD_UNPACKER_BIN="$HOME/.local/share/efd_unpacker/bin"' in profile_text


def test_install_cli_launcher_does_not_override_unmanaged_launcher(monkeypatch, tmp_path):
    home = tmp_path / "home"
    launcher_dir = home / ".local" / "share" / "efd_unpacker" / "bin"
    launcher_dir.mkdir(parents=True)
    launcher_path = launcher_dir / runtime.CLI_LAUNCHER_NAME
    launcher_path.write_text("#!/bin/sh\nexec /custom/efd_unpacker \"$@\"\n", encoding="utf-8")

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "efd-unpacker.AppImage"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    runtime.install_cli_launcher()

    assert launcher_path.read_text(encoding="utf-8") == "#!/bin/sh\nexec /custom/efd_unpacker \"$@\"\n"


def test_get_shell_profile_path_uses_login_shell_when_env_is_missing(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setattr(runtime.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_shell="/bin/zsh"))

    assert runtime.get_shell_profile_path() == home / ".zprofile"


def test_get_shell_profile_path_falls_back_when_pwd_is_unavailable(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setattr(runtime, "pwd", None)

    assert runtime.get_shell_profile_path() == home / ".profile"


def test_install_cli_launcher_removes_legacy_profile_and_launcher(monkeypatch, tmp_path):
    home = tmp_path / "home"
    legacy_bin = home / ".local" / "bin"
    legacy_bin.mkdir(parents=True)
    legacy_launcher = legacy_bin / runtime.CLI_LAUNCHER_NAME
    legacy_launcher.write_text(
        "#!/bin/sh\n# Managed by EFD Unpacker\nexec /old/location \"$@\"\n",
        encoding="utf-8",
    )
    profile_path = home / ".profile"
    profile_path.write_text(
        '# Managed by EFD Unpacker\nexport PATH="$PATH:$HOME/.local/bin"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "efd-unpacker.AppImage"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/bash")

    runtime.install_cli_launcher()

    assert not legacy_launcher.exists()
    profile_text = profile_path.read_text(encoding="utf-8")
    assert 'export PATH="$PATH:$HOME/.local/bin"' not in profile_text
    assert runtime.CLI_PROFILE_START in profile_text


def test_cli_launcher_self_removes_when_target_is_missing(tmp_path):
    launcher_path = tmp_path / runtime.CLI_LAUNCHER_NAME
    launcher_path.write_text(
        runtime._cli_launcher_script(tmp_path / "missing.AppImage"),
        encoding="utf-8",
    )
    launcher_path.chmod(0o755)

    result = subprocess.run(
        [str(launcher_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 127
    assert not launcher_path.exists()
    assert "launcher was removed because the application is no longer available" in result.stderr
