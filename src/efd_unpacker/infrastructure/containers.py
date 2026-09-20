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

import io
import lzma
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import BinaryIO, Callable, Iterator, List, Optional, Sequence, Tuple

from ..domain.errors import UnpackError, UnpackErrorCode
from ..domain.supply import safe_relative_parts
from . import rar

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

    if kind == "rar":
        yield from _rar_leaves(path, name)
        return

    yield from _descend(lambda: open(path, "rb"), (name,), kind, max_depth)


def _rar_leaves(path: str, name: str) -> Iterator[Leaf]:
    """
    Записи .rar через внешнюю программу.

    Только на верхнем уровне: программа принимает путь к файлу, а не поток, и
    у вложенного в zip архива пути нет. Все двенадцать дистрибутивов платформы
    под Windows лежат отдельными .rar, так что на деле это ничего не стоит.

    Во вложенные контейнеры внутри .rar не спускаемся: чтобы узнать вид каждой
    записи, пришлось бы её извлечь, а у solid-архива это полный проход по
    архиву на каждую запись. Настоящие дистрибутивы плоские — 44 файла
    .msi/.exe/.ini/.cab.
    """
    tool, entries = rar.read_entries(path)
    _check_count(len(entries), (name,))
    for entry in entries:
        if entry.link:
            # Символьная ссылка содержимым архива не является, а распакованная
            # ссылка на файл хозяина открылась бы обычным open как запись
            # архива — проверено, читался файл за пределами временного
            # каталога. То же самое уже ловилось для образов .dmg.
            continue
        # Имя проверено и в read_entries; здесь — второй раз, потому что это
        # последняя точка перед тем, как оно станет путём.
        safe_relative_parts(entry.name)
        yield Leaf(
            trail=(name, entry.name),
            size=entry.size,
            opener=_rar_opener(tool, path, entry),
        )


def _rar_opener(tool, archive: str, entry) -> Callable[[], BinaryIO]:
    """
    Поток одной записи: извлекаем её во временный каталог и отдаём файл.

    Программа и запись фиксируются здесь, в момент создания листа: размер в
    Leaf объявила эта программа, и наполнять лист должна она же.

    Каталог удаляется при закрытии потока — тем же механизмом владения, что у
    вложенных архивов, поэтому дескриптор и временные файлы не ждут сборщика.
    """

    def open_entry() -> BinaryIO:
        probe = tempfile.mkdtemp(prefix="efd-rar-entry-")
        try:
            if not rar.extract_entry(tool, archive, probe, entry):
                raise UnpackError(
                    UnpackErrorCode.CORRUPTED_ARCHIVE,
                    {"reason": "broken_container", "entry": entry.name},
                )
            # extract_entry уже убедился, что это обычный файл внутри probe;
            # открываем ровно тот путь, который он проверил.
            handle = open(os.path.join(probe, *entry.name.split("/")), "rb")
        except BaseException:
            shutil.rmtree(probe, ignore_errors=True)
            raise
        return _OwnedStream(handle, _Removable(probe))

    return open_entry


class _Removable:
    """Временный каталог, живущий ровно столько, сколько открытый поток."""

    def __init__(self, path: str) -> None:
        self._path = path

    def close(self) -> None:
        shutil.rmtree(self._path, ignore_errors=True)


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


#: Отказы разборщиков, которые означают «файл повреждён», а не ошибку в коде.
_BROKEN = (zipfile.BadZipFile, tarfile.ReadError, zlib.error, lzma.LZMAError, EOFError)


def _entries(
    opener: Callable[[], BinaryIO], trail: Tuple[str, ...], kind: str
) -> List[Tuple[str, int, bytes, Callable[[], BinaryIO]]]:
    try:
        if kind == "zip":
            return _zip_entries(opener, trail)
        if kind in ("tar", "tar.gz", "tar.bz2", "tar.xz"):
            return _tar_entries(opener, trail)
    except _BROKEN as exc:
        # Недокачанный архив — обычное дело, и выглядеть он должен как порча
        # файла, а не как BadZipFile наружу.
        raise UnpackError(
            UnpackErrorCode.CORRUPTED_ARCHIVE,
            {"reason": "broken_container", "entry": " → ".join(trail), "error": str(exc)},
        ) from exc
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
    source = opener()
    heads = []
    try:
        with zipfile.ZipFile(source) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            _check_count(len(infos), trail)
            for info in infos:
                with archive.open(info) as entry:
                    heads.append(entry.read(_PROBE_SIZE))
    finally:
        source.close()

    def make(info: zipfile.ZipInfo) -> Callable[[], BinaryIO]:
        def open_entry() -> BinaryIO:
            # Открываем по самой записи, а не по имени: в zip допустимы
            # одинаковые имена, и открытие по имени отдавало бы последнюю
            # запись под видом первой — с чужим размером и содержимым.
            nested = opener()
            archive = zipfile.ZipFile(nested)
            return _OwnedStream(archive.open(info), archive, nested)

        return open_entry

    return [
        (info.filename, info.file_size, head, make(info))
        for info, head in zip(infos, heads)
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
    members: List[tarfile.TarInfo] = []
    heads: List[bytes] = []
    source = opener()
    try:
        with tarfile.open(fileobj=source, mode="r:*") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                members.append(member)
                _check_count(len(members), trail)
                handle = archive.extractfile(member)
                heads.append(handle.read(_PROBE_SIZE) if handle is not None else b"")
    finally:
        source.close()

    def make(member: tarfile.TarInfo) -> Callable[[], BinaryIO]:
        def open_entry() -> BinaryIO:
            # По самой записи, а не по имени: одинаковые имена в tar допустимы.
            nested = opener()
            archive = tarfile.open(fileobj=nested, mode="r:*")
            handle = archive.extractfile(member)
            if handle is None:  # pragma: no cover - isfile уже отфильтровал
                archive.close()
                nested.close()
                raise UnpackError(
                    UnpackErrorCode.CORRUPTED_ARCHIVE,
                    {"reason": "truncated_entry", "entry": member.name},
                )
            return _OwnedStream(handle, archive, nested)

        return open_entry

    return [
        (member.name, member.size, head, make(member))
        for member, head in zip(members, heads)
    ]


class _OwnedStream(io.BufferedIOBase):
    """
    Поток записи, владеющий контейнером и исходным потоком.

    zipfile и tarfile не закрывают поток, который им передали, а подмена
    handle.close замыканием создавала ссылочный цикл: дескрипторы держались
    до сборки мусора. Измерено на 120 вложенных архивах — 5 дескрипторов
    превращались в 245.
    """

    def __init__(self, inner: BinaryIO, *owned) -> None:
        self._inner = inner
        self._owned = owned

    def read(self, size: int = -1) -> bytes:
        return self._inner.read(size)

    def read1(self, size: int = -1) -> bytes:
        reader = getattr(self._inner, "read1", None)
        return reader(size) if reader is not None else self._inner.read(size)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return self._inner.seekable()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._inner.seek(offset, whence)

    def tell(self) -> int:
        return self._inner.tell()

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            for resource in reversed(self._owned):
                try:
                    resource.close()
                except Exception:  # pragma: no cover - закрытие не должно мешать
                    pass


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
        root_real = os.path.realpath(mount_point)
        leaves = []
        for root, _dirs, files in os.walk(mount_point):
            for filename in sorted(files):
                full = os.path.join(root, filename)
                if not _inside(full, root_real):
                    # Симлинк из образа на файл хоста выдал бы /etc/hosts за
                    # содержимое архива. Проверено: os.walk отдаёт такую ссылку
                    # как обычный файл, а getsize и чтение идут по ней.
                    continue
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


def _inside(path: str, root_real: str) -> bool:
    """Лежит ли файл внутри смонтированного образа, а не за его пределами."""
    if os.path.islink(path):
        return False
    try:
        return os.path.commonpath([root_real, os.path.realpath(path)]) == root_real
    except ValueError:  # pragma: no cover - разные тома на Windows
        return False


def _file_opener(path: str) -> Callable[[], BinaryIO]:
    """Поток файла на смонтированном образе. Действителен, пока образ подключён."""
    return lambda: open(path, "rb")
