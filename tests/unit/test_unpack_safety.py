"""
Регрессионные тесты безопасности распаковки.

Архивы собираются на лету в tmp_path: класть вредоносную фикстуру в репозиторий
не нужно, а формат достаточно прост, чтобы описать его генератором.
"""

import os
import struct
import zlib
from pathlib import Path

import pytest

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain.unpack_service import UnpackService

FILETIME_2020 = 132223104000000000


def _wide_string(value: str) -> bytes:
    """Строка в формате .efd: длина в символах + UTF-16."""
    encoded = value.encode("utf-16")
    return struct.pack("I", len(encoded) // 2) + encoded


def _build_efd(entries) -> bytes:
    """Собирает .efd из пар (имя записи, содержимое)."""
    header = struct.pack("II", 1, 0) + struct.pack("I", len(entries))
    payload = b""
    for name, data in entries:
        header += struct.pack("I", 0)
        header += _wide_string(name)
        header += struct.pack("Q", FILETIME_2020)
        header += struct.pack("I", 0)
        header += struct.pack("I", len(data))
        payload += data

    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(header + payload) + compressor.flush()


def _write_efd(path: Path, entries) -> str:
    path.write_bytes(_build_efd(entries))
    return str(path)


UNSAFE_NAMES = [
    pytest.param("..\\..\\escaped.txt", id="parent-traversal"),
    pytest.param("\\escaped.txt", id="leading-separator"),
    pytest.param("/escaped.txt", id="leading-slash"),
    pytest.param("D:\\escaped.txt", id="drive-prefix"),
    pytest.param("sub\\..\\..\\escaped.txt", id="traversal-in-the-middle"),
]


@pytest.mark.parametrize("entry_name", UNSAFE_NAMES)
def test_unsafe_entry_is_rejected_and_nothing_escapes(entry_name, tmp_path):
    source = _write_efd(tmp_path / "evil.efd", [(entry_name, b"payload")])
    output_dir = tmp_path / "workspace" / "out"
    output_dir.mkdir(parents=True)

    before = sorted(p.name for p in (tmp_path / "workspace").iterdir())

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(source, str(output_dir))

    assert ctx.value.code is UnpackErrorCode.UNSAFE_ENTRY
    assert sorted(p.name for p in (tmp_path / "workspace").iterdir()) == before
    assert list(output_dir.iterdir()) == []


def test_unsafe_entry_rejects_archive_before_writing_safe_entries(tmp_path):
    """Отклоняем архив целиком: половина распакованных файлов хуже, чем отказ."""
    source = _write_efd(
        tmp_path / "mixed.efd",
        [("good\\a.txt", b"first"), ("..\\escaped.txt", b"second")],
    )
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(source, str(output_dir))

    assert ctx.value.code is UnpackErrorCode.UNSAFE_ENTRY
    assert list(output_dir.rglob("*")) == []


def test_nested_entry_still_unpacks(tmp_path):
    source = _write_efd(tmp_path / "ok.efd", [("A\\B\\file.txt", b"content")])
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    UnpackService().unpack(source, str(output_dir))

    assert (output_dir / "A" / "B" / "file.txt").read_bytes() == b"content"


def test_real_fixture_entries_pass_the_normalizer(tmp_path):
    sample = Path(__file__).resolve().parents[1] / "data" / "1cv8.efd"

    UnpackService().unpack(str(sample), str(tmp_path))

    unpacked = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert unpacked == [
        "IngvarConsulting/Test/1Cv8.cf",
        "IngvarConsulting/Test/1Cv8.dt",
        "IngvarConsulting/Test/1Cv8snc.1CD",
        "IngvarConsulting/Test/1cv8.mft",
    ]


def test_unpacking_twice_into_the_same_directory_succeeds(tmp_path):
    """Повторная распаковка того же шаблона — штатный сценарий (регресс на O_EXCL)."""
    sample = Path(__file__).resolve().parents[1] / "data" / "1cv8.efd"
    service = UnpackService()

    service.unpack(str(sample), str(tmp_path))
    service.unpack(str(sample), str(tmp_path))

    assert (tmp_path / "IngvarConsulting" / "Test" / "1Cv8.dt").exists()


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW доступен только на Unix")
def test_symlink_in_place_of_target_is_not_followed(tmp_path):
    source = _write_efd(tmp_path / "ok.efd", [("victim.txt", b"new content")])
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    (output_dir / "victim.txt").symlink_to(outside)

    with pytest.raises(UnpackError):
        UnpackService().unpack(source, str(output_dir))

    assert outside.read_text(encoding="utf-8") == "original"


def test_oversized_stream_is_rejected_without_exhausting_memory(tmp_path, monkeypatch):
    from efd_unpacker.domain import unpack_service as module

    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(module, "MIN_RATIO_CHECK_BYTES", 1024 * 1024)

    payload = b"\0" * (64 * 1024 * 1024)
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    bomb = tmp_path / "bomb.efd"
    bomb.write_bytes(compressor.compress(payload) + compressor.flush())

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(str(bomb), str(output_dir))

    assert ctx.value.code is UnpackErrorCode.TOO_LARGE
    assert list(output_dir.rglob("*")) == []
