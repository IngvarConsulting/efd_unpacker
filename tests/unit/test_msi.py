"""
Тесты чтения версии платформы из msi установщика Windows.

Настоящий msi в репозиторий не кладётся — это три мегабайта чужого файла, —
поэтому здесь собранные блобы той же формы. Проверка на настоящем файле есть
ниже и пропускается, когда архива нет под рукой: так она не врёт про то, чего
на машине сборки не было.
"""

import os
from pathlib import Path

import pytest

from efd_unpacker.infrastructure import msi

#: Числа из настоящих msi: версии MSVC, WebKit, встроенной JRE. Ровно из-за
#: них номер и берётся по маркеру, а не «четыре числа через точку»: в полном
#: дистрибутиве кандидатов двадцать пять, и три начинаются с восьмёрки.
NEIGHBOURS = (
    b"11.0.51106.1 14.10.25028.0 257.3.1139.00 91.0.0.107 1.0.0.271 "
    b"8.0.275.1jre8u275_1_x64 8.9.10.0jre_licenses "
)

#: Так номер лежит у тонкого клиента и у полного 64-битного.
DESKTOP = b"docsDOCS.:DesktopDesktopFolder%sENLPRO~1|en.lproj"

#: А так — у серверного и у 32-битного полного.
SHORTCUT = b"COMM~1|MoreShortcutFolder83151~1|%sShortcutFolderVersion{&Ta"

#: Настоящие архивы. Проверка на них пропускается, когда их нет под рукой:
#: так она не врёт про то, чего на машине сборки не было.
DOWNLOADS = Path.home() / "Downloads"
REAL = [
    ("setuptc64_8_3_27_2342.rar", "8.3.27.2342"),
    ("setuptc_8_5_4_1683.rar", "8.5.4.1683"),
    ("windows64_8_5_4_1683.rar", "8.5.4.1683"),
    ("windows64full_8_5_4_1683.rar", "8.5.4.1683"),
    ("windows_8_5_4_1683.rar", "8.5.4.1683"),
]


def blob(tmp_path, payload: bytes, name: str = "setup.msi") -> str:
    path = tmp_path / name
    path.write_bytes(payload)
    return str(path)


@pytest.mark.parametrize("shape", [DESKTOP, SHORTCUT], ids=["desktop", "shortcut"])
def test_version_is_read_by_either_marker(tmp_path, shape):
    """
    Маркеров два, и поодиночке ни один не покрывает всё.

    DesktopFolder есть у тонкого клиента и у полного 64-битного,
    ShortcutFolderVersion — у всех вариантов windows*. Правило, выведенное
    по одному архиву, оставило бы шесть из десяти без версии.
    """
    assert msi.read_version(blob(tmp_path, shape % b"8.3.27.2342")) == "8.3.27.2342"


def test_versions_of_bundled_libraries_do_not_confuse_it(tmp_path):
    """
    Якорь на «8.» — не украшение.

    В настоящем msi четырнадцать четырёхчастных чисел, и тринадцать из них к
    платформе отношения не имеют.
    """
    path = blob(tmp_path, NEIGHBOURS + DESKTOP % b"8.3.27.2342" + NEIGHBOURS)

    assert msi.read_version(path) == "8.3.27.2342"


def test_number_glued_to_another_number_is_refused(tmp_path):
    """
    Значения в пуле лежат вплотную, без разделителей.

    Если следом за версией идёт другое число, различить, где кончилась одна
    и началась другая, нечем: «8.3.27.2342» и «11.0.51106.1» дают в файле
    «8.3.27.234211.0.51106.1». Без границ шаблон брал отсюда «8.3.27.234211»
    — номер, которого не существует. Отказ здесь честнее выдумки.
    """
    path = blob(tmp_path, b"DesktopFolder8.3.27.234211.0.51106.1")

    assert msi.read_version(path) == ""


def test_the_same_version_twice_is_still_one_answer(tmp_path):
    """У полного 64-битного срабатывают оба маркера — и дают одно и то же."""
    path = blob(tmp_path, DESKTOP % b"8.5.4.1683" + SHORTCUT % b"8.5.4.1683")

    assert msi.read_version(path) == "8.5.4.1683"


def test_two_different_versions_give_nothing(tmp_path):
    """
    Две разные версии в одном установщике мы объяснить не можем.

    Выбрать наугад хуже, чем не показать ничего: номер версии уедет в имя
    каталога, и ошибка в нём разведёт один выпуск по двум местам.
    """
    path = blob(tmp_path, DESKTOP % b"8.3.27.2342" + SHORTCUT % b"8.5.1.1529")

    assert msi.read_version(path) == ""


def test_version_split_across_two_chunks_is_found(tmp_path):
    """
    Файл читается кусками, и номер не должен теряться на их границе.

    Без нахлёста «8.3.27.» оставалось бы в одном куске, «2342» — в другом, и
    версия пропадала бы ровно на определённом размере файла.
    """
    payload = DESKTOP % b"8.3.27.2342"
    head = b"x" * (msi.CHUNK - len(payload) // 2)
    path = blob(tmp_path, head + payload + b"y" * 100)

    assert msi.read_version(path) == "8.3.27.2342"


@pytest.mark.parametrize(
    "payload",
    [b"", "ни одного номера".encode("utf-8"), b"8.3 8.3.27 1.2.3.4",
     b"8.3.27.2342 \xd0\xb1\xd0\xb5\xd0\xb7 \xd0\xbc\xd0\xb0\xd1\x80\xd0\xba\xd0\xb5\xd1\x80\xd0\xb0"],
    ids=["пусто", "без чисел", "неполные номера", "номер без маркера"],
)
def test_absent_version_is_an_empty_string(tmp_path, payload):
    assert msi.read_version(blob(tmp_path, payload)) == ""


def test_missing_file_is_not_a_failure(tmp_path):
    """Опознание вида идёт по именам записей и от версии не зависит."""
    assert msi.read_version(str(tmp_path / "нет.msi")) == ""


def test_directory_instead_of_a_file_is_survived(tmp_path):
    (tmp_path / "setup.msi").mkdir()

    assert msi.read_version(str(tmp_path / "setup.msi")) == ""


def test_huge_file_is_not_read_whole(tmp_path, monkeypatch):
    """
    Предел чтения — не предположение о размере msi, а страховка.

    Подставленный или повреждённый файл не должен уезжать в память целиком.
    """
    monkeypatch.setattr(msi, "SIZE_LIMIT", msi.CHUNK)
    # Номер лежит за пределом: до него чтение дойти не должно.
    path = blob(tmp_path, b"z" * (msi.CHUNK * 2) + DESKTOP % b"8.3.27.2342")

    assert msi.read_version(path) == ""


def test_version_of_accepts_nothing(tmp_path):
    assert msi.version_of(None) == ""
    assert msi.version_of(blob(tmp_path, DESKTOP % b"8.3.27.2342")) == "8.3.27.2342"


@pytest.mark.parametrize("archive, expected", REAL, ids=[name for name, _ in REAL])
def test_real_windows_installers(tmp_path, archive, expected):
    """
    Настоящие установщики: тонкий клиент, сервер, полный, 32 и 64 бита.

    Правило выведено по десяти архивам и двум версиям платформы. По одному
    оно бы не вывелось: маркер DesktopFolder, который есть у тонкого
    клиента, отсутствует у серверного и у 32-битного полного.

    Msi достаётся из архива отдельной записью — RAR5 несолидный, и вытащить
    три мегабайта из ста сорока стоит сотые доли секунды.
    """
    from efd_unpacker.infrastructure import rar

    path = DOWNLOADS / archive
    if not path.is_file():
        pytest.skip("нет архива %s под рукой" % archive)

    tool, entries = rar.read_entries(str(path))
    wanted = next(entry for entry in entries if entry.name.lower().endswith(".msi"))
    assert rar.extract_entry(tool, str(path), str(tmp_path), wanted)

    assert msi.read_version(os.path.join(str(tmp_path), wanted.name)) == expected
