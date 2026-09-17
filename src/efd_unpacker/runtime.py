"""
Runtime helpers for resources, locale and bundled CLI registration.
"""

from __future__ import annotations

import locale
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List

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
PROFILE_BACKUP_SUFFIX = ".efd-unpacker.bak"
MACOS_BUNDLE_NAME = "EFDUnpacker.app"

# Права на вновь создаваемый профиль, если его ещё не было. У существующего
# режим копируется как есть: профиль с 0600 не должен стать 0644.
_UMASK = os.umask(0)
os.umask(_UMASK)
DEFAULT_PROFILE_MODE = 0o644 & ~_UMASK


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
    profile_paths = get_shell_profile_paths()

    try:
        launcher_dir.mkdir(parents=True, exist_ok=True)
        changed = _write_cli_launcher(launcher_path, target)
        changed |= _remove_legacy_launcher()
        for profile_path in profile_paths:
            changed |= _ensure_shell_profile_exports_path(profile_path, launcher_dir, target)
            changed |= _cleanup_legacy_profile_block(profile_path)
    except (OSError, ValueError):
        # Профиль в неизвестной кодировке, недоступный каталог, симлинк в
        # никуда — регистрация CLI не должна мешать работе приложения.
        return False

    return changed


def resolve_cli_launcher_target() -> Path | None:
    """Return the stable executable path that should back the CLI launcher."""
    if sys.platform == "darwin":
        # Проверка по подстроке пути пропускала любой интерпретатор внутри
        # чужого .app (например framework-сборку Python): в PATH уезжал бы
        # launcher, указывающий не на наше приложение.
        if not getattr(sys, "frozen", False):
            return None

        executable = Path(sys.executable)
        executable_str = str(executable).replace("\\", "/")
        if executable_str.startswith("/Volumes/"):
            return None
        if ".app/Contents/MacOS/" not in executable_str:
            return None

        parents = executable.parents
        if len(parents) < 3 or parents[2].name != MACOS_BUNDLE_NAME:
            return None

        return executable.resolve(strict=False)

    if sys.platform.startswith("linux"):
        appimage = os.environ.get("APPIMAGE")
        if not appimage:
            return None
        return Path(appimage).expanduser().resolve(strict=False)

    return None


def get_cli_launcher_dir() -> Path:
    """Return the per-user directory used for CLI launcher registration."""
    return Path.home() / ".local" / "share" / "efd_unpacker" / "bin"


def get_shell_profile_paths() -> List[Path]:
    """
    Файлы профиля, в которые нужно дописать блок PATH.

    Login-профиля мало: gnome-terminal запускает zsh и bash не как login-shell,
    поэтому ~/.zprofile и ~/.bash_profile там не читаются, и команда
    `efd_unpacker` в обычном терминале не появлялась. Поэтому к login-файлу
    добавляется соответствующий rc-файл.
    """
    home = Path.home()
    shell_path = os.environ.get("SHELL", "")
    if not shell_path and pwd is not None and hasattr(os, "getuid"):
        try:
            shell_path = pwd.getpwuid(os.getuid()).pw_shell
        except KeyError:
            shell_path = ""
    if not shell_path:
        return [home / ".profile"]

    shell_name = Path(shell_path).name
    if shell_name == "zsh":
        zdotdir = Path(os.environ.get("ZDOTDIR") or home)
        return [zdotdir / ".zprofile", zdotdir / ".zshrc"]
    if shell_name == "bash":
        bash_profile = home / ".bash_profile"
        login_profile = bash_profile if bash_profile.exists() else home / ".profile"
        return [login_profile, home / ".bashrc"]
    return [home / ".profile"]


def get_shell_profile_path() -> Path:
    """Основной login-профиль текущего шелла."""
    return get_shell_profile_paths()[0]


def _is_profile_modifiable(real_path: Path) -> bool:
    """
    Можно ли трогать этот профиль.

    os.replace проверяет права на каталог, а не на сам файл, поэтому профиль,
    намеренно оставленный только для чтения, он переписал бы молча. Прежний
    write_text в этом случае падал с PermissionError, и регистрация тихо
    пропускалась — сохраняем то же поведение.
    """
    if not real_path.exists():
        return True
    return os.access(real_path, os.W_OK)


def _write_profile_text(profile_path: Path, text: str) -> None:
    """
    Записывает профиль, не ломая его связей с другими файлами.

    Прежний write_text обрезал файл до нуля перед записью, поэтому вторая
    копия приложения, стартовавшая в этот момент, читала пустой профиль и
    затирала его целиком. Обычный случай пишется атомарно через временный
    файл и os.replace; путь резолвится намеренно, иначе os.replace заменил бы
    сам симлинк обычным файлом и отцепил профиль от dotfiles-репозитория.
    """
    real_path = profile_path.resolve(strict=False)
    real_path.parent.mkdir(parents=True, exist_ok=True)

    if real_path.exists() and real_path.stat().st_nlink > 1:
        # Профиль — жёсткая ссылка (dotfiles-репозиторий, общий файл для
        # нескольких шеллов). os.replace создал бы новый inode и молча разорвал
        # связь: правки через вторую ссылку перестали бы доходить до активного
        # профиля. Пишем на месте; порядок write -> truncate оставляет файл
        # непустым в любой момент, в отличие от прежнего write_text.
        with open(real_path, "r+", encoding="utf-8") as handle:
            handle.seek(0)
            handle.write(text)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        return

    descriptor, temporary = tempfile.mkstemp(dir=str(real_path.parent), prefix=".efd-profile-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        if real_path.exists():
            shutil.copystat(real_path, temporary)
        else:
            os.chmod(temporary, DEFAULT_PROFILE_MODE)

        os.replace(temporary, real_path)
    finally:
        if os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _backup_profile_once(profile_path: Path) -> None:
    """Одноразовая копия профиля перед первой модификацией."""
    real_path = profile_path.resolve(strict=False)
    if not real_path.is_file():
        return

    backup = real_path.with_name(real_path.name + PROFILE_BACKUP_SUFFIX)
    if backup.exists():
        return

    try:
        shutil.copy2(real_path, backup)
    except OSError:
        # Без бэкапа обойдёмся, ронять регистрацию из-за него незачем.
        pass


def _ensure_shell_profile_exports_path(profile_path: Path, bin_dir: Path, target: Path) -> bool:
    real_path = profile_path.resolve(strict=False)
    if not _is_profile_modifiable(real_path):
        return False

    profile_text = real_path.read_text(encoding="utf-8") if real_path.is_file() else ""
    export_block = _shell_profile_export_block(bin_dir, target)
    sanitized_text = _remove_legacy_profile_block(_remove_managed_profile_block(profile_text))
    prefix = "\n" if sanitized_text and not sanitized_text.endswith("\n") else ""
    new_text = f"{sanitized_text}{prefix}{export_block}"

    if new_text == profile_text:
        return False

    _backup_profile_once(profile_path)
    _write_profile_text(profile_path, new_text)
    return True


def _shell_profile_export_block(bin_dir: Path, target: Path) -> str:
    bin_path = _shell_profile_path(bin_dir)
    target_path = shlex.quote(str(target.resolve(strict=False)))
    return (
        f"{CLI_PROFILE_START}\n"
        f"EFD_UNPACKER_BIN={bin_path}\n"
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
    """
    Правая часть присваивания EFD_UNPACKER_BIN, безопасная для sh.

    К домашней ветке shlex.quote применять нельзя целиком — тогда перестанет
    раскрываться $HOME, поэтому квотируется только относительный хвост.
    Раньше значение просто оборачивалось в двойные кавычки, и путь с " или
    $(...) ломал синтаксис профиля.
    """
    home = Path.home().resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        relative = resolved_path.relative_to(home)
    except ValueError:
        return shlex.quote(str(resolved_path))
    return '"$HOME"/' + shlex.quote(relative.as_posix())


def _write_cli_launcher(launcher_path: Path, target: Path) -> bool:
    script_content = _cli_launcher_script(target)

    if launcher_path.is_symlink():
        # Симлинк создавали не мы: и висячий, и рабочий оставляем как есть.
        return False

    if launcher_path.exists():
        current_content = launcher_path.read_text(encoding="utf-8")
        if current_content == script_content:
            launcher_path.chmod(0o755)
            return False
        if current_content and CLI_LAUNCHER_MARKER not in current_content:
            # Чужой непустой файл — не наш, не трогаем.
            return False
        # Либо наш устаревший, либо пустой: пустой остаётся после обрыва
        # записи и без перезаписи чинить его было нечем.

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


def _remove_legacy_launcher() -> bool:
    """Удаляет launcher из старого расположения ~/.local/bin."""
    legacy_launcher = Path.home() / ".local" / "bin" / CLI_LAUNCHER_NAME
    if legacy_launcher.is_symlink() or not legacy_launcher.exists():
        return False

    if CLI_LAUNCHER_MARKER not in legacy_launcher.read_text(encoding="utf-8"):
        return False

    legacy_launcher.unlink()
    return True


def _cleanup_legacy_profile_block(profile_path: Path) -> bool:
    real_path = profile_path.resolve(strict=False)
    if not real_path.is_file() or not _is_profile_modifiable(real_path):
        return False

    profile_text = real_path.read_text(encoding="utf-8")
    cleaned_text = _remove_legacy_profile_block(profile_text)
    if cleaned_text == profile_text:
        return False

    _backup_profile_once(profile_path)
    _write_profile_text(profile_path, cleaned_text)
    return True


def _remove_managed_profile_block(profile_text: str) -> str:
    """
    Убирает наш блок из профиля, построчно.

    Регулярка с DOTALL хватала всё от осиротевшего START до END следующего
    блока — вместе с пользовательскими строками между ними. Теперь поиск END
    прерывается на очередном START: незакрытый START удаляется как одна
    строка, а чужой текст остаётся на месте.
    """
    lines = profile_text.splitlines(keepends=True)
    kept: List[str] = []
    index = 0

    while index < len(lines):
        if lines[index].strip() != CLI_PROFILE_START:
            kept.append(lines[index])
            index += 1
            continue

        end = index + 1
        while end < len(lines) and lines[end].strip() not in (CLI_PROFILE_END, CLI_PROFILE_START):
            end += 1

        if end < len(lines) and lines[end].strip() == CLI_PROFILE_END:
            index = end + 1
        else:
            # Незакрытый START — выбрасываем только его собственную строку.
            index += 1

    return "".join(kept).lstrip("\n")


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
