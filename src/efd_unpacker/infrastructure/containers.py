"""
Чтение контейнеров и рекурсивный спуск до содержимого.

Дистрибутивы 1С приходят не голыми .efd. Разбор пятнадцати файлов,
скачанных с releases.1c.ru:

    *_setup1c.zip        zip → 1cv8.efd в корне
    demo.zip             zip → demo_1_0_41_3.zip → 1cv8.efd     два уровня
    server64_*.zip       zip → setup-full-8.3.27.2342-x86_64.run
    deb64_*.zip          zip → 7 пакетов .deb
    postgresql_*.tar.bz2 tar.bz2 → 8 пакетов .deb
    macos.client_*.dmg   dmg → 1cv8-client-8.5.1.1529.pkg

Контейнер и вид — разные вещи: deb64_*.zip и postgresql_*.tar.bz2 несут одно
и то же в разных обёртках. Здесь снимается обёртка; что внутри — решает
слой выше.

Вид определяется по сигнатуре, а не по расширению. На одной странице релиза
платформы 8.3.27 имена следуют четырём несовместимым соглашениям, а demo.zip
вообще не содержит версии, так что именам доверия нет.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import BinaryIO, Callable, Iterator, List, Optional, Sequence, Tuple

from ..domain.errors import UnpackError, UnpackErrorCode
from ..domain.supply import safe_relative_parts

# Предел вложенности. Наблюдали два уровня (demo.zip), запас — один.
MAX_DEPTH = 3

# Потолок на число записей в одном контейнере: защита от архива, который
# состоит из миллиона пустых файлов. Самый населённый из исследованных —
# 83 записи внутри .efd и 37 внутри server64_*.zip.
MAX_ENTRIES = 50_000

# Сигнатуры. tar опознаётся по «ustar» со смещения 257, остальное — по началу.
_MAGIC: Sequence[Tuple[bytes, str]] = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),
    (b"\x1f\x8b", "tar.gz"),
    (b"BZh", "tar.bz2"),
    (b"\xfd7zXZ\x00", "tar.xz"),
    (b"Rar!\x1a\x07", "rar"),
)
_TAR_MAGIC_OFFSET = 257
_PROBE_SIZE = 512


@dataclass(frozen=True)
class Leaf:
    """Файл, найденный внутри контейнеров. Сам контейнером не является."""

    trail: Tuple[str, ...]
    size: int
    opener: Callable[[], BinaryIO]

    @property
    def name(self) -> str:
        return self.trail[-1]

    @property
    def display_path(self) -> str:
        return " → ".join(self.trail)


def detect_kind(head: bytes) -> Optional[str]:
    """
    Вид контейнера по сигнатуре. None — не контейнер.

    Отдельно про tar: у него нет сигнатуры в начале, поэтому проверяется
    «ustar» со смещения 257.
    """
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    if head[_TAR_MAGIC_OFFSET : _TAR_MAGIC_OFFSET + 5] == b"ustar":
        return "tar"
    return None


def walk(path: str, max_depth: int = MAX_DEPTH) -> Iterator[Leaf]:
    """
    Перечисляет файлы внутри контейнера, спускаясь во вложенные.

    Сам файл, если он не контейнер, отдаётся единственным листом — так
    вызывающему коду не нужно знать, архив перед ним или голый .efd.
    """
    with open(path, "rb") as handle:
        kind = detect_kind(handle.read(_PROBE_SIZE))
    name = os.path.basename(path)

    if kind is None:
        yield Leaf(trail=(name,), size=os.path.getsize(path), opener=lambda: open(path, "rb"))
        return

    yield from _descend(lambda: open(path, "rb"), (name,), kind, max_depth)


def _descend(
    opener: Callable[[], BinaryIO],
    trail: Tuple[str, ...],
    kind: str,
    depth_left: int,
) -> Iterator[Leaf]:
    if depth_left <= 0:
        raise UnpackError(
            UnpackErrorCode.NESTING_TOO_DEEP,
            {"entry": " → ".join(trail), "limit": MAX_DEPTH},
        )

    for name, size, head, child_opener in _entries(opener, trail, kind):
        # Имя из контейнера — такие же чужие данные, как имя записи .efd.
        # Без этого `../../etc/passwd` во вложенном архиве уехал бы в путь.
        safe_relative_parts(name)
        child_trail = trail + (name,)
        child_kind = detect_kind(head)

        if child_kind is None:
            yield Leaf(trail=child_trail, size=size, opener=child_opener)
        else:
            yield from _descend(child_opener, child_trail, child_kind, depth_left - 1)


def _entries(
    opener: Callable[[], BinaryIO], trail: Tuple[str, ...], kind: str
) -> List[Tuple[str, int, bytes, Callable[[], BinaryIO]]]:
    if kind == "zip":
        return _zip_entries(opener, trail)
    if kind in ("tar", "tar.gz", "tar.bz2", "tar.xz"):
        return _tar_entries(opener, trail)
    raise UnpackError(
        UnpackErrorCode.CONTAINER_UNSUPPORTED,
        {"entry": " → ".join(trail), "kind": kind},
    )


def _check_count(count: int, trail: Tuple[str, ...]) -> None:
    if count > MAX_ENTRIES:
        raise UnpackError(
            UnpackErrorCode.TOO_MANY_ENTRIES,
            {"entry": " → ".join(trail), "count": count, "limit": MAX_ENTRIES},
        )


def _zip_entries(
    opener: Callable[[], BinaryIO], trail: Tuple[str, ...]
) -> List[Tuple[str, int, bytes, Callable[[], BinaryIO]]]:
    """
    Записи zip. Вложенный архив открывается прямо из внешнего.

    ZipExtFile перематываемый, поэтому буферизовать вложенный zip целиком не
    нужно: demo_1_0_41_3.zip на 28 МБ открывается с пиком памяти в 16 МБ.
    """
    with zipfile.ZipFile(opener()) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        _check_count(len(infos), trail)
        heads = {}
        for info in infos:
            with archive.open(info) as entry:
                heads[info.filename] = entry.read(_PROBE_SIZE)

    def make(name: str) -> Callable[[], BinaryIO]:
        def open_entry() -> BinaryIO:
            # Свой ZipFile на каждое открытие: поток чтения нельзя делить
            # между потребителями, а закрывать чужой мы не вправе.
            archive = zipfile.ZipFile(opener())
            handle = archive.open(name)
            _close_with(handle, archive)
            return handle

        return open_entry

    return [
        (info.filename, info.file_size, heads[info.filename], make(info.filename))
        for info in infos
    ]


def _tar_entries(
    opener: Callable[[], BinaryIO], trail: Tuple[str, ...]
) -> List[Tuple[str, int, bytes, Callable[[], BinaryIO]]]:
    """
    Записи tar, включая сжатые варианты.

    В отличие от zip, tar читается только последовательно, поэтому сигнатуры
    снимаются за тот же единственный проход. Отдельный проход на каждую запись
    стоил 4.13 с на postgresql_*.tar.bz2 против 0.2 с сейчас.
    """
    sizes: List[Tuple[str, int]] = []
    heads = {}
    with tarfile.open(fileobj=opener(), mode="r:*") as archive:
        for member in archive:
            if not member.isfile():
                continue
            sizes.append((member.name, member.size))
            _check_count(len(sizes), trail)
            handle = archive.extractfile(member)
            heads[member.name] = handle.read(_PROBE_SIZE) if handle is not None else b""

    def make(name: str) -> Callable[[], BinaryIO]:
        def open_entry() -> BinaryIO:
            archive = tarfile.open(fileobj=opener(), mode="r:*")
            handle = archive.extractfile(name)
            if handle is None:  # pragma: no cover - getmembers уже отфильтровал
                raise UnpackError(
                    UnpackErrorCode.CORRUPTED_ARCHIVE,
                    {"reason": "truncated_entry", "entry": name},
                )
            _close_with(handle, archive)
            return handle

        return open_entry

    return [(name, size, heads[name], make(name)) for name, size in sizes]


def _close_with(handle: BinaryIO, archive) -> None:
    """Закрывает контейнер вместе с записью, чтобы не течь дескрипторами."""
    original = handle.close

    def close() -> None:
        try:
            original()
        finally:
            archive.close()

    handle.close = close  # type: ignore[method-assign]


def dmg_supported() -> bool:
    """Образы .dmg монтируются только на macOS."""
    return platform.system() == "Darwin" and shutil.which("hdiutil") is not None


@contextmanager
def open_dmg(path: str) -> Iterator[Tuple[Leaf, ...]]:
    """
    Монтирует .dmg только для чтения на время работы с ним.

    Именно контекстный менеджер, а не генератор: у смонтированного образа есть
    время жизни, и потоки его файлов действительны только пока он подключён.
    Генератор отцеплял образ в finally, и открыть файл после обхода уже не
    получалось — путь исчезал.

    Заглянуть внутрь без монтирования нельзя: hdiutil imageinfo содержимое не
    перечисляет. Поэтому на Linux и Windows этот вид честно не поддержан.
    """
    if not dmg_supported():
        raise UnpackError(
            UnpackErrorCode.CONTAINER_UNSUPPORTED,
            {"entry": os.path.basename(path), "kind": "dmg"},
        )

    mount_point = tempfile.mkdtemp(prefix="efd-dmg-")
    attached = False
    try:
        subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-readonly", "-noverify",
             "-mountpoint", mount_point, path],
            check=True, capture_output=True,
        )
        attached = True
        name = os.path.basename(path)
        leaves = []
        for root, _dirs, files in os.walk(mount_point):
            for filename in sorted(files):
                full = os.path.join(root, filename)
                leaves.append(
                    Leaf(
                        trail=(name, os.path.relpath(full, mount_point)),
                        size=os.path.getsize(full),
                        opener=_file_opener(full),
                    )
                )
        yield tuple(leaves)
    finally:
        if attached:
            subprocess.run(["hdiutil", "detach", mount_point, "-quiet"], capture_output=True)
        shutil.rmtree(mount_point, ignore_errors=True)


def _file_opener(path: str) -> Callable[[], BinaryIO]:
    """Поток файла на смонтированном образе. Действителен, пока образ подключён."""
    return lambda: open(path, "rb")
