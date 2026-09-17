"""
Интеграционные тесты CLI на настоящем UnpackService.

Раньше здесь стоял NoopUnpackService, который ничего не распаковывал: тесты
проверяли только код возврата, а вся работа с форматом оставалась непокрытой.
"""

import hashlib
import os
import sys

import pytest

from efd_unpacker.application.cli import CLIApplication, CLIResult
from efd_unpacker.domain.file_validator import FileValidator
from efd_unpacker.domain.unpack_service import UnpackService
from tests.efd_builder import unpacked_tree, write_efd

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "1cv8.efd")

# Содержимое tests/data/1cv8.efd: путь, размер, sha256.
EXPECTED_CONTENTS = [
    ("IngvarConsulting/Test/1Cv8.cf", 10772, "b84bd692a098e66617288119c8289b76237417b06f6783ce86a6a52bf2672afc"),
    ("IngvarConsulting/Test/1Cv8.dt", 29215, "60abf608b175f36964864d8477f8e09385edaeaa4e000bfc089dc327b5f62b5c"),
    ("IngvarConsulting/Test/1Cv8snc.1CD", 98304, "d17b969e8cb3da6c3de44af5253a56ead1203abf1d6304e53f2990f8074a5457"),
    ("IngvarConsulting/Test/1cv8.mft", 171, "0fc76af0d136aef9c26aa54e0fafc244e8abf603e85b17681962ba9ab8f09e53"),
]


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return source


def _cli(output=None):
    return CLIApplication(
        validator=FileValidator(),
        unpack_service=UnpackService(),
        translator=DummyTranslator(),
        output=output or (lambda message: None),
    )


def test_cli_unpacks_the_real_sample_byte_for_byte(tmp_path):
    """Не только «файлы появились», но и что содержимое именно то."""
    output_dir = tmp_path / "out"

    result = _cli().run(["efd_unpacker", "unpack", SAMPLE, "-tmplts", str(output_dir)])

    assert result == CLIResult(exit_code=0, handled=True)
    assert unpacked_tree(output_dir) == [name for name, _, _ in EXPECTED_CONTENTS]

    for name, size, digest in EXPECTED_CONTENTS:
        data = (output_dir / name).read_bytes()
        assert len(data) == size, name
        assert hashlib.sha256(data).hexdigest() == digest, name


def test_cli_reports_missing_input(tmp_path):
    messages = []

    result = _cli(messages.append).run(
        ["efd_unpacker", "unpack", str(tmp_path / "missing.efd"), "-tmplts", str(tmp_path / "out")]
    )

    assert result.exit_code == 1
    assert result.handled
    assert any("[ERROR]" in message for message in messages)


def test_cli_reports_damaged_archive(tmp_path):
    """Битый архив обязан давать ненулевой код, а не «успех» с пустыми файлами."""
    damaged = tmp_path / "damaged.efd"
    damaged.write_bytes(open(SAMPLE, "rb").read()[:4000])
    output_dir = tmp_path / "out"
    messages = []

    result = _cli(messages.append).run(
        ["efd_unpacker", "unpack", str(damaged), "-tmplts", str(output_dir)]
    )

    assert result.exit_code == 1
    assert any("[ERROR]" in message for message in messages)


def test_cli_refuses_archive_escaping_the_output_directory(tmp_path):
    source = write_efd(tmp_path / "evil.efd", [("..\\..\\escaped.txt", b"payload")])
    workspace = tmp_path / "workspace"
    output_dir = workspace / "out"
    output_dir.mkdir(parents=True)
    messages = []

    result = _cli(messages.append).run(
        ["efd_unpacker", "unpack", source, "-tmplts", str(output_dir)]
    )

    assert result.exit_code == 1
    assert any("[ERROR]" in message for message in messages)
    assert not (workspace / "escaped.txt").exists()
    assert unpacked_tree(output_dir) == []


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-путь как имя записи")
def test_cli_refuses_absolute_posix_entry(tmp_path):
    source = write_efd(tmp_path / "abs.efd", [("/etc/passwd", b"payload")])
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = _cli().run(["efd_unpacker", "unpack", source, "-tmplts", str(output_dir)])

    assert result.exit_code == 1
    assert unpacked_tree(output_dir) == []


def test_cli_creates_the_output_directory(tmp_path):
    output_dir = tmp_path / "deep" / "nested" / "out"

    result = _cli().run(["efd_unpacker", "unpack", SAMPLE, "-tmplts", str(output_dir)])

    assert result.exit_code == 0
    assert output_dir.is_dir()
    assert unpacked_tree(output_dir)


def test_cli_reports_an_incomplete_command_instead_of_opening_the_gui(tmp_path):
    """
    Контракт изменён намеренно (#15).

    Раньше `unpack <файл>` без -tmplts возвращал handled=False, и процесс
    проваливался в Qt event loop: из терминала поднималось окно, а под
    QT_QPA_PLATFORM без дисплея команда висела до убийства — ни сообщения,
    ни кода возврата. docs/CLI.md называл эту форму «не headless-режимом»,
    но GUI не обещал. Теперь unpack всегда обрабатывается CLI: код 2 и usage.
    """
    messages = []

    result = _cli(messages.append).run(["efd_unpacker", "unpack", SAMPLE])

    assert result.handled is True
    assert result.exit_code == 2
    assert "efd_unpacker unpack <input_file.efd> -tmplts <output_dir>" in "\n".join(messages)


def test_cli_still_leaves_a_bare_file_to_the_gui(tmp_path):
    """GUI-режим из docs/CLI.md не тронут: файл без команды unpack уходит в окно."""
    result = _cli().run(["efd_unpacker", SAMPLE])

    assert result.handled is False
    assert result.exit_code == 0
