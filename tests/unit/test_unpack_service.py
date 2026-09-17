import datetime as dt
import os
import tempfile
import unittest

import pytest
from pathlib import Path

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain import unpack_service
from efd_unpacker.domain.unpack_service import UnpackService


class DummyReader:
    def __init__(self, stream):
        self.stream = stream
        self.called = False

    def unpack(self, output_dir: str) -> None:
        self.called = True
        self.output_dir = output_dir


class TestUnpackService(unittest.TestCase):
    def test_unpack_success(self) -> None:
        reader = DummyReader(None)

        def factory(handle):
            return reader

        service = UnpackService(reader_factory=factory)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"data")
            tmp_path = tmp.name
        try:
            service.unpack(tmp_path, "/tmp")
            self.assertTrue(reader.called)
        finally:
            os.unlink(tmp_path)

    def test_unpack_file_not_found(self) -> None:
        service = UnpackService()
        with self.assertRaises(UnpackError) as ctx:
            service.unpack("missing.efd", "/tmp")
        self.assertEqual(ctx.exception.code, UnpackErrorCode.FILE_NOT_FOUND)


def test_unpack_skips_unrepresentable_timestamps(monkeypatch, tmp_path) -> None:
    """Даты до 1678 года пропускаются на всех платформах, а не только на Windows."""
    sample = Path(__file__).resolve().parents[1] / "data" / "1cv8.efd"
    service = UnpackService()

    original_utime = unpack_service.os.utime
    utime_calls = []

    def guarded_utime(path, times):
        utime_calls.append(times)
        assert times[0] >= 0
        return original_utime(path, times)

    monkeypatch.setattr(unpack_service.os, "utime", guarded_utime)

    service.unpack(str(sample), str(tmp_path))

    assert (tmp_path / "IngvarConsulting" / "Test" / "1Cv8.dt").exists()
    assert utime_calls == []


def test_unpack_leaves_representable_mtime_on_every_platform(tmp_path) -> None:
    """
    Регресс на INT64_MIN: guard был привязан к Windows, поэтому на macOS и Linux
    древние FILETIME уезжали в os.utime и давали st_mtime_ns = -2**63.
    """
    sample = Path(__file__).resolve().parents[1] / "data" / "1cv8.efd"

    UnpackService().unpack(str(sample), str(tmp_path))

    unpacked = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(unpacked) == 4
    for path in unpacked:
        assert path.stat().st_mtime_ns != -(2 ** 63), path


def test_apply_file_mtime_skips_dates_before_the_representable_range(tmp_path, monkeypatch):
    """FILETIME от 1601 года не должен уезжать в os.utime ни на одной платформе."""
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    calls = []
    monkeypatch.setattr(unpack_service.os, "utime", lambda *a, **k: calls.append(a))

    unpack_service._apply_file_mtime(str(target), dt.datetime(1601, 5, 3))

    assert calls == []


def test_unpack_service_does_not_branch_on_platform_for_mtime():
    """
    Регресс: guard был привязан к sys.platform, и на macOS/Linux древние даты
    уезжали в os.utime, давая st_mtime_ns = INT64_MIN. После правки модуль
    вообще не смотрит на платформу — подменять в тесте нечего.
    """
    assert not hasattr(unpack_service, "sys")
    assert unpack_service.MIN_REPRESENTABLE_MTIME == dt.datetime(1678, 1, 1)


@pytest.mark.parametrize(
    "moment, applied",
    [
        (dt.datetime(1601, 5, 3), False),
        (dt.datetime(1677, 12, 31), False),
        (dt.datetime(1678, 1, 2), True),
        (dt.datetime(1969, 1, 1), True),
        (dt.datetime(2019, 6, 15), True),
    ],
    ids=["1601", "1677", "1678", "1969", "2019"],
)
def test_apply_file_mtime_boundary(tmp_path, monkeypatch, moment, applied):
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    calls = []
    monkeypatch.setattr(unpack_service.os, "utime", lambda *a, **k: calls.append(a))

    unpack_service._apply_file_mtime(str(target), moment)

    assert bool(calls) is applied


def test_apply_file_mtime_applies_modern_dates(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")

    unpack_service._apply_file_mtime(str(target), dt.datetime(2019, 6, 15, 12, 0, 0))

    assert dt.datetime.utcfromtimestamp(os.path.getmtime(str(target))).year == 2019


def test_apply_file_mtime_survives_oserror(tmp_path, monkeypatch):
    """Метка времени — не повод считать распаковку неуспешной."""
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(unpack_service.os, "utime", boom)

    unpack_service._apply_file_mtime(str(target), dt.datetime(2019, 6, 15))


if __name__ == "__main__":
    unittest.main()
