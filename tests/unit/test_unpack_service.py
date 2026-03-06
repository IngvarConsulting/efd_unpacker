import os
import tempfile
import unittest

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
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


if __name__ == "__main__":
    unittest.main()
