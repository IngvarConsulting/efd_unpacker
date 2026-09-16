"""
Регрессионные тесты целостности архива.

Раньше повреждённый .efd распаковывался молча: CLI печатал [OK], возвращал 0,
а на диске оставался неполный каталог шаблона.
"""

import struct
import zlib
from pathlib import Path

import pytest

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain.unpack_service import UnpackService

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "1cv8.efd"
FILETIME_2020 = 132223104000000000


def _wide_string(value: str) -> bytes:
    encoded = value.encode("utf-16")
    return struct.pack("I", len(encoded) // 2) + encoded


def _build_efd(entries, header: int = 1, declared_sizes=None) -> bytes:
    """Собирает .efd; declared_sizes позволяет соврать о размере записей."""
    head = struct.pack("II", header, 0) + struct.pack("I", len(entries))
    payload = b""
    for index, (name, data) in enumerate(entries):
        declared = declared_sizes[index] if declared_sizes else len(data)
        head += struct.pack("I", 0)
        head += _wide_string(name)
        head += struct.pack("Q", FILETIME_2020)
        head += struct.pack("I", 0)
        head += struct.pack("I", declared)
        payload += data

    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(head + payload) + compressor.flush()


def _write(path: Path, blob: bytes) -> str:
    path.write_bytes(blob)
    return str(path)


@pytest.mark.parametrize("keep_bytes", [500, 32000], ids=["head-500", "head-32000"])
def test_truncated_archive_is_rejected(keep_bytes, tmp_path):
    """Недокачанный .efd больше не считается успешно распакованным."""
    source = _write(tmp_path / "trunc.efd", SAMPLE.read_bytes()[:keep_bytes])
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(source, str(output_dir))

    assert ctx.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE


def test_entry_larger_than_stream_is_rejected(tmp_path):
    """Объявленный размер больше доступных данных — ошибка, а не пустые файлы."""
    blob = _build_efd([("a.txt", b"1234"), ("b.txt", b"5678")], declared_sizes=[64, 4])
    source = _write(tmp_path / "lying.efd", blob)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(source, str(output_dir))

    assert ctx.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE
    assert ctx.value.details["reason"] == "truncated_entry"
    assert list(output_dir.rglob("*")) == []


def test_unsupported_header_reports_the_reason(tmp_path):
    """Вместо AssertionError без текста — код ошибки и внятная причина."""
    source = _write(tmp_path / "alien.efd", _build_efd([("a.txt", b"x")], header=0xDEADBEEF))
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(source, str(output_dir))

    assert ctx.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE
    assert ctx.value.details["reason"] == "unsupported_header"


def test_duplicate_entries_are_rejected(tmp_path):
    """Дубль имени раньше молча терял первую запись."""
    source = _write(tmp_path / "dup.efd", _build_efd([("dup.txt", b"first"), ("dup.txt", b"second")]))
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(source, str(output_dir))

    assert ctx.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE
    assert ctx.value.details["reason"] == "duplicate_entry"
    assert list(output_dir.rglob("*")) == []


def test_case_insensitive_duplicate_entries_are_rejected(tmp_path):
    """На APFS и NTFS README.txt и readme.txt — один файл."""
    source = _write(tmp_path / "case.efd", _build_efd([("README.txt", b"a"), ("readme.txt", b"bb")]))
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(source, str(output_dir))

    assert ctx.value.details["reason"] == "duplicate_entry"


def test_entry_colliding_with_directory_is_rejected(tmp_path):
    """Раньше это падало на os.makedirs с FileExistsError уже после записи части файлов."""
    source = _write(tmp_path / "clash.efd", _build_efd([("a", b"file"), ("a\\b.txt", b"nested")]))
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(UnpackError) as ctx:
        UnpackService().unpack(source, str(output_dir))

    assert ctx.value.details["reason"] == "entry_is_also_directory"
    assert list(output_dir.rglob("*")) == []


def test_failed_unpack_keeps_previous_file_intact(tmp_path):
    """Запись идёт через временный файл: обрыв не оставляет обрезанной версии."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    victim = output_dir / "a.txt"
    victim.write_bytes(b"previous version")

    blob = _build_efd([("a.txt", b"new")], declared_sizes=[4096])
    source = _write(tmp_path / "bad.efd", blob)

    with pytest.raises(UnpackError):
        UnpackService().unpack(source, str(output_dir))

    assert victim.read_bytes() == b"previous version"
    assert [p.name for p in output_dir.iterdir()] == ["a.txt"]


def test_valid_archive_still_unpacks_completely(tmp_path):
    UnpackService().unpack(str(SAMPLE), str(tmp_path))

    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert files == [
        "IngvarConsulting/Test/1Cv8.cf",
        "IngvarConsulting/Test/1Cv8.dt",
        "IngvarConsulting/Test/1Cv8snc.1CD",
        "IngvarConsulting/Test/1cv8.mft",
    ]
    assert all(p.stat().st_size > 0 for p in tmp_path.rglob("*") if p.is_file())
