"""
Тесты осмотра: из файла на диске в Inspected.

Главное свойство команды — ничего не писать. Оно проверяется не чтением кода,
а снимком дерева до и после: любой созданный файл, включая временный, ломает
тест.
"""

import io
import os
import struct
import zipfile
import zlib

import pytest

from efd_unpacker.application import inspector as inspector_module
from efd_unpacker.application.inspector import inspect, inspect_all
from efd_unpacker.domain.errors import UnpackErrorCode
from efd_unpacker.infrastructure import containers
from tests.efd_builder import build_efd


def _zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files:
            archive.writestr(name, data)
    return buffer.getvalue()


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _supply(entries=(("1c/Demo/1_0/1cv8.mft", b"m"), ("1c/Demo/1_0/1cv8.cf", b"data"))):
    return build_efd(entries, supply_info=[("ru", "Демо", "1С", "")])


def _tree(root):
    return sorted(str(path) for path in root.rglob("*"))


class _Counting:
    """
    Поток, считающий прочитанные байты.

    Именно обёртка, а не подмена метода: io.BufferedReader — тип на C, его
    атрибуты присвоить нельзя.
    """

    def __init__(self, inner, log):
        self._inner = inner
        self._log = log

    def read(self, *args):
        chunk = self._inner.read(*args)
        self._log.append(len(chunk))
        return chunk

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._inner.close()


# --- поставки ----------------------------------------------------------------


def test_efd_inside_zip_becomes_a_supply(tmp_path):
    path = _write(tmp_path, "demo.zip", _zip_bytes([("1cv8.efd", _supply())]))

    result = inspect(path)

    assert result.failure is None
    assert len(result.supplies) == 1
    assert result.supplies[0].trail == ("demo.zip", "1cv8.efd")
    assert result.supplies[0].catalog.describe().name == "Демо"


def test_bare_efd_is_inspected_without_a_container(tmp_path):
    path = _write(tmp_path, "1cv8.efd", _supply())

    result = inspect(path)

    assert len(result.supplies) == 1
    assert result.supplies[0].trail == ("1cv8.efd",)


def test_extension_is_matched_case_insensitively(tmp_path):
    """Имена внутри дистрибутивов 1С встречаются и в верхнем регистре."""
    path = _write(tmp_path, "demo.zip", _zip_bytes([("1CV8.EFD", _supply())]))

    result = inspect(path)

    assert len(result.supplies) == 1
    assert not result.files


def test_several_efd_in_one_archive_all_get_through(tmp_path):
    """
    Решение принято явно: каждый .efd становится своей находкой.

    В дикой природе такого не встречалось, но молча взять первый значило бы
    потерять остальные.
    """
    path = _write(
        tmp_path, "two.zip",
        _zip_bytes([("a/1cv8.efd", _supply()), ("b/1cv8.efd", _supply())]),
    )

    result = inspect(path)

    assert [found.trail[-1] for found in result.supplies] == ["a/1cv8.efd", "b/1cv8.efd"]


# --- прочие файлы ------------------------------------------------------------


def test_files_without_efd_are_collected_with_sizes(tmp_path):
    path = _write(
        tmp_path, "server.zip",
        _zip_bytes([("setup-full-8.3.27.2342-x86_64.run", b"x" * 100)]),
    )

    result = inspect(path)

    assert not result.supplies
    assert [(found.name, found.size) for found in result.files] == [
        ("setup-full-8.3.27.2342-x86_64.run", 100)
    ]


def test_empty_archive_yields_neither_supplies_nor_files(tmp_path):
    path = _write(tmp_path, "empty.zip", _zip_bytes([]))

    result = inspect(path)

    assert result.failure is None
    assert not result.supplies and not result.files


# --- отказы ------------------------------------------------------------------


def test_broken_archive_is_returned_as_failure_not_raised(tmp_path):
    path = _write(tmp_path, "broken.zip", b"PK\x03\x04" + b"\x00" * 60)

    result = inspect(path)

    assert result.failure is not None
    assert result.failure.code is UnpackErrorCode.CORRUPTED_ARCHIVE


def test_rar_is_reported_as_unsupported_container(tmp_path):
    path = _write(tmp_path, "tc.rar", b"Rar!\x1a\x07\x01\x00" + b"\x00" * 60)

    result = inspect(path)

    assert result.failure.code is UnpackErrorCode.CONTAINER_UNSUPPORTED
    assert result.failure.details["kind"] == "rar"


def test_broken_efd_inside_a_good_archive_fails_the_whole_file(tmp_path):
    """
    Оглавление не прочиталось — про содержимое архива сказать нечего.

    Выдать такой файл за «ничего не нашли» значило бы соврать: внутри лежит
    поставка, просто нечитаемая.
    """
    path = _write(tmp_path, "bad.zip", _zip_bytes([("1cv8.efd", b"not deflate at all")]))

    result = inspect(path)

    assert result.failure is not None
    assert result.failure.code is UnpackErrorCode.CORRUPTED_ARCHIVE


def test_missing_file_becomes_a_failure(tmp_path):
    result = inspect(str(tmp_path / "нет-такого.zip"))

    assert result.failure.code is UnpackErrorCode.FILE_NOT_FOUND


def test_directory_instead_of_file_does_not_raise(tmp_path):
    """IsADirectoryError — тоже OSError, и обрывать осмотр остальных он не должен."""
    result = inspect(str(tmp_path))

    assert result.failure is not None


# --- пакетный осмотр ---------------------------------------------------------


def test_order_follows_the_arguments(tmp_path):
    first = _write(tmp_path, "a.zip", _zip_bytes([("x.run", b"1")]))
    second = _write(tmp_path, "b.zip", _zip_bytes([("y.run", b"2")]))

    forward = [result.path for result in inspect_all([first, second])]
    backward = [result.path for result in inspect_all([second, first])]

    assert forward == [first, second]
    assert backward == [second, first]


def test_one_broken_file_does_not_stop_the_rest(tmp_path):
    good = _write(tmp_path, "good.zip", _zip_bytes([("1cv8.efd", _supply())]))
    bad = _write(tmp_path, "bad.zip", b"PK\x03\x04" + b"\x00" * 60)
    other = _write(tmp_path, "other.zip", _zip_bytes([("x.run", b"1")]))

    results = inspect_all([bad, good, other])

    assert [result.failure is None for result in results] == [False, True, True]


def test_progress_is_reported_before_each_file(tmp_path):
    first = _write(tmp_path, "a.zip", _zip_bytes([("x.run", b"1")]))
    second = _write(tmp_path, "b.zip", _zip_bytes([("y.run", b"2")]))
    seen = []

    inspect_all([first, second], on_start=seen.append)

    assert seen == [first, second]


# --- ничего не пишем ---------------------------------------------------------


def test_inspection_creates_no_files(tmp_path):
    """
    Критерий готовности #52: после прогона в файловой системе нет новых файлов.

    Снимок берётся по всему дереву, а не по одному каталогу: временный файл
    рядом с архивом тоже считается записью.
    """
    work = tmp_path / "work"
    work.mkdir()
    archive = _write(work, "demo.zip", _zip_bytes([("1cv8.efd", _supply())]))
    big = _write(work, "server.zip", _zip_bytes([("setup-full-8.3.27.2342-x86_64.run", b"x" * 5000)]))
    broken = _write(work, "bad.zip", b"PK\x03\x04" + b"\x00" * 60)

    before = _tree(tmp_path)
    inspect_all([archive, big, broken])
    after = _tree(tmp_path)

    assert after == before


def test_supply_is_read_without_inflating_the_payload(tmp_path, monkeypatch):
    """
    Осмотр читает оглавление, а не данные.

    Полезная нагрузка здесь на два порядка больше оглавления; если бы читалось
    всё, размер прочитанного выдал бы это.
    """
    payload = os.urandom(4 * 1024 * 1024)
    path = _write(
        tmp_path, "big.zip",
        _zip_bytes([("1cv8.efd", build_efd([("1c/D/1_0/1cv8.mft", b"m"), ("1c/D/1_0/data.cf", payload)]))]),
    )
    read = []

    def counting_open(*args, **kwargs):
        return _Counting(open(*args, **kwargs), read)

    monkeypatch.setattr(containers, "open", counting_open, raising=False)
    result = inspect(path)

    assert result.supplies[0].catalog.entries[1].size == len(payload)
    assert read, "подмена open не сработала — счётчик ничего не видел"
    assert sum(read) < len(payload) // 2, "прочитано слишком много — читаются данные, а не оглавление"


@pytest.mark.parametrize("name", ["image.dmg", "IMAGE.DMG"])
def test_dmg_is_recognised_by_extension(tmp_path, monkeypatch, name):
    """
    Образ узнаётся по расширению: сигнатуры в начале файла у него нет.

    Без этого detect_kind вернул бы None и образ уехал бы в план как один
    непонятный файл вместо своего содержимого.
    """
    from efd_unpacker.application import sources

    path = _write(tmp_path, name, b"\x00" * 600)
    monkeypatch.setattr(sources, "dmg_supported", lambda: False)

    result = inspect(path)

    assert result.failure.code is UnpackErrorCode.CONTAINER_UNSUPPORTED
    assert result.failure.details["kind"] == "dmg"


def test_unreadable_entry_name_becomes_a_row_not_a_crash(tmp_path):
    """
    Битый UTF-16 в имени записи раньше уносил весь прогон.

    read_catalog отдавал UnicodeDecodeError, а осмотр ловил только UnpackError
    и OSError: один такой файл оставлял пользователя без строк по всем
    остальным.
    """
    head = struct.pack("II", 1, 0) + struct.pack("I", 1)
    head += struct.pack("I", 0)
    broken = b"\x00\xd8\x00\x00"  # незакрытая суррогатная пара
    head += struct.pack("I", len(broken) // 2) + broken
    head += struct.pack("q", 132223104000000000) + struct.pack("I", 0) + struct.pack("I", 0)
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    path = _write(
        tmp_path, "bad.zip",
        _zip_bytes([("1cv8.efd", compressor.compress(head) + compressor.flush())]),
    )

    result = inspect(path)

    assert result.failure.code is UnpackErrorCode.CORRUPTED_ARCHIVE
    assert result.failure.details["reason"] == "broken_entry_name"


def test_unexpected_error_on_one_file_does_not_stop_the_rest(tmp_path, monkeypatch):
    """
    Последний рубеж: неожиданный отказ тоже становится строкой, а не падением.

    Перечислить все типы исключений нельзя — набор открытый, и именно на этом
    осмотр уже один раз обрывался.
    """
    good = _write(tmp_path, "good.zip", _zip_bytes([("x.run", b"1")]))
    bad = _write(tmp_path, "bad.zip", _zip_bytes([("1cv8.efd", _supply())]))

    real = inspector_module.read_catalog

    def explode(handle, *args, **kwargs):
        raise RuntimeError("что-то пошло не так внутри библиотеки")

    monkeypatch.setattr(inspector_module, "read_catalog", explode)
    results = inspect_all([bad, good])
    monkeypatch.setattr(inspector_module, "read_catalog", real)

    assert results[0].failure.code is UnpackErrorCode.UNEXPECTED
    assert results[1].failure is None, "осмотр второго файла не состоялся"
