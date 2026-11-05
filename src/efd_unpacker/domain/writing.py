"""
Правила безопасной записи файла на диск.

Общие для всех источников: записи .efd, файлы из zip и tar, содержимое .rar.
Раньше они жили в сервисе распаковки, и когда появился второй писатель —
исполнитель плана, — он их не унаследовал: файл уходил за пределы каталога
назначения через промежуточный симлинк, а `a.txt` и `./a.txt` молча затирали
друг друга. Один модуль на всех — чтобы третьего писателя это не ждало.
"""

from __future__ import annotations

import os
import stat
import sys
from contextlib import contextmanager
from typing import Iterator, List

from .errors import UnpackError, UnpackErrorCode

#: Предел длины пути в Windows без длинных путей (MAX_PATH, вместе с
#: завершающим нулём). Включены ли длинные пути, Python заранее не скажет,
#: поэтому это лишь подсказка в сообщении, а не запрет.
WINDOWS_MAX_PATH = 260

_UMASK = os.umask(0)
os.umask(_UMASK)
DEFAULT_FILE_MODE = 0o644 & ~_UMASK


def resolve_entry_path(output_root: str, src_path: str, parts: List[str]) -> str:
    """
    Возвращает путь записи внутри output_root или поднимает UnpackError.

    Проверка идёт через commonpath, а не через startswith: строковый префикс
    считает `/tmp/out2` находящимся внутри `/tmp/out`. realpath дополнительно
    закрывает случай, когда промежуточный каталог оказался симлинком наружу.
    """
    target = os.path.join(output_root, *parts)

    try:
        if os.path.commonpath([output_root, os.path.realpath(target)]) != output_root:
            raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path})
    except ValueError as exc:
        # Разные диски на Windows или смесь абсолютного и относительного пути.
        raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path}) from exc

    return target


def reject_conflicting_entries(src_paths: List[str], parts_list: List[List[str]]) -> None:
    """
    Отвергает архив, в котором записи затирают друг друга.

    Без этой проверки дубль имени молча терял первую запись, а имя, совпадающее
    с каталогом соседней записи, роняло распаковку на середине с FileExistsError
    из недр os.makedirs — то есть с сообщением «Неожиданная ошибка».

    Ключи строятся из тех же компонентов, что и целевой путь, а не из сырого
    имени: иначе `a.txt` и `./a.txt` считались бы разными записями и вторая
    молча перезаписала бы первую.

    Сравнение регистронезависимое: на APFS и NTFS `README.txt` и `readme.txt` —
    один и тот же файл.
    """
    keys = ["/".join(parts).casefold() for parts in parts_list]

    seen = set()
    for key, src_path in zip(keys, src_paths):
        if key in seen:
            raise UnpackError(
                UnpackErrorCode.CORRUPTED_ARCHIVE,
                {"reason": "duplicate_entry", "entry": src_path},
            )
        seen.add(key)

    for key, src_path in zip(keys, src_paths):
        components = key.split("/")
        for depth in range(1, len(components)):
            if "/".join(components[:depth]) in seen:
                raise UnpackError(
                    UnpackErrorCode.CORRUPTED_ARCHIVE,
                    {"reason": "entry_is_also_directory", "entry": src_path},
                )


def apply_file_mode(temporary: str, path: str) -> None:
    """
    Выставляет режим временному файлу перед подстановкой на место цели.

    mkstemp создаёт файл с 0600, и os.replace переносит этот режим на цель.
    Если цель уже существует обычным файлом — сохраняем её режим, как делала
    прежняя запись поверх; иначе берём обычные права для новых файлов.
    lstat, а не stat: у симлинка режим брать нельзя.
    """
    mode = DEFAULT_FILE_MODE
    try:
        existing = os.lstat(path)
        if stat.S_ISREG(existing.st_mode):
            mode = stat.S_IMODE(existing.st_mode)
    except OSError:
        pass

    try:
        os.chmod(temporary, mode)
    except OSError:
        # На Windows chmod умеет немногое; права — не повод валить распаковку.
        pass


def write_failure(path: str, exc: OSError) -> UnpackError:
    """
    Отказ записи файла назначения в доменных терминах.

    Причина берётся из самой ОС, а длинный путь называется отдельно: Windows
    отвечает на него «системе не удаётся найти путь», и без подсказки человек
    ищет пропавший файл, а не длину пути.
    """
    absolute = os.path.abspath(path)
    return UnpackError(
        UnpackErrorCode.WRITE_FAILED,
        {
            "path": absolute,
            "error": exc.strerror or str(exc) or type(exc).__name__,
            "long_path": sys.platform == "win32" and len(absolute) >= WINDOWS_MAX_PATH,
        },
    )


@contextmanager
def writing_to(path: str) -> Iterator[None]:
    """Переводит отказ ОС при записи `path` в WRITE_FAILED."""
    try:
        yield
    except OSError as exc:
        raise write_failure(path, exc) from exc
