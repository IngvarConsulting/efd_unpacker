import os
import tempfile
import unittest
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


def test_unpack_skips_unsupported_windows_timestamps(monkeypatch, tmp_path) -> None:
    sample = Path(__file__).resolve().parents[1] / "data" / "1cv8.efd"
    service = UnpackService()

    original_utime = unpack_service.os.utime
    utime_calls = []

    def guarded_utime(path, times):
        utime_calls.append(times)
        assert times[0] >= 0
        return original_utime(path, times)

    monkeypatch.setattr(unpack_service.sys, "platform", "win32")
    monkeypatch.setattr(unpack_service.os, "utime", guarded_utime)

    service.unpack(str(sample), str(tmp_path))

    assert (tmp_path / "IngvarConsulting" / "Test" / "1Cv8.dt").exists()
    assert utime_calls == []


if __name__ == "__main__":
    unittest.main()
