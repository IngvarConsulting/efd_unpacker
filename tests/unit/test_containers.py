"""
Тесты спуска по контейнерам.

Настоящие дистрибутивы в репозиторий не положить — гигабайты. Поэтому здесь
синтетические архивы той же формы, что встретилась на releases.1c.ru:
zip с .efd в корне, zip в zip, tar с пакетами внутри.
"""

import gc
import io
import os
import tarfile
import zipfile

import pytest

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.infrastructure import containers
from efd_unpacker.infrastructure.containers import (
    MAX_DEPTH,
    Leaf,
    detect_kind,
    dmg_supported,
    walk,
    open_dmg,
)
from tests.efd_builder import build_efd


def _zip_bytes(files, compress=False):
    buffer = io.BytesIO()
    method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", compression=method) as archive:
        for name, data in files:
            archive.writestr(name, data)
    return buffer.getvalue()


def _tar_bytes(files, mode="w:bz2"):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# --- опознание по сигнатуре --------------------------------------------------


@pytest.mark.parametrize(
    "head, expected",
    [
        (b"PK\x03\x04rest", "zip"),
        (b"\x1f\x8b\x08", "tar.gz"),
        (b"BZh9", "tar.bz2"),
        (b"\xfd7zXZ\x00", "tar.xz"),
        (b"Rar!\x1a\x07\x01\x00", "rar"),
        (b"just text", None),
        (b"", None),
    ],
)
def test_detect_kind_by_signature(head, expected):
    assert detect_kind(head) == expected


def test_tar_is_detected_by_the_ustar_marker():
    """У tar нет сигнатуры в начале — опознаётся по «ustar» со смещения 257."""
    assert detect_kind(_tar_bytes([("a.txt", b"x")], mode="w")) == "tar"


def test_extension_does_not_decide():
    """
    Имена на releases.1c.ru следуют четырём несовместимым соглашениям,
    а demo.zip вовсе не содержит версии. Решает только содержимое.
    """
    assert detect_kind(b"PK\x03\x04") == "zip"
    assert detect_kind(b"not an archive despite the name.zip") is None


# --- спуск -------------------------------------------------------------------


def test_plain_file_is_a_single_leaf(tmp_path):
    """Голый .efd проходит тем же путём, что и архив: вызывающему всё равно."""
    path = _write(tmp_path, "1cv8.efd", build_efd([("a\\b\\c.txt", b"payload")]))

    leaves = list(walk(path))

    assert [leaf.name for leaf in leaves] == ["1cv8.efd"]
    assert leaves[0].size == os.path.getsize(path)


def test_efd_inside_a_zip(tmp_path):
    path = _write(
        tmp_path, "setup1c.zip",
        _zip_bytes([("1cv8.efd", build_efd([("a\\b\\c.txt", b"x")])), ("ReadMe.txt", b"hi")]),
    )

    leaves = {leaf.name: leaf for leaf in walk(path)}

    assert set(leaves) == {"1cv8.efd", "ReadMe.txt"}
    assert leaves["1cv8.efd"].display_path == "setup1c.zip → 1cv8.efd"


def test_efd_two_levels_deep(tmp_path):
    """
    Форма demo.zip платформы 8.3.27 — она опровергла утверждение
    «.efd всегда в корне архива».
    """
    inner = _zip_bytes([("1cv8.efd", build_efd([("a\\b\\c.txt", b"x")]))])
    path = _write(tmp_path, "demo.zip", _zip_bytes([("VerInfo.txt", b"1.0.41.3"), ("demo_1_0_41_3.zip", inner)]))

    leaves = {leaf.display_path: leaf for leaf in walk(path)}

    assert "demo.zip → demo_1_0_41_3.zip → 1cv8.efd" in leaves
    assert "demo.zip → VerInfo.txt" in leaves


def test_nested_zip_is_read_without_buffering(tmp_path):
    """
    ZipExtFile перематываемый, поэтому вложенный архив открывается прямо из
    внешнего: demo_1_0_41_3.zip на 28 МБ обходится пиком памяти в 16 МБ.
    """
    payload = os.urandom(3 * 1024 * 1024)
    inner = _zip_bytes([("big.bin", payload)])
    path = _write(tmp_path, "outer.zip", _zip_bytes([("inner.zip", inner)]))

    leaf = next(leaf for leaf in walk(path) if leaf.name == "big.bin")

    with leaf.opener() as handle:
        assert handle.read(16) == payload[:16]
    assert leaf.size == len(payload)


def test_tar_bz2_with_packages(tmp_path):
    """Форма postgresql_*.tar.bz2: плоский набор пакетов в сжатом tar."""
    path = _write(
        tmp_path, "postgresql.tar.bz2",
        _tar_bytes([("libpq5_18.4_amd64.deb", b"deb-1"), ("postgresql-18_18.4_amd64.deb", b"deb-2")]),
    )

    leaves = sorted(leaf.name for leaf in walk(path))

    assert leaves == ["libpq5_18.4_amd64.deb", "postgresql-18_18.4_amd64.deb"]


def test_entry_content_is_readable(tmp_path):
    path = _write(tmp_path, "a.tar.gz", _tar_bytes([("inner.txt", b"hello")], mode="w:gz"))

    leaf = next(iter(walk(path)))

    with leaf.opener() as handle:
        assert handle.read() == b"hello"


def test_entry_can_be_opened_twice(tmp_path):
    """Каждое открытие — свой поток: делить его между потребителями нельзя."""
    path = _write(tmp_path, "a.zip", _zip_bytes([("x.txt", b"data")]))

    leaf = next(iter(walk(path)))

    with leaf.opener() as first, leaf.opener() as second:
        assert first.read() == second.read() == b"data"


# --- защита ------------------------------------------------------------------


def test_escaping_name_inside_a_container_is_rejected(tmp_path):
    """
    Имя из контейнера — такие же чужие данные, как имя записи .efd.

    Регресс: без санирования `../../etc/passwd` из вложенного архива уехал бы
    прямо в путь назначения.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../etc/passwd", b"root")
    path = _write(tmp_path, "evil.zip", buffer.getvalue())

    with pytest.raises(UnpackError) as ctx:
        list(walk(path))

    assert ctx.value.code is UnpackErrorCode.UNSAFE_ENTRY


def test_too_deep_nesting_is_rejected(tmp_path):
    """Наблюдали два уровня, разрешаем три, четвёртый отклоняем."""
    blob = _zip_bytes([("payload.txt", b"x")])
    for level in range(MAX_DEPTH + 1):
        blob = _zip_bytes([("level%d.zip" % level, blob)])
    path = _write(tmp_path, "deep.zip", blob)

    with pytest.raises(UnpackError) as ctx:
        list(walk(path))

    assert ctx.value.code is UnpackErrorCode.NESTING_TOO_DEEP


def test_nesting_at_the_limit_is_allowed(tmp_path):
    blob = _zip_bytes([("payload.txt", b"x")])
    for level in range(MAX_DEPTH - 1):
        blob = _zip_bytes([("level%d.zip" % level, blob)])
    path = _write(tmp_path, "ok.zip", blob)

    assert [leaf.name for leaf in walk(path)] == ["payload.txt"]


def test_unsupported_container_is_named(tmp_path):
    """RAR распознаётся, но здесь не читается — отказ должен быть внятным."""
    path = _write(tmp_path, "a.zip", _zip_bytes([("inner.rar", b"Rar!\x1a\x07\x01\x00rest")]))

    with pytest.raises(UnpackError) as ctx:
        list(walk(path))

    assert ctx.value.code is UnpackErrorCode.CONTAINER_UNSUPPORTED
    assert ctx.value.details["kind"] == "rar"


def test_too_many_entries_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("efd_unpacker.infrastructure.containers.MAX_ENTRIES", 3)
    path = _write(tmp_path, "many.zip", _zip_bytes([("f%d.txt" % i, b"x") for i in range(5)]))

    with pytest.raises(UnpackError) as ctx:
        list(walk(path))

    assert ctx.value.code is UnpackErrorCode.TOO_MANY_ENTRIES


def test_bomb_inside_a_nested_container_is_not_materialised(tmp_path):
    """
    Вложенная бомба не разворачивается: наружу отдаётся только заявленный
    размер и поток по требованию.
    """
    inner = _zip_bytes([("bomb.bin", b"\x00" * (64 * 1024 * 1024))], compress=True)
    path = _write(tmp_path, "outer.zip", _zip_bytes([("inner.zip", inner)]))

    leaf = next(leaf for leaf in walk(path) if leaf.name == "bomb.bin")

    assert leaf.size == 64 * 1024 * 1024
    assert os.path.getsize(path) < 1024 * 1024, "внешний архив мал — бомба не развёрнута"


# --- dmg ---------------------------------------------------------------------


def test_dmg_is_refused_where_it_cannot_be_mounted(tmp_path, monkeypatch):
    """На Linux и Windows заглянуть внутрь .dmg нечем — отказ, а не исключение."""
    monkeypatch.setattr("efd_unpacker.infrastructure.containers.dmg_supported", lambda: False)
    path = _write(tmp_path, "client.dmg", b"koly")

    with pytest.raises(UnpackError) as ctx:
        with open_dmg(path):
            pass

    assert ctx.value.code is UnpackErrorCode.CONTAINER_UNSUPPORTED
    assert ctx.value.details["kind"] == "dmg"


@pytest.mark.skipif(not dmg_supported(), reason="hdiutil есть только на macOS")
def test_dmg_is_mounted_and_detached(tmp_path):
    """Настоящий образ: монтируется только для чтения и обязательно отцепляется."""
    import subprocess

    source = tmp_path / "content"
    source.mkdir()
    (source / "readme.txt").write_text("hello", encoding="utf-8")
    image = tmp_path / "test.dmg"
    subprocess.run(
        ["hdiutil", "create", "-quiet", "-srcfolder", str(source), "-format", "UDZO", str(image)],
        check=True, capture_output=True,
    )

    before = set(os.listdir("/Volumes"))
    with open_dmg(str(image)) as leaves:
        assert [leaf.name for leaf in leaves] == ["readme.txt"]
        with leaves[0].opener() as handle:
            assert handle.read() == b"hello"

    assert set(os.listdir("/Volumes")) == before, "образ остался смонтированным"


def test_leaf_display_path_reads_as_a_trail():
    leaf = Leaf(trail=("demo.zip", "inner.zip", "1cv8.efd"), size=1, opener=lambda: io.BytesIO())

    assert leaf.display_path == "demo.zip → inner.zip → 1cv8.efd"
    assert leaf.name == "1cv8.efd"


# --- находки обзора ----------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [b"PK\x03\x04" + b"\x00" * 60, b"BZh9" + b"\xff" * 60, b"\x1f\x8b" + b"\xff" * 60],
    ids=["обрезанный zip", "обрезанный tar.bz2", "обрезанный tar.gz"],
)
def test_broken_container_becomes_a_domain_error(tmp_path, data):
    """
    Регресс: BadZipFile и ReadError уходили наружу как есть.

    Недокачанный архив — обычное дело, и выглядеть он должен как порча файла
    с локализованным сообщением, а не как исключение разборщика.
    """
    path = _write(tmp_path, "broken.zip", data)

    with pytest.raises(UnpackError) as ctx:
        list(walk(path))

    assert ctx.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE
    assert ctx.value.details["reason"] == "broken_container"


def test_duplicate_names_keep_their_own_content(tmp_path):
    """
    Регресс: открытие по имени отдавало последнюю запись под видом первой.

    Лист заявлял 5 байт, а читал 13 — и оба листа возвращали одно и то же.
    Открываем по самой записи, а не по имени.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("dup.txt", b"FIRST")
        archive.writestr("dup.txt", b"SECOND-LONGER")
    path = _write(tmp_path, "dup.zip", buffer.getvalue())

    read = []
    for leaf in walk(path):
        with leaf.opener() as handle:
            data = handle.read()
        assert len(data) == leaf.size
        read.append(data)

    assert read == [b"FIRST", b"SECOND-LONGER"]


def test_tar_duplicate_names_keep_their_own_content(tmp_path):
    path = _write(
        tmp_path, "dup.tar.gz",
        _tar_bytes([("dup.txt", b"FIRST"), ("dup.txt", b"SECOND-LONGER")], mode="w:gz"),
    )

    read = []
    for leaf in walk(path):
        with leaf.opener() as handle:
            read.append(handle.read())

    assert read == [b"FIRST", b"SECOND-LONGER"]


def test_descriptors_are_released_without_waiting_for_the_collector(tmp_path, monkeypatch):
    """
    Регресс: каждый вложенный архив держал дескриптор до сборки мусора.

    Измерено на 120 вложенных архивах: 5 дескрипторов превращались в 245.
    zipfile не закрывает переданный ему поток, а подмена handle.close
    замыканием создавала ссылочный цикл.

    Считаем не дескрипторы процесса, а сами потоки: каталога /dev/fd нет на
    Windows, а незакрытый поток одинаково виден везде. Модуль зовёт open по
    глобальному имени, поэтому подмена атрибута модуля перехватывает все
    открытия, включая те, что делают повторные вызовы opener.
    """
    inner = _zip_bytes([("payload.txt", b"x")])
    path = _write(
        tmp_path, "many.zip",
        _zip_bytes([("nested%03d.zip" % index, inner) for index in range(120)]),
    )

    opened = []
    real_open = open

    def tracking_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(containers, "open", tracking_open, raising=False)

    gc.disable()
    try:
        leaves = list(walk(path))
        for leaf in leaves:
            with leaf.opener() as handle:
                handle.read()
        unclosed = [handle for handle in opened if not handle.closed]
    finally:
        gc.enable()
        for handle in opened:
            handle.close()

    assert len(leaves) == 120
    assert opened, "подмена open не сработала — счётчик ничего не видел"
    assert not unclosed, "дескрипторы держатся до сборки мусора"


@pytest.mark.skipif(not dmg_supported(), reason="hdiutil есть только на macOS")
def test_symlink_out_of_the_image_is_not_exposed(tmp_path):
    """
    Регресс: симлинк из образа отдавал файл хоста как содержимое архива.

    os.walk возвращает такую ссылку обычным файлом, а getsize и чтение идут
    по ней: /etc/hosts приходил 213 байтами «из архива».
    """
    import subprocess

    source = tmp_path / "content"
    source.mkdir()
    (source / "real.txt").write_text("inside", encoding="utf-8")
    os.symlink("/etc/hosts", source / "escape.txt")
    image = tmp_path / "sym.dmg"
    subprocess.run(
        ["hdiutil", "create", "-quiet", "-srcfolder", str(source), "-format", "UDZO", str(image)],
        check=True, capture_output=True,
    )

    with open_dmg(str(image)) as leaves:
        names = [leaf.trail[-1] for leaf in leaves]

    assert names == ["real.txt"]


@pytest.mark.skipif(not dmg_supported(), reason="hdiutil есть только на macOS")
def test_symlink_inside_the_image_is_not_listed_twice(tmp_path):
    """
    Ссылка внутрь образа отбрасывается отдельно от проверки на выход наружу.

    realpath её пропускает — цель лежит внутри, — но лист был бы вторым
    именем того же файла. Цель при этом перечисляется сама по себе, так что
    ничего не теряется. Типичный случай — ярлык Applications в дистрибутивах.
    """
    import subprocess

    source = tmp_path / "content"
    source.mkdir()
    (source / "real.pkg").write_text("payload", encoding="utf-8")
    os.symlink("real.pkg", source / "latest.pkg")
    image = tmp_path / "inner.dmg"
    subprocess.run(
        ["hdiutil", "create", "-quiet", "-srcfolder", str(source), "-format", "UDZO", str(image)],
        check=True, capture_output=True,
    )

    with open_dmg(str(image)) as leaves:
        names = sorted(leaf.trail[-1] for leaf in leaves)

    assert names == ["real.pkg"]
