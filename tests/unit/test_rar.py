"""
Тесты поиска внешней программы для .rar.

Настоящих 7-Zip и WinRAR на машине сборки нет, а класть в репозиторий
141-мегабайтный архив незачем. Поэтому программы здесь подставные: скрипты на
Python, запускаемые тем же интерпретатором. Это не имитация вызова — процесс
запускается настоящий, аргументы разбираются настоящие, отличается только то,
что на другом конце.

Разборщик вывода libarchive проверен на настоящем setuptc64_8_3_27_2342.rar:
44 записи из 44. Разборщик 7-Zip проверен на формате `l -slt`, а не на живой
программе — этого в проекте нет на чём сделать.
"""

import os
import sys

import pytest

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.infrastructure import rar
from efd_unpacker.infrastructure.rar import LIBARCHIVE, SEVENZIP, RarEntry, Tool

# Подставная программа. Поведение зашито в файл, а не в окружение: поиск
# кешируется, и переключать режим через переменную было бы нечестно.
FAKE = '''
import os
import sys
import time

BEHAVIOUR = %r
LISTING = (
    "-rw-r--r--  0 owner name group name        5 Jan  1 00:00 data/a.txt\\n"
    "-rw-r--r--  0 owner name group name       11 Feb 29  2024 data/файл с пробелом.txt\\n"
    "drwxr-xr-x  0 owner name group name        0 Jan  1 00:00 data/\\n"
    "lrwxr-xr-x  0 owner name group name        3 Jan  1 00:00 data/link -> a.txt\\n"
)
CONTENT = {"data/a.txt": b"12345", "data/\\u0444\\u0430\\u0439\\u043b \\u0441 \\u043f\\u0440\\u043e\\u0431\\u0435\\u043b\\u043e\\u043c.txt": b"12345678901"}

args = sys.argv[1:]
if BEHAVIOUR == "hang":
    time.sleep(30)
if args and args[0] == "--version":
    print("fake 1.0")
    sys.exit(0)
if args and args[0] == "-tvf":
    if BEHAVIOUR == "broken_list":
        sys.exit(1)
    sys.stdout.write(LISTING)
    sys.exit(0)
if args and args[0] == "-xf":
    if BEHAVIOUR == "list_only":
        sys.exit(1)
    if BEHAVIOUR == "silent":
        sys.exit(0)          # код успеха, но ничего не создано
    destination = args[args.index("-C") + 1]
    wanted = args[args.index("-C") + 2:]
    for name, data in CONTENT.items():
        if wanted and name not in wanted:
            continue
        path = os.path.join(destination, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * (len(data) - 1) if BEHAVIOUR == "short" else data)
    sys.exit(0)
sys.exit(2)
'''


def fake_tool(tmp_path, behaviour="good", name="bsdtar"):
    script = tmp_path / ("%s_%s.py" % (name, behaviour))
    script.write_text(FAKE % behaviour, encoding="utf-8")
    return Tool(path=str(script), family=LIBARCHIVE, version="fake 1.0",
                prefix=(sys.executable,))


@pytest.fixture(autouse=True)
def _forget_discovery():
    """Поиск кешируется на весь процесс — между тестами его надо сбрасывать."""
    rar.forget()
    yield
    rar.forget()


# --- разбор вывода libarchive ------------------------------------------------


def test_libarchive_listing_is_parsed_by_the_date_not_by_columns():
    """
    По номерам колонок разбирать нельзя: имя владельца бывает с пробелом.

    Здесь владелец «owner name», группа «group name» — при позиционном разборе
    размер уехал бы на две колонки.
    """
    output = (
        "-rw-r--r--  0 owner name group name        5 Jan  1 00:00 data/a.txt\n"
        "-rw-r--r--  0 owner name group name       11 Feb 29  2024 data/файл с пробелом.txt\n"
    )

    entries = rar._parse_libarchive(output)

    assert entries == (
        RarEntry("data/a.txt", 5),
        RarEntry("data/файл с пробелом.txt", 11),
    )


def test_libarchive_listing_skips_directories_and_unwraps_symlinks():
    output = (
        "drwxr-xr-x  0 u g        0 Jan  1 00:00 data/\n"
        "lrwxr-xr-x  0 u g        3 Jan  1 00:00 data/link -> a.txt\n"
        "-rw-r--r--  0 u g        5 Jan  1 00:00 data/a.txt\n"
    )

    entries = rar._parse_libarchive(output)

    assert [entry.name for entry in entries] == ["data/link", "data/a.txt"]


def test_libarchive_listing_ignores_lines_without_a_date():
    """Предупреждения программы не должны превращаться в записи."""
    output = "bsdtar: Ignoring malformed header\n-rw-r--r--  0 u g  5 Jan  1 00:00 a.txt\n"

    assert rar._parse_libarchive(output) == (RarEntry("a.txt", 5),)


# --- разбор вывода 7-Zip -----------------------------------------------------


def test_sevenzip_listing_reads_key_value_blocks():
    """Формат `l -slt` выбран за то, что не зависит ни от локали, ни от колонок."""
    output = (
        "Path = data\\a.txt\n"
        "Size = 5\n"
        "Attributes = _ -rw-r--r--\n"
        "\n"
        "Path = data\n"
        "Size = 0\n"
        "Attributes = D_ drwxr-xr-x\n"
        "\n"
        "Path = data\\b.txt\n"
        "Size = 11\n"
        "Attributes = _ -rw-r--r--\n"
    )

    entries = rar._parse_sevenzip(output)

    assert entries == (RarEntry("data/a.txt", 5), RarEntry("data/b.txt", 11))


def test_sevenzip_listing_survives_a_missing_trailing_blank_line():
    """Последний блок без пустой строки в конце тоже должен попасть в список."""
    output = "Path = only.txt\nSize = 7\nAttributes = _ -rw-r--r--"

    assert rar._parse_sevenzip(output) == (RarEntry("only.txt", 7),)


# --- проверка на самом архиве ------------------------------------------------


def test_listing_tool_that_cannot_extract_is_not_chosen(tmp_path, monkeypatch):
    """
    Критерий #54: подставная программа, которая печатает оглавление, но падает
    на распаковке, рабочей не считается.
    """
    broken = fake_tool(tmp_path, "list_only", name="brokentar")
    good = fake_tool(tmp_path, "good")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (broken, good))
    destination = tmp_path / "out"
    destination.mkdir()

    chosen = rar.extract(str(tmp_path / "any.rar"), str(destination))

    assert chosen.path == good.path
    assert (destination / "data" / "a.txt").read_bytes() == b"12345"


def test_tool_that_reports_success_without_creating_anything_is_not_chosen(tmp_path, monkeypatch):
    """
    Самый коварный случай: код возврата 0, а файлов нет.

    Поэтому проверка смотрит на файл и его размер, а не на код возврата.
    """
    silent = fake_tool(tmp_path, "silent", name="silenttar")
    good = fake_tool(tmp_path, "good")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (silent, good))

    chosen = rar.extract(str(tmp_path / "any.rar"), str(tmp_path))

    assert chosen.path == good.path


def test_tool_that_extracts_a_short_file_is_not_chosen(tmp_path, monkeypatch):
    """Размер на диске сверяется с заявленным: усечённая запись — не успех."""
    short = fake_tool(tmp_path, "short", name="shorttar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (short,))

    assert rar.verify(short, str(tmp_path / "any.rar"), rar.list_entries(short, "x")) is False


def test_verification_extracts_only_the_smallest_entry(tmp_path, monkeypatch):
    """Цена проверки — доли секунды даже для архива на 141 МБ."""
    good = fake_tool(tmp_path, "good")
    created = []
    real = rar._extract_with

    def spy(tool, archive, destination, only=None):
        created.append(only)
        return real(tool, archive, destination, only)

    monkeypatch.setattr(rar, "_extract_with", spy)
    rar.verify(good, "any.rar", rar.list_entries(good, "x"))

    assert created == ["data/a.txt"], "проверка должна брать самую маленькую запись"


# --- отсутствие программ -----------------------------------------------------


def test_no_tools_gives_a_domain_error_with_a_hint(tmp_path, monkeypatch):
    """
    Критерий #54: при отсутствии всех кандидатов — пропуск, а не исключение
    наружу. Код CONTAINER_UNSUPPORTED с kind=rar план превращает в
    SkipReason.RAR_TOOL_MISSING.
    """
    monkeypatch.setattr(rar, "discover", lambda extra=None: ())

    with pytest.raises(UnpackError) as caught:
        rar.read_entries(str(tmp_path / "tc.rar"))

    assert caught.value.code is UnpackErrorCode.CONTAINER_UNSUPPORTED
    assert caught.value.details["kind"] == "rar"
    assert caught.value.details["hint"], "подсказку об установке надо показать"


def test_broken_listing_falls_through_to_the_next_tool(tmp_path, monkeypatch):
    broken = fake_tool(tmp_path, "broken_list", name="badtar")
    good = fake_tool(tmp_path, "good")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (broken, good))

    entries = rar.read_entries("any.rar")

    assert [entry.name for entry in entries] == [
        "data/a.txt", "data/файл с пробелом.txt", "data/link",
    ]


def test_hanging_tool_does_not_block_forever(tmp_path, monkeypatch):
    """Зависшая программа не должна превращать осмотр каталога в ожидание."""
    hanging = fake_tool(tmp_path, "hang", name="hangtar")
    monkeypatch.setattr(rar, "LIST_TIMEOUT", 1.0)

    assert rar.list_entries(hanging, "any.rar") is None


# --- поиск кандидатов --------------------------------------------------------


def test_the_same_binary_behind_two_names_is_probed_once(tmp_path, monkeypatch):
    """
    На macOS /usr/bin/tar — символьная ссылка на bsdtar.

    Так и выходит, когда --rar-tool указывает на ссылку, а поиск находит цель:
    без разрешения пути один бинарник проверялся бы дважды, а каждая проверка
    стоит запуска процесса.
    """
    real = tmp_path / "bsdtar"
    real.write_text("#!/bin/sh\n", encoding="utf-8")
    link = tmp_path / "tar"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows без прав
        pytest.skip("символьные ссылки недоступны")

    monkeypatch.setattr(rar.sys, "platform", "darwin")
    monkeypatch.setattr(rar.shutil, "which",
                        lambda name: str(real) if name == "bsdtar" else None)
    monkeypatch.setattr(rar, "_version", lambda *_args: "x")

    assert len(rar.discover(str(link))) == 1


def test_discovery_is_not_repeated_for_every_file(tmp_path, monkeypatch):
    """Критерий #54: результат поиска не пересчитывается на каждый файл."""
    calls = []
    monkeypatch.setattr(rar.shutil, "which", lambda name: calls.append(name) or None)

    rar.discover()
    rar.discover()
    rar.discover()

    assert calls, "поиск не запускался вовсе"
    assert len(calls) == len(set(calls)), "поиск повторился"


def test_explicit_tool_comes_first(tmp_path, monkeypatch):
    """
    Критерий #54: --rar-tool перекрывает поиск — это для контейнеров сборки.

    Поиск он при этом не отменяет: подставленная программа тоже проверяется на
    архиве, и если не подойдёт, очередь дойдёт до системной.
    """
    chosen = tmp_path / "myown"
    chosen.write_text("#!/bin/sh\n", encoding="utf-8")
    system = tmp_path / "bsdtar"
    system.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(rar.shutil, "which", lambda name: str(system) if name == "bsdtar" else None)
    monkeypatch.setattr(rar, "_version", lambda *_args: "x")

    tools = rar.discover(str(chosen))

    assert [os.path.basename(tool.path) for tool in tools] == ["myown", "bsdtar"]


@pytest.mark.parametrize(
    "name, expected",
    [("bsdtar", LIBARCHIVE), ("tar", LIBARCHIVE), ("tar.exe", LIBARCHIVE),
     ("7zz", SEVENZIP), ("7z.exe", SEVENZIP), ("что-то", SEVENZIP)],
)
def test_family_is_guessed_by_the_file_name(name, expected):
    assert rar._guess_family("/opt/bin/" + name) == expected


def test_registry_is_only_read_on_windows(monkeypatch):
    monkeypatch.setattr(rar.sys, "platform", "darwin")

    assert rar._from_registry() == []


def test_install_hint_is_a_command_not_an_action():
    """Установку не запускаем: человек вправе знать, что ставится в систему."""
    assert "install" in rar.install_hint()


# --- реестр Windows ----------------------------------------------------------


class FakeWinreg:
    """
    Заглушка winreg: модуль существует только на Windows.

    Без неё разбор путей из реестра проверялся бы лишь на самой Windows, где
    7-Zip обычно не установлен, — то есть не проверялся бы вовсе.
    """

    HKEY_LOCAL_MACHINE = 1
    HKEY_CURRENT_USER = 2

    def __init__(self, values):
        self.values = values
        self.opened = []

    def OpenKey(self, root, subkey):  # noqa: N802 - имя из winreg
        self.opened.append((root, subkey))
        if (root, subkey) not in self.values:
            raise OSError("нет такого ключа")
        return _FakeKey()

    def QueryValueEx(self, _handle, name):  # noqa: N802 - имя из winreg
        for values in self.values.values():
            if name in values:
                return values[name], 1
        raise OSError("нет такого значения")


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _with_winreg(monkeypatch, fake):
    monkeypatch.setattr(rar.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", fake)


def test_registry_gives_the_installation_path(monkeypatch):
    """
    Искать через реестр, а не перебором каталогов: Program Files бывает
    локализован, а пользовательская установка лежит вовсе не там.
    """
    fake = FakeWinreg({(FakeWinreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip"): {"Path": r"D:\Мои программы\7-Zip"}})
    _with_winreg(monkeypatch, fake)

    assert rar._from_registry() == [(os.path.join(r"D:\Мои программы\7-Zip", "7z.exe"), SEVENZIP)]


def test_registry_looks_in_both_hives(monkeypatch):
    """Установка «только для меня» кладёт ключ в HKCU, а не в HKLM."""
    fake = FakeWinreg({(FakeWinreg.HKEY_CURRENT_USER, r"SOFTWARE\7-Zip"): {"Path": r"C:\Users\u\7-Zip"}})
    _with_winreg(monkeypatch, fake)

    assert rar._from_registry() == [(os.path.join(r"C:\Users\u\7-Zip", "7z.exe"), SEVENZIP)]


def test_missing_registry_key_is_not_an_error(monkeypatch):
    _with_winreg(monkeypatch, FakeWinreg({}))

    assert rar._from_registry() == []


def test_registry_value_of_the_wrong_type_is_ignored(monkeypatch):
    """REG_MULTI_SZ отдаёт список — os.path.join на нём падает."""
    fake = FakeWinreg({(FakeWinreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip"): {"Path": ["a", "b"]}})
    _with_winreg(monkeypatch, fake)

    assert rar._from_registry() == []


# --- версия программы --------------------------------------------------------


def test_version_is_read_from_the_first_line(tmp_path):
    tool = fake_tool(tmp_path)

    assert rar._version(tool.path, LIBARCHIVE, tool.prefix) == "fake 1.0"


def test_version_of_a_missing_program_is_empty():
    """Отсутствие внятного ответа не повод исключать программу из проверки."""
    assert rar._version("/нет/такой/программы", LIBARCHIVE) == ""


# --- извлечение одной записи -------------------------------------------------


def test_extract_entry_uses_the_tool_that_read_the_listing(tmp_path, monkeypatch):
    good = fake_tool(tmp_path, "good")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (good,))
    destination = tmp_path / "one"
    destination.mkdir()

    assert rar.extract_entry("any.rar", str(destination), "data/a.txt") is True
    assert (destination / "data" / "a.txt").read_bytes() == b"12345"
    assert not (destination / "data" / "файл с пробелом.txt").exists(), "извлеклось лишнее"


def test_extract_entry_reports_failure_when_no_tool_works(tmp_path, monkeypatch):
    broken = fake_tool(tmp_path, "broken_list", name="badtar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (broken,))

    assert rar.extract_entry("any.rar", str(tmp_path), "data/a.txt") is False


# --- настройка на весь запуск ------------------------------------------------


def test_configured_tool_is_used_when_no_explicit_one_is_given(tmp_path, monkeypatch):
    chosen = tmp_path / "myown"
    chosen.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(rar.shutil, "which", lambda _name: None)
    monkeypatch.setattr(rar, "_version", lambda *_args: "x")

    rar.configure(str(chosen))
    try:
        assert [tool.name for tool in rar.discover()] == ["myown"]
    finally:
        rar.reset()


def test_changing_the_tool_within_one_process_takes_effect(tmp_path, monkeypatch):
    """
    Кеш ключуется выбранной программой, поэтому смена значения даёт другой
    ключ и пересчёт происходит сам. Тест закрепляет именно это свойство: без
    него пришлось бы сбрасывать кеш руками.
    """
    first = tmp_path / "first"
    second = tmp_path / "second"
    for path in (first, second):
        path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(rar.shutil, "which", lambda _name: None)
    monkeypatch.setattr(rar, "_version", lambda *_args: "x")

    rar.configure(str(first))
    try:
        assert [tool.name for tool in rar.discover()] == ["first"]
        rar.configure(str(second))
        assert [tool.name for tool in rar.discover()] == ["second"]
    finally:
        rar.reset()
