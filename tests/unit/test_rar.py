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
import subprocess
import sys

import pytest

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.infrastructure import rar
from efd_unpacker.infrastructure.rar import LIBARCHIVE, SEVENZIP, RarEntry, Tool

#: Настоящая функция: фикстура ниже подменяет её заглушкой для всех тестов,
#: кроме тех, что проверяют сам разбор реестра.
_REAL_FROM_REGISTRY = rar._from_registry

# Подставная программа. Поведение зашито в файл, а не в окружение: поиск
# кешируется, и переключать режим через переменную было бы нечестно.
FAKE = """
import os
import sys
import time

BEHAVIOUR = "__BEHAVIOUR__"
OUTSIDE = os.environ.get("FAKE_OUTSIDE", "")
LISTING = (
    "-rw-r--r--  0 owner name group name        5 Jan  1 00:00 data/a.txt\\n"
    "-rw-r--r--  0 owner name group name       11 Feb 29  2024 data/\u0444\u0430\u0439\u043b \u0441 \u043f\u0440\u043e\u0431\u0435\u043b\u043e\u043c.txt\\n"
    "drwxr-xr-x  0 owner name group name        0 Jan  1 00:00 data/\\n"
    "lrwxr-xr-x  0 owner name group name        3 Jan  1 00:00 data/link -> a.txt\\n"
)
LISTINGS = {
    "traversal": "-rw-r--r--  0 u g  5 Jan  1 00:00 ../../escaped.txt\\n",
    "duplicates": (
        "-rw-r--r--  0 u g  9 Jan  1 00:00 dup.txt\\n"
        "-rw-r--r--  0 u g  4 Jan  1 00:00 dup.txt\\n"
    ),
    "empty": "",
}
CONTENT = {
    "data/a.txt": b"12345",
    "data/\u0444\u0430\u0439\u043b \u0441 \u043f\u0440\u043e\u0431\u0435\u043b\u043e\u043c.txt": b"12345678901",
}

args = sys.argv[1:]
if BEHAVIOUR == "hang":
    time.sleep(30)
if args and args[0] == "--version":
    sys.stdout.buffer.write(b"fake 1.0\\n")
    sys.exit(0)
if args and args[0] == "-tvf":
    if BEHAVIOUR == "broken_list":
        sys.exit(1)
    if BEHAVIOUR == "symlink":
        listing = "lrwxr-xr-x  0 u g  %d Jan  1 00:00 payload.efd -> %s\\n" % (len(OUTSIDE), OUTSIDE)
        listing += "-rw-r--r--  0 u g  6 Jan  1 00:00 real.txt\\n"
    elif BEHAVIOUR == "symlink_exact":
        # Размер заявлен ровно такой, какой у файла за ссылкой: сверка размера
        # такую запись пропустит, отклонить её может только проверка на ссылку.
        listing = "-rw-r--r--  0 u g  6 Jan  1 00:00 payload.efd\\n"
    elif BEHAVIOUR == "dirlink":
        listing = "-rw-r--r--  0 u g  6 Jan  1 00:00 data/a.txt\\n"
    elif BEHAVIOUR == "innerlink":
        listing = "-rw-r--r--  0 u g  6 Jan  1 00:00 payload.efd\\n"
    elif BEHAVIOUR == "partial":
        listing = (
            "-rw-r--r--  0 u g  6 Jan  1 00:00 first.txt\\n"
            "-rw-r--r--  0 u g  6 Jan  1 00:00 second.txt\\n"
        )
    else:
        listing = LISTINGS.get(BEHAVIOUR, LISTING)
    sys.stdout.buffer.write(listing.encode("utf-8"))
    sys.exit(0)
if args and args[0] == "-xf":
    if BEHAVIOUR == "list_only":
        sys.exit(1)
    if BEHAVIOUR == "silent":
        sys.exit(0)          # код успеха, но ничего не создано
    destination = args[args.index("-C") + 1]
    wanted = args[args.index("-C") + 2:]
    if BEHAVIOUR == "symlink_exact":
        os.symlink(OUTSIDE, os.path.join(destination, "payload.efd"))
        sys.exit(0)
    if BEHAVIOUR == "innerlink":
        # Ссылка ведёт ВНУТРЬ каталога: и размер сойдётся, и вложенность —
        # отклонить такую запись может только проверка на ссылку.
        with open(os.path.join(destination, "real.txt"), "wb") as handle:
            handle.write(b"normal")
        os.symlink("real.txt", os.path.join(destination, "payload.efd"))
        sys.exit(0)
    if BEHAVIOUR == "dirlink":
        # Ссылкой становится КАТАЛОГ: сам файл обычный и нужного размера, но
        # лежит он за пределами назначения.
        os.symlink(OUTSIDE, os.path.join(destination, "data"))
        sys.exit(0)
    if BEHAVIOUR == "partial":
        with open(os.path.join(destination, "first.txt"), "wb") as handle:
            handle.write(b"normal")
        sys.exit(0)
    if BEHAVIOUR == "symlink":
        for name in (wanted or ["payload.efd", "real.txt"]):
            target = os.path.join(destination, name)
            if name == "payload.efd":
                os.symlink(OUTSIDE, target)
            else:
                with open(target, "wb") as handle:
                    handle.write(b"normal")
        sys.exit(0)
    for name, data in CONTENT.items():
        if wanted and name not in wanted:
            continue
        path = os.path.join(destination, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * (len(data) - 1) if BEHAVIOUR == "short" else data)
    sys.exit(0)
sys.exit(2)
"""


def fake_tool(tmp_path, behaviour="good", name="bsdtar"):
    script = tmp_path / ("%s_%s.py" % (name, behaviour))
    script.write_text(FAKE.replace("__BEHAVIOUR__", behaviour), encoding="utf-8")
    return Tool(path=str(script), family=LIBARCHIVE, version="fake 1.0",
                prefix=(sys.executable,))


def _entry(tool, name):
    """Запись из оглавления этой программы — ровно то, что получает опенер."""
    entries = rar.list_entries(tool, "any.rar") or ()
    return next(item for item in entries if item.name == name)


@pytest.fixture(autouse=True)
def _isolate_discovery(monkeypatch):
    """
    Поиск изолируется от машины, на которой идёт прогон.

    Кеш живёт весь процесс, поэтому сбрасывается между тестами. Реестр
    заглушается: на раннере windows-2022 установлен настоящий 7z.exe, и поиск
    находил его помимо подменённого shutil.which — тесты про порядок и про
    отсутствие программ падали от того, что есть на машине сборки.
    """
    rar.reset()
    monkeypatch.setattr(rar, "_from_registry", list)
    yield
    rar.reset()


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

    _tool, entries = rar.read_entries("any.rar")

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

    # Платформа задаётся явно: список кандидатов у каждой свой, и на Windows
    # bsdtar в нём отсутствует вовсе — тест проверял бы пустоту вместо порядка.
    monkeypatch.setattr(rar.sys, "platform", "darwin")
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

    assert _REAL_FROM_REGISTRY() == []


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
    """Возвращает настоящий _from_registry поверх заглушки из фикстуры."""
    monkeypatch.setattr(rar, "_from_registry", _REAL_FROM_REGISTRY)
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
    tool = fake_tool(tmp_path, "good")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))
    destination = tmp_path / "one"
    destination.mkdir()

    assert rar.extract_entry(tool, "any.rar", str(destination), _entry(tool, "data/a.txt")) is True
    assert (destination / "data" / "a.txt").read_bytes() == b"12345"
    assert not (destination / "data" / "файл с пробелом.txt").exists(), "извлеклось лишнее"


def test_leaf_is_filled_by_the_tool_that_listed_it(tmp_path, monkeypatch):
    """
    Лист, созданный по оглавлению одной программы, не наполняется другой.

    Воспроизведено: первая перечисляла запись как 100 байт и не умела
    распаковывать, вторая перечисляла её же как 6 байт и умела — лист заявлял
    100, а отдавал 6. Теперь программа и запись фиксируются при создании листа,
    и при отказе лист честно отказывает.
    """
    listing_only = fake_tool(tmp_path, "list_only", name="listonly")
    working = fake_tool(tmp_path, "good", name="working")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (listing_only, working))
    destination = tmp_path / "one"
    destination.mkdir()
    entry = _entry(listing_only, "data/a.txt")

    assert rar.extract_entry(listing_only, "any.rar", str(destination), entry) is False
    assert not list(destination.iterdir()), "вторая программа всё-таки наполнила лист"


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


# --- кодировка вывода --------------------------------------------------------


def test_output_is_decoded_as_utf8_first():
    """
    Вывод берётся байтами, а не text=True.

    На Windows text=True декодирует кодировкой локали — cp1251 или cp866, — и
    кириллица в именах записей превратилась бы в мусор.
    """
    assert rar._decode("файл.txt".encode("utf-8")) == "файл.txt"


def test_undecodable_output_does_not_lose_the_whole_listing(monkeypatch):
    """Потерять одно имя лучше, чем потерять всё оглавление."""
    monkeypatch.setattr(rar.locale, "getpreferredencoding", lambda _do_setlocale=True: "ascii")

    decoded = rar._decode(b"a.txt\n\xff\xfe broken\n")

    assert "a.txt" in decoded


def test_unknown_locale_encoding_is_survived(monkeypatch):
    """LookupError от несуществующей кодировки не должен ронять осмотр."""
    monkeypatch.setattr(rar.locale, "getpreferredencoding", lambda _do_setlocale=True: "нет-такой")

    assert rar._decode(b"\xff plain") .endswith("plain")


def test_sevenzip_is_asked_for_utf8_output(tmp_path, monkeypatch):
    """
    7-Zip по умолчанию пишет в кодовой странице консоли; -sccUTF-8 делает
    вывод предсказуемым независимо от системы.
    """
    seen = []
    monkeypatch.setattr(rar, "_run", lambda command, _timeout: seen.append(command) or None)

    rar.list_entries(Tool(path="7z", family=SEVENZIP), "any.rar")

    assert "-sccUTF-8" in seen[0]


# --- имена и содержимое от чужой программы -----------------------------------


def test_traversal_in_an_entry_name_is_refused(tmp_path, monkeypatch):
    """
    Имя уходит аргументом во внешнюю программу.

    `../../escaped.txt` распаковался бы за пределы назначения руками самой
    программы, мимо всех наших проверок пути.
    """
    tool = fake_tool(tmp_path, "traversal", name="evil")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))

    with pytest.raises(UnpackError) as caught:
        rar.read_entries("any.rar")

    assert caught.value.code is UnpackErrorCode.UNSAFE_ENTRY


def test_duplicate_entry_names_are_refused(tmp_path, monkeypatch):
    """
    Программа выбирает запись по имени.

    Два листа с одним именем вернули бы одно и то же содержимое, и хотя бы
    один перестал бы совпадать с заявленным размером. Для .efd этот случай
    уже отклоняется тем же кодом.
    """
    tool = fake_tool(tmp_path, "duplicates", name="dups")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))

    with pytest.raises(UnpackError) as caught:
        rar.read_entries("any.rar")

    assert caught.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE
    assert caught.value.details["reason"] == "duplicate_entry"


def test_empty_archive_is_not_an_unsupported_format(tmp_path, monkeypatch):
    """
    Пустое оглавление и отказ программы — разные ответы.

    Слитые воедино, они объявляли пустой архив неподдерживаемым форматом.
    """
    tool = fake_tool(tmp_path, "empty", name="emptytar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))

    assert rar.read_entries("any.rar")[1] == ()


def test_extract_entry_checks_what_the_tool_produced(tmp_path, monkeypatch):
    """
    Код возврата ноль без файла успехом не считается.

    Иначе поток записи упал бы голым FileNotFoundError вместо доменного отказа.
    """
    tool = fake_tool(tmp_path, "silent", name="silenttar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))

    assert rar.extract_entry(tool, "any.rar", str(tmp_path), _entry(tool, "data/a.txt")) is False


def test_extract_entry_refuses_a_short_file(tmp_path, monkeypatch):
    tool = fake_tool(tmp_path, "short", name="shorttar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))
    destination = tmp_path / "out"
    destination.mkdir()

    assert rar.extract_entry(tool, "any.rar", str(destination), _entry(tool, "data/a.txt")) is False


def test_extracted_symlink_is_not_accepted_as_content(tmp_path, monkeypatch):
    """
    Распакованная ссылка на файл хозяина открылась бы обычным open как запись
    архива. Тот же случай уже ловился для образов .dmg — здесь он вернулся
    другим путём.
    """
    secret = tmp_path / "secret.txt"
    secret.write_text("совершенно секретно", encoding="utf-8")
    monkeypatch.setenv("FAKE_OUTSIDE", str(secret))
    tool = fake_tool(tmp_path, "symlink", name="linktar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))
    destination = tmp_path / "out"
    destination.mkdir()

    assert rar.extract_entry(tool, "any.rar", str(destination), _entry(tool, "payload.efd")) is False


def test_symlink_whose_target_matches_the_declared_size_is_still_refused(tmp_path, monkeypatch):
    """
    Проверку на ссылку не должна перекрывать сверка размера.

    Здесь файл за ссылкой ровно того размера, что заявлен в оглавлении: сверка
    размера такую запись пропускает, и отклонить её может только islink. Без
    этого теста мутация «убрать islink» проходила незамеченной — ровно так же,
    как однажды уже было с образами .dmg.
    """
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"normal")
    monkeypatch.setenv("FAKE_OUTSIDE", str(secret))
    tool = fake_tool(tmp_path, "symlink_exact", name="exacttar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))
    destination = tmp_path / "out"
    destination.mkdir()

    assert rar.extract_entry(tool, "any.rar", str(destination), _entry(tool, "payload.efd")) is False


def test_regular_file_reached_through_a_symlinked_directory_is_refused(tmp_path, monkeypatch):
    """
    Ссылкой может оказаться каталог, а не файл.

    Тогда сам файл обычный и нужного размера, islink на нём молчит, а лежит он
    за пределами назначения. Отклоняет его только проверка вложенности.
    """
    outside = tmp_path / "выход"
    outside.mkdir()
    (outside / "a.txt").write_bytes(b"normal")
    monkeypatch.setenv("FAKE_OUTSIDE", str(outside))
    tool = fake_tool(tmp_path, "dirlink", name="dirtar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))
    destination = tmp_path / "out"
    destination.mkdir()

    assert rar.extract_entry(tool, "any.rar", str(destination), _entry(tool, "data/a.txt")) is False


def test_extraction_that_misses_a_file_is_not_accepted(tmp_path, monkeypatch):
    """
    Раскладывает файлы чужая программа, и её код возврата ничего не доказывает.

    Здесь она перечисляет две записи, а создаёт одну — и выходит с нулём.
    """
    partial = fake_tool(tmp_path, "partial", name="parttar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (partial,))
    destination = tmp_path / "out"
    destination.mkdir()

    with pytest.raises(UnpackError) as caught:
        rar.extract("any.rar", str(destination))

    assert caught.value.code is UnpackErrorCode.CONTAINER_UNSUPPORTED
    assert "parttar" in caught.value.details["tried"]


def test_symlink_pointing_inside_the_destination_is_still_refused(tmp_path, monkeypatch):
    """
    Проверку на ссылку не должна перекрывать и проверка вложенности.

    Здесь ссылка ведёт внутрь каталога: размер сходится, вложенность сходится,
    и отклонить запись может только islink. Запись, объявленная файлом, но
    оказавшаяся ссылкой, — признак того, что программа сделала не то, о чём
    её просили.
    """
    tool = fake_tool(tmp_path, "innerlink", name="innertar")
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))
    destination = tmp_path / "out"
    destination.mkdir()

    assert rar.extract_entry(tool, "any.rar", str(destination), _entry(tool, "payload.efd")) is False


# --- что экран настроек берёт отсюда -----------------------------------------


def test_successful_read_is_remembered_as_a_probe(tmp_path, monkeypatch):
    """
    Пригодность проверяется на самом архиве — и результат стоит записать.

    Экран настроек иначе не может сказать про программу ничего, кроме номера
    версии, а он про поддержку формата и не говорит: набор форматов libarchive
    задаётся при сборке. «Проверена на вашем архиве» без такой записи было бы
    выдумкой, а выдумка на экране, по которому принимают решения, хуже пустоты.
    """
    tool = fake_tool(tmp_path)
    monkeypatch.setattr(rar, "discover", lambda extra=None: (tool,))
    assert rar.last_probe() is None

    used, entries = rar.read_entries(str(tmp_path / "setuptc64.rar"))

    probe = rar.last_probe()
    assert probe is not None
    assert probe.tool is used
    assert probe.archive == "setuptc64.rar"
    assert probe.entries == len(entries)


def test_probe_is_not_recorded_when_nothing_could_read_the_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(rar, "discover", lambda extra=None: (fake_tool(tmp_path, "broken_list"),))

    with pytest.raises(UnpackError):
        rar.read_entries(str(tmp_path / "a.rar"))

    assert rar.last_probe() is None


def test_forgetting_the_search_forgets_the_probe_too(tmp_path, monkeypatch):
    """
    Запись о проверке говорит про программу из кеша поиска.

    Пережив его, она утверждала бы что-то про программу, которой в списке
    больше нет: «Искать заново» после удаления bsdtar показала бы пустой
    список и строку о том, что он проверен.
    """
    monkeypatch.setattr(rar, "discover", lambda extra=None: (fake_tool(tmp_path),))
    rar.read_entries(str(tmp_path / "a.rar"))
    assert rar.last_probe() is not None

    rar.forget()

    assert rar.last_probe() is None


def test_known_families_keep_the_search_order():
    """
    Порядок тот же, что у поиска: по нему видно, кого позовут первым.

    Семейство названо один раз, а не по разу на каждое имя в PATH: 7zz и 7z —
    одна и та же программа, и две строки про неё в экране настроек были бы
    шумом.
    """
    families = rar.known_families()

    assert families == tuple(dict.fromkeys(families)), "семейство названо дважды"
    assert LIBARCHIVE in families and SEVENZIP in families
    assert all(family in rar.FAMILY_TITLES for family in families)


def test_searched_names_are_the_ones_actually_looked_for(monkeypatch):
    """«Ищется как…» обязано совпадать с тем, что и правда ищется в PATH."""
    asked = []
    monkeypatch.setattr(rar.shutil, "which", lambda name: asked.append(name) and None)

    rar.discover()

    for family in rar.known_families():
        for name in rar.searched_names(family):
            assert name in asked


def test_found_does_not_start_a_search(tmp_path, monkeypatch):
    """
    Цифра в меню не должна стоить запуска чужих программ.

    Меню открывается в потоке окна, а поиск запускает каждого кандидата за
    номером версии: предел ожидания такого запуска — двадцать секунд.

    Вторая подмена which поверх первой, а не через monkeypatch.undo(): undo
    снимает ВСЕ подмены, включая заглушку реестра из фикстуры, — и на раннере
    windows-2022 discover() находил настоящий 7z.exe, установленный в системе.
    """
    monkeypatch.setattr(rar.shutil, "which", _forbidden_which)
    assert rar.found() is None

    monkeypatch.setattr(rar.shutil, "which", lambda name: None)
    rar.discover()

    assert rar.found() == ()


def _forbidden_which(_name):
    raise AssertionError("found() не должен запускать поиск")


# --- разборщики против НАСТОЯЩИХ программ ------------------------------------

#: Что кладём в пробный архив. Две записи разного размера и каталог: размеры
#: должны прочитаться, каталог — отсеяться.
SAMPLE = (
    ("readme.txt", b"a" * 11),
    (os.path.join("data", "inner.bin"), b"b" * 37),
)

#: Чем архив создаётся и во что. 7-Zip не умеет писать RAR — и не нужно:
#: непроверенным оставался РАЗБОРЩИК вывода, а формат `l -slt` у 7-Zip один
#: на все архивы. Читает ли программа именно RAR, выясняется на самом файле
#: во время работы, и знать это заранее не требуется.
PACKING = {
    rar.LIBARCHIVE: ("sample.zip", lambda archive, names: ["-a", "-c", "-f", archive] + names),
    rar.SEVENZIP: ("sample.7z", lambda archive, names: ["a", "-bso0", "-bsp0", archive] + names),
}


def _sample_tree(root):
    for name, payload in SAMPLE:
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)


def _installed(family):
    """Настоящая программа этого семейства, если она есть на машине."""
    rar.reset()
    for tool in rar.discover():
        if tool.family == family:
            return tool
    return None


@pytest.mark.parametrize("family", sorted(PACKING), ids=sorted(PACKING))
def test_listing_is_read_from_a_real_tool(tmp_path, family, monkeypatch):
    """
    Разборщик вывода проверяется на настоящей программе, а не на подставной.

    Подставная печатает то, что я про неё думаю, — и если думаю неверно,
    молчит об этом. Здесь программа сама создаёт архив, сама его перечисляет,
    и наш код читает её настоящий вывод: команда, кодировка, разбор.

    Пропускается, когда программы нет: на машине сборки бывает то одна, то
    другая, и врать про непроверенное хуже, чем пропустить.
    """
    monkeypatch.undo()  # поиск не должен быть изолирован: нужна живая машина
    tool = _installed(family)
    if tool is None:
        pytest.skip("нет программы семейства %s" % family)

    name, arguments = PACKING[family]
    source = tmp_path / "src"
    source.mkdir()
    _sample_tree(str(source))
    archive = str(tmp_path / name)
    packed = subprocess.run(
        tool.command(arguments(archive, [entry for entry, _ in SAMPLE])),
        cwd=str(source), capture_output=True, timeout=60,
    )
    assert packed.returncode == 0, packed.stderr[:400]

    entries = rar.list_entries(tool, archive)

    assert entries is not None, "%s не смогла перечислить собственный архив" % tool.path
    assert {entry.name: entry.size for entry in entries} == {
        name.replace("\\", "/"): len(payload) for name, payload in SAMPLE
    }
