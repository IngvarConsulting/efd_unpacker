"""
Регрессия #3/#5: отрицательный FILETIME валил распаковку целиком.

onec_dtools читает поле как беззнаковое "Q", поэтому -17400000000 превращалось
в 18446744056309551616, и datetime + timedelta бросал OverflowError. Падение
происходит при разборе оглавления, до записи первого файла, — отсюда жалобы
вида «вообще не распаковывает».

Значения взяты из настоящих поставок с releases.1c.ru:
  БГУ 2.0.110.66              — 10 таких записей из 83
  Бухгалтерия КОРП 3.0.206.19 — 21 из 26
"""

import datetime as dt
import io
import struct

import pytest

from efd_unpacker.domain import unpack_service
from efd_unpacker.domain.unpack_service import UnpackService
from tests.efd_builder import unpacked_tree, write_efd

# Ровно то, что лежит в 1cv8.efd БГУ: -17400000000 как беззнаковое 64-битное.
REAL_NEGATIVE_FILETIME = 18446744056309551616
FILETIME_2020 = 132223104000000000


def test_the_real_value_is_a_negative_signed_integer():
    """Фиксируем природу значения: это не порча, а дата раньше 1601 года."""
    signed = struct.unpack("q", struct.pack("Q", REAL_NEGATIVE_FILETIME))[0]

    assert signed == -17400000000
    assert signed / 10_000_000 == -1740  # секунд до эпохи FILETIME


@pytest.mark.parametrize(
    "filetime, expected",
    [
        (REAL_NEGATIVE_FILETIME, None),
        (-1, None),
        (0, None),
        (FILETIME_2020, dt.datetime(2020, 1, 1)),
        (2**63 - 1, None),  # верхний край: год далеко за 9999
    ],
    ids=["из БГУ", "минус один", "ноль", "2020", "максимум int64"],
)
def test_filetime_conversion(filetime, expected):
    assert unpack_service._filetime_to_datetime(filetime) == expected


def _entry_bytes(name: str, filetime: int, size: int) -> bytes:
    encoded = name.encode("utf-16")
    return (
        struct.pack("I", 0)
        + struct.pack("I", len(encoded) // 2)
        + encoded
        + struct.pack("Q", filetime)
        + struct.pack("I", 0)
        + struct.pack("I", size)
    )


def test_included_file_info_survives_a_negative_filetime():
    """Регресс: onec_dtools читает "Q" и падает ещё на разборе оглавления."""
    buffer = io.BytesIO(_entry_bytes("a\\b.txt", REAL_NEGATIVE_FILETIME, 7))

    name, modified_at, size = unpack_service._read_included_file_info(buffer)

    assert name == "a\\b.txt"
    assert modified_at is None
    assert size == 7


def test_included_file_info_reads_filetime_as_signed(monkeypatch):
    """
    Отдельная проверка именно знаковости чтения.

    Без неё подмена "q" на "Q" проходит незамеченной: _filetime_to_datetime
    гасит и беззнакового гиганта — через переполнение timedelta. Результат
    совпадает, но по случайности, а не по замыслу, и любая правка конвертера
    (например, зажим вместо перехвата) молча вернула бы падение.
    """
    seen = []
    monkeypatch.setattr(unpack_service, "_filetime_to_datetime", lambda value: seen.append(value))

    unpack_service._read_included_file_info(io.BytesIO(_entry_bytes("a.txt", REAL_NEGATIVE_FILETIME, 1)))

    assert seen == [-17400000000]


def test_included_file_info_keeps_normal_dates():
    buffer = io.BytesIO(_entry_bytes("a.txt", FILETIME_2020, 3))

    _name, modified_at, _size = unpack_service._read_included_file_info(buffer)

    assert modified_at == dt.datetime(2020, 1, 1)


def test_archive_with_negative_filetime_unpacks(tmp_path):
    """
    Сквозной регресс: раньше здесь был OverflowError и ноль файлов на выходе.

    Проверено и на настоящих поставках: БГУ 2.0.110.66 отдаёт 83 файла (2.3 ГБ),
    «Бухгалтерия КОРП» 3.0.206.19 — 26 файлов (946 МБ), размеры совпадают
    с объявленными в оглавлении до байта.
    """
    source = write_efd(
        tmp_path / "negative.efd",
        [("dir\\first.txt", b"first"), ("dir\\second.txt", b"second")],
        filetime=REAL_NEGATIVE_FILETIME,
    )
    output_dir = tmp_path / "out"

    UnpackService().unpack(source, str(output_dir))

    assert unpacked_tree(output_dir) == ["dir/first.txt", "dir/second.txt"]
    assert (output_dir / "dir" / "first.txt").read_bytes() == b"first"


def test_negative_filetime_leaves_a_representable_mtime(tmp_path):
    """Файл получает текущее время, а не INT64_MIN и не 1601 год."""
    source = write_efd(
        tmp_path / "negative.efd", [("a.txt", b"x")], filetime=REAL_NEGATIVE_FILETIME
    )
    output_dir = tmp_path / "out"

    UnpackService().unpack(source, str(output_dir))

    stamp = (output_dir / "a.txt").stat().st_mtime
    assert stamp > dt.datetime(2000, 1, 1).timestamp()


def test_apply_file_mtime_accepts_none(tmp_path, monkeypatch):
    """None означает «осмысленной даты нет» и не должен доходить до os.utime."""
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    calls = []
    monkeypatch.setattr(unpack_service.os, "utime", lambda *a, **k: calls.append(a))

    unpack_service._apply_file_mtime(str(target), None)

    assert calls == []
