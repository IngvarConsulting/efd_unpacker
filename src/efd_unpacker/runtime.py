"""
Runtime helpers for resources, locale and bundled CLI registration.
"""

from __future__ import annotations

import locale
import os
import re
import shlex
import sys
from pathlib import Path

try:
    import pwd
except ImportError:  # pragma: no cover - unavailable on Windows
    pwd = None  # type: ignore[assignment]

try:
    from PyQt5.QtCore import QLocale
except ImportError:  # pragma: no cover - PyQt5 is available in app runtime
    QLocale = None  # type: ignore[assignment]

CLI_LAUNCHER_NAME = "efd_unpacker"
CLI_LAUNCHER_MARKER = "# Managed by EFD Unpacker"
CLI_PROFILE_START = "# >>> EFD Unpacker PATH >>>"
CLI_PROFILE_END = "# <<< EFD Unpacker PATH <<<"


def _normalized_path_text(path: Path) -> str:
    """Return a path string with normalized separators for platform checks."""
    return str(path.resolve(strict=False)).replace("\\", "/")


def detect_system_language(default: str = "en") -> str:
    """Return `ru` for Russian systems, otherwise the provided default."""
    if QLocale is not None and QLocale.system().language() == QLocale.Language.Russian:
        return "ru"

    locale_name = (
        os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or locale.getlocale()[0]
        or ""
    ).lower()
    if locale_name.startswith("ru"):
        return "ru"
    return default


def resource_path(*parts: str) -> str:
    """Resolve a resource path for source checkout and PyInstaller bundles."""
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base_path = Path(__file__).resolve().parents[2]
    return str(base_path.joinpath(*parts))


def install_cli_launcher() -> bool:
    """
    Register `efd_unpacker` in the user's PATH for bundled DMG/AppImage builds.

    The launcher is installed into a managed user directory and the shell
    profile adds that directory to PATH only while both the launcher and its
    target application still exist.
    """
    target = resolve_cli_launcher_target()
    if target is None:
        return False

    launcher_dir = get_cli_launcher_dir()
    launcher_path = launcher_dir / CLI_LAUNCHER_NAME
    profile_path = get_shell_profile_path()

    try:
        launcher_dir.mkdir(parents=True, exist_ok=True)
        launcher_changed = _write_cli_launcher(launcher_path, target)
        profile_changed = _ensure_shell_profile_exports_path(profile_path, launcher_dir, target)
        legacy_changed = _cleanup_legacy_cli_registration(profile_path)
    except OSError:
        return False

    return launcher_changed or profile_changed or legacy_changed


def resolve_cli_launcher_target() -> Path | None:
    """Return the stable executable path that should back the CLI launcher."""
    if sys.platform == "darwin":
        executable = Path(sys.executable)
        executable_str = str(executable).replace("\\", "/")
        if executable_str.startswith("/Volumes/"):
            return None
        if ".app/Contents/MacOS/" in executable_str:
            return executable.resolve(strict=False)
        return None

    if sys.platform.startswith("linux"):
        appimage = os.environ.get("APPIMAGE")
        if not appimage:
            return None
        return Path(appimage).expanduser().resolve(strict=False)

    return None


def get_cli_launcher_dir() -> Path:
    """Return the per-user directory used for CLI launcher registration."""
    return Path.home() / ".local" / "share" / "efd_unpacker" / "bin"


def get_shell_profile_path() -> Path:
    """Return the most likely shell profile file for the current user shell."""
    home = Path.home()
    shell_path = os.environ.get("SHELL", "")
    if not shell_path:
        if pwd is not None and hasattr(os, "getuid"):
            shell_path = pwd.getpwuid(os.getuid()).pw_shell
        else:
            return home / ".profile"
    shell_name = Path(shell_path).name
    if shell_name == "zsh":
        return home / ".zprofile"
    if shell_name == "bash":
        bash_profile = home / ".bash_profile"
        return bash_profile if bash_profile.exists() else home / ".profile"
    return home / ".profile"


def _ensure_shell_profile_exports_path(profile_path: Path, bin_dir: Path, target: Path) -> bool:
    profile_text = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    export_block = _shell_profile_export_block(bin_dir, target)
    sanitized_text = _remove_legacy_profile_block(_remove_managed_profile_block(profile_text))
    prefix = "\n" if sanitized_text and not sanitized_text.endswith("\n") else ""
    new_text = f"{sanitized_text}{prefix}{export_block}"

    if new_text == profile_text:
        return False

    profile_path.write_text(new_text, encoding="utf-8")
    return True


def _shell_profile_export_block(bin_dir: Path, target: Path) -> str:
    bin_path = _shell_profile_path(bin_dir)
    target_path = shlex.quote(str(target.resolve(strict=False)))
    return (
        f"{CLI_PROFILE_START}\n"
        f'EFD_UNPACKER_BIN="{bin_path}"\n'
        f'EFD_UNPACKER_TARGET={target_path}\n'
        'if [ -x "$EFD_UNPACKER_BIN/efd_unpacker" ] && [ -x "$EFD_UNPACKER_TARGET" ]; then\n'
        '  case ":$PATH:" in\n'
        '    *":$EFD_UNPACKER_BIN:"*) ;;\n'
        '    *) export PATH="$PATH:$EFD_UNPACKER_BIN" ;;\n'
        "  esac\n"
        "fi\n"
        "unset EFD_UNPACKER_BIN EFD_UNPACKER_TARGET\n"
        f"{CLI_PROFILE_END}\n"
    )


def _shell_profile_path(path: Path) -> str:
    home = Path.home().resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        relative = resolved_path.relative_to(home)
    except ValueError:
        return str(resolved_path)
    return f"$HOME/{relative.as_posix()}"


def _write_cli_launcher(launcher_path: Path, target: Path) -> bool:
    script_content = _cli_launcher_script(target)

    if launcher_path.is_symlink():
        try:
            if launcher_path.resolve(strict=False) == target.resolve(strict=False):
                return False
        except OSError:
            pass
        return False

    if launcher_path.exists():
        current_content = launcher_path.read_text(encoding="utf-8")
        if CLI_LAUNCHER_MARKER not in current_content:
            return False
        if current_content == script_content:
            launcher_path.chmod(0o755)
            return False

    launcher_path.write_text(script_content, encoding="utf-8")
    launcher_path.chmod(0o755)
    return True


def _cli_launcher_script(target: Path) -> str:
    quoted_target = shlex.quote(str(target.resolve(strict=False)))
    return (
        "#!/bin/sh\n"
        f"{CLI_LAUNCHER_MARKER}\n"
        f"TARGET={quoted_target}\n"
        'if [ ! -x "$TARGET" ]; then\n'
        '  rm -f "$0"\n'
        '  echo "EFD Unpacker launcher was removed because the application is no longer available." >&2\n'
        "  exit 127\n"
        "fi\n"
        'exec "$TARGET" "$@"\n'
    )


def _cleanup_legacy_cli_registration(profile_path: Path) -> bool:
    changed = False
    legacy_launcher = Path.home() / ".local" / "bin" / CLI_LAUNCHER_NAME
    if legacy_launcher.exists() and not legacy_launcher.is_symlink():
        legacy_content = legacy_launcher.read_text(encoding="utf-8")
        if CLI_LAUNCHER_MARKER in legacy_content:
            legacy_launcher.unlink()
            changed = True

    if profile_path.exists():
        profile_text = profile_path.read_text(encoding="utf-8")
        cleaned_text = _remove_legacy_profile_block(profile_text)
        if cleaned_text != profile_text:
            profile_path.write_text(cleaned_text, encoding="utf-8")
            changed = True

    return changed


def _remove_managed_profile_block(profile_text: str) -> str:
    pattern = re.compile(
        rf"(?:^|\n){re.escape(CLI_PROFILE_START)}\n.*?{re.escape(CLI_PROFILE_END)}\n?",
        re.DOTALL,
    )
    return pattern.sub("\n", profile_text).lstrip("\n")


def _remove_legacy_profile_block(profile_text: str) -> str:
    lines = profile_text.splitlines(keepends=True)
    cleaned_lines: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if line.strip() == CLI_LAUNCHER_MARKER:
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if next_line.lstrip().startswith('export PATH="$PATH:'):
                index += 2
                continue
        cleaned_lines.append(line)
        index += 1

    return "".join(cleaned_lines).lstrip("\n")
