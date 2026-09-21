"""
Тесты разбора оглавления .efd.

Главное свойство: узнать состав поставки, не разворачивая её целиком.
У самого большого из исследованных дистрибутивов данные весят 2.96 ГБ,
а оглавление — три килобайта.
"""

import datetime as dt
import io
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain.supply import (
    CATALOG_PREFIX_LIMIT,
    MANIFEST_NAME,
    group_templates,
    parse_catalog,
    readable_name,
    read_catalog,
    version_from_dir,
)
from tests.efd_builder import build_efd

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "1cv8.efd"


def _raw(entries, header=1, supply_info=()):
    """Оглавление без сжатия — то, что видит parse_catalog."""
    head = struct.pack("II", header, len(supply_info))
    for lang, name, provider, description in supply_info:
        head += struct.pack("I", 0)
        for value in (lang, name, provider, description):
            encoded = value.encode("utf-16")
            head += struct.pack("I", len(encoded) // 2) + encoded
    head += struct.pack("I", len(entries))
    for path, filetime, size in entries:
        encoded = path.encode("utf-16")
        head += struct.pack("I", 0) + struct.pack("I", len(encoded) // 2) + encoded
        head += struct.pack("Q", filetime) + struct.pack("I", 0) + struct.pack("I", size)
    return io.BytesIO(head)


FILETIME_2020 = 132223104000000000


# --- разбор ------------------------------------------------------------------


def test_parses_supply_info_and_entries():
    catalog = parse_catalog(
        _raw(
            [("1c\\Trade\\11_6_1_61\\1cv8.cf", FILETIME_2020, 900)],
            supply_info=[("ru", "Управление торговлей", 'Фирма "1С"', "\\1c\\Trade\\ReadMe.txt")],
        )
    )

    assert catalog.header == 1
    assert catalog.supply_info[0].name == "Управление торговлей"
    assert catalog.supply_info[0].provider == 'Фирма "1С"'
    assert catalog.entries[0].size == 900
    assert catalog.entries[0].modified_at == dt.datetime(2020, 1, 1)
    assert catalog.total_bytes == 900


def test_stream_stays_at_the_first_entry_body():
    """Вызывающий код продолжает чтение с данных, не перематывая поток."""
    stream = _raw([("a\\b\\c\\d.txt", FILETIME_2020, 4)])
    stream_with_body = io.BytesIO(stream.getvalue() + b"BODY")

    parse_catalog(stream_with_body)

    assert stream_with_body.read() == b"BODY"


def test_unsupported_header_is_rejected():
    with pytest.raises(UnpackError) as ctx:
        parse_catalog(_raw([], header=2))

    assert ctx.value.details["reason"] == "unsupported_header"


def test_truncated_catalog_is_rejected():
    """
    Короткое чтение — это обрезанное оглавление, а не конец данных.

    Регресс на молчаливый успех: раньше недостающие байты приходили нулями
    и разбирались как мусор.
    """
    full = _raw([("a\\b\\c\\d.txt", FILETIME_2020, 4)]).getvalue()

    with pytest.raises(UnpackError) as ctx:
        parse_catalog(io.BytesIO(full[:-6]))

    assert ctx.value.details["reason"] == "truncated_header"


def test_entry_escaping_the_output_is_rejected_during_parsing():
    """Санирование имён происходит при разборе, а не при записи."""
    with pytest.raises(UnpackError) as ctx:
        parse_catalog(_raw([("..\\..\\escaped.txt", FILETIME_2020, 1)]))

    assert ctx.value.code is UnpackErrorCode.UNSAFE_ENTRY


def test_broken_display_string_does_not_stop_the_scan():
    """Испорченный символ в наименовании — не повод отказывать в осмотре."""
    head = struct.pack("II", 1, 1) + struct.pack("I", 0)
    head += struct.pack("I", 1) + b"\xff\xfe"          # наименование из одного суррогата
    for value in ("x", "y", "z"):
        encoded = value.encode("utf-16")
        head += struct.pack("I", len(encoded) // 2) + encoded
    head += struct.pack("I", 0)

    catalog = parse_catalog(io.BytesIO(head))

    assert catalog.supply_info[0].provider == "y"


# --- выбор языка -------------------------------------------------------------


def test_describe_prefers_russian():
    catalog = parse_catalog(
        _raw([], supply_info=[("en", "Trade", "1C", ""), ("ru", "Торговля", "1С", "")])
    )

    assert catalog.describe().name == "Торговля"


def test_describe_falls_back_over_empty_names():
    """У demo.zip украинское наименование пустое — откат обязателен."""
    catalog = parse_catalog(
        _raw([], supply_info=[("uk", "", "Фiрма", ""), ("en", "Demo", "1C", "")])
    )

    assert catalog.describe("uk").name == "Demo"


def test_describe_without_any_supply_info():
    assert parse_catalog(_raw([])).describe() is None


# --- шаблоны -----------------------------------------------------------------


def test_one_efd_can_carry_several_templates():
    """
    Регресс на моё же неверное утверждение «один .efd — один корень».

    Опровергнуто demo.zip платформы 8.3.27: там два шаблона разных продуктов
    и разных версий в одном .efd.
    """
    catalog = parse_catalog(
        _raw(
            [
                ("1c\\Platform8Demo\\1_0_41_3\\1cv8.dt", FILETIME_2020, 25222858),
                ("1c\\Platform8Demo\\1_0_41_3\\1cv8.mft", FILETIME_2020, 395),
                ("1c\\Platform8DemoMA\\1_0_27\\1cv8.mft", FILETIME_2020, 457),
                ("1c\\Platform8DemoMA\\1_0_27\\mobileapp.cf", FILETIME_2020, 374706),
            ]
        )
    )

    by_path = {template.relative_path: template for template in catalog.templates}
    assert set(by_path) == {"1c/Platform8Demo/1_0_41_3", "1c/Platform8DemoMA/1_0_27"}
    assert by_path["1c/Platform8Demo/1_0_41_3"].version == "1.0.41.3"
    assert by_path["1c/Platform8DemoMA/1_0_27"].version == "1.0.27"
    assert by_path["1c/Platform8Demo/1_0_41_3"].total_bytes == 25223253


def test_entries_at_the_very_root_get_no_template():
    """Записи в корне архива каталога назначения не задают — выдумывать нечего."""
    catalog = parse_catalog(_raw([("ReadMe.txt", FILETIME_2020, 10)]))

    assert catalog.templates == ()
    assert catalog.entries[0].parts == ("ReadMe.txt",)


def test_supply_without_manifest_falls_back_to_the_common_directory():
    """Поставка без манифеста стандарту не следует, но показать её всё равно надо."""
    catalog = parse_catalog(
        _raw(
            [
                ("vendor\\conf\\a.txt", FILETIME_2020, 1),
                ("vendor\\conf\\sub\\b.txt", FILETIME_2020, 1),
            ]
        )
    )

    assert len(catalog.templates) == 1
    assert catalog.templates[0].relative_path == "vendor/conf"
    assert catalog.templates[0].version == ""


def test_deeper_manifest_wins_over_a_shallower_one():
    """Запись принадлежит самому глубокому шаблону, внутри которого лежит."""
    catalog = parse_catalog(
        _raw(
            [
                ("1c\\Conf\\1cv8.mft", FILETIME_2020, 100),
                ("1c\\Conf\\2_0\\1cv8.mft", FILETIME_2020, 100),
                ("1c\\Conf\\2_0\\inner.cf", FILETIME_2020, 7),
            ]
        )
    )

    by_path = {tpl.relative_path: tpl for tpl in catalog.templates}
    assert [e.path for e in by_path["1c/Conf/2_0"].entries] == [
        "1c\\Conf\\2_0\\1cv8.mft",
        "1c\\Conf\\2_0\\inner.cf",
    ]


def test_manifest_beats_depth_when_entries_sit_deeper():
    """
    Случай, на котором фиксированная глубина даёт неверный корень.

    Манифест лежит на втором уровне, а часть записей — на третьем. Считая корень
    по глубине, мы объявили бы шаблоном подкаталог `sub` и потеряли манифест.
    """
    catalog = parse_catalog(
        _raw(
            [
                ("IngvarConsulting\\Test\\1cv8.mft", FILETIME_2020, 171),
                ("IngvarConsulting\\Test\\sub\\deep.txt", FILETIME_2020, 5),
            ]
        )
    )

    assert len(catalog.templates) == 1
    assert catalog.templates[0].relative_path == "IngvarConsulting/Test"
    assert len(catalog.templates[0].entries) == 2


def test_template_root_is_built_from_sanitised_parts():
    """
    Регресс #7: ключи строились из сырых имён, и `a/b` против `./a/b`
    расходились в разные группы.
    """
    catalog = parse_catalog(
        _raw(
            [
                ("1c\\Trade\\11_6_1_61\\1cv8.mft", FILETIME_2020, 1),
                (".\\1c\\Trade\\11_6_1_61\\b.txt", FILETIME_2020, 1),
                ("1c/Trade/11_6_1_61/c.txt", FILETIME_2020, 1),
            ]
        )
    )

    assert len(catalog.templates) == 1
    assert len(catalog.templates[0].entries) == 3


@pytest.mark.parametrize(
    "directory, expected",
    [("2_0_110_66", "2.0.110.66"), ("11_6_1_61", "11.6.1.61"), ("1_0_27", "1.0.27"),
     ("ARAutomation20", "ARAutomation20"), ("2_0_beta", "2_0_beta")],
)
def test_version_from_directory(directory, expected):
    assert version_from_dir(directory) == expected


def test_manifest_name_matches_the_standard():
    """Стандарт #std731 требует 1cv8.mft в каталоге версии."""
    assert MANIFEST_NAME == "1cv8.mft"


def test_group_templates_is_pure():
    """Группировка — чистая функция: её можно звать без файлов и потоков."""
    assert group_templates([]) == ()


# --- ограниченное чтение -----------------------------------------------------


def test_read_catalog_touches_only_the_beginning_of_the_stream():
    """Осмотр обязан быть дешёвым: гигабайты данных не читаются."""
    payload = os.urandom(4 * 1024 * 1024)
    blob = build_efd([("1c\\Trade\\11_6_1_61\\big.bin", payload)])
    handle = io.BytesIO(blob)

    catalog = read_catalog(handle, limit=64 * 1024)

    assert catalog.entries[0].size == len(payload)
    assert handle.tell() < len(blob), "прочитан весь файл вместо начала"


def test_read_catalog_on_the_real_sample():
    """
    У образца всего два каталога вместо трёх, зато есть манифест.

    По фиксированной глубине шаблон бы потерялся — по манифесту находится.
    Версия остаётся пустой: «Test» на номер версии не похож.
    """
    catalog = read_catalog(SAMPLE.open("rb"))

    assert len(catalog.entries) == 4
    assert catalog.templates[0].relative_path == "IngvarConsulting/Test"
    assert catalog.templates[0].version == ""


def test_catalog_larger_than_the_limit_is_named_as_such():
    """Наш предел и порча файла — разные вещи, путать их нельзя."""
    blob = build_efd([("1c\\Trade\\11_6_1_61\\a.txt", b"payload")])

    with pytest.raises(UnpackError) as ctx:
        read_catalog(io.BytesIO(blob), limit=8)

    assert ctx.value.details["reason"] == "catalog_too_large"


def test_truncated_archive_is_not_reported_as_our_limit():
    blob = build_efd([("1c\\Trade\\11_6_1_61\\a.txt", b"payload")])

    with pytest.raises(UnpackError) as ctx:
        read_catalog(io.BytesIO(blob[:12]))

    assert ctx.value.details["reason"] == "truncated_header"


def test_compression_bomb_stops_at_the_limit():
    """Предел заодно и защита: бомба не опасна тому, кто вовремя остановился."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    bomb = compressor.compress(b"\x00" * (200 * 1024 * 1024)) + compressor.flush()

    with pytest.raises(UnpackError) as ctx:
        read_catalog(io.BytesIO(bomb), limit=1024 * 1024)

    assert ctx.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE


def test_default_limit_is_generous_enough_for_real_supplies():
    assert CATALOG_PREFIX_LIMIT >= 1024 * 1024


@pytest.mark.parametrize(
    "data",
    [b"not deflate at all, just bytes", b"\x78\x9c" + b"\xff" * 40, b"\x00" * 64],
    ids=["мусор", "битый поток", "нули"],
)
def test_broken_stream_becomes_a_domain_error(data):
    """
    Регресс: отказ zlib уходил наружу как есть.

    Вызывающий код ловит UnpackError, а не деталь реализации: иначе осмотр
    падал бы zlib.error там, где обрезанный заголовок даёт внятный отказ.
    """
    with pytest.raises(UnpackError) as ctx:
        read_catalog(io.BytesIO(data))

    assert ctx.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE
    assert ctx.value.details["reason"] in {"broken_stream", "truncated_header"}


def test_template_order_does_not_depend_on_the_hash_seed(tmp_path):
    """
    Порядок шаблонов обязан быть одинаковым от запуска к запуску.

    Корни собирались в множество, а множество обходится в порядке хешей строк,
    и они солятся при каждом старте интерпретатора. Вывод `info --json` на одном
    и том же файле получался разным — для сравнения в CI и для потребителя-агента
    это разные ответы на один вопрос.

    Проверяется в отдельных процессах с разными PYTHONHASHSEED: внутри одного
    процесса соль одна, и дефект бы не проявился.
    """
    roots = ["1c/%s/1_0" % name for name in ("Delta", "Alpha", "Echo", "Charlie", "Bravo", "Foxtrot")]
    entries = [(root + "/1cv8.mft", b"m") for root in roots]
    entries += [(root + "/1cv8.cf", b"data") for root in roots]
    archive = tmp_path / "many.efd"
    archive.write_bytes(build_efd(entries))

    script = (
        "import sys;"
        "from efd_unpacker.domain.supply import read_catalog;"
        "handle = open(sys.argv[1], 'rb');"
        "print('|'.join(t.relative_path for t in read_catalog(handle).templates))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")

    orders = set()
    for seed in ("0", "1", "2", "3"):
        env["PYTHONHASHSEED"] = seed
        orders.add(
            subprocess.run(
                [sys.executable, "-c", script, str(archive)],
                capture_output=True, text=True, env=env, check=True,
            ).stdout.strip()
        )

    assert len(orders) == 1, "порядок шаблонов меняется вместе с солью хешей: %s" % orders
    assert orders.pop() == "|".join(sorted(roots))


# --- наименование поставки ---------------------------------------------------
#
# 1С пишет его в .efd как хочет. На девяти настоящих поставках вышло пять
# разных схем, и две из девяти обёрнуты служебным словом с кавычками.


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Обёртка снимается — настоящие наименования из поставок 1С.
        ('конфигурация "Бухгалтерия предприятия КОРП", редакция 3.0',
         "Бухгалтерия предприятия КОРП, редакция 3.0"),
        ('конфигурация "Бухгалтерия государственного учреждения", редакция 2.0',
         "Бухгалтерия государственного учреждения, редакция 2.0"),
        # Та же поставка на других языках: обёртка у каждого своя.
        ('configuration "Accounting CORP", v. 3.0', "Accounting CORP, v. 3.0"),
        ('konfigurācija "Accounting CORP", 3.0 red.', "Accounting CORP, 3.0 red."),
        ('конфігурація "Бухгалтерия предприятия КОРП", ред. 3.0',
         "Бухгалтерия предприятия КОРП, ред. 3.0"),
        # Уже человеческие — не трогаем ни одного знака.
        ("1С:Архив, редакция 1.0", "1С:Архив, редакция 1.0"),
        ("1С:Клиент ЭДО 8, редакция 2.9", "1С:Клиент ЭДО 8, редакция 2.9"),
        ("1С Документооборот КОРП 3.0, редакция 3.0", "1С Документооборот КОРП 3.0, редакция 3.0"),
        ("Комплексная автоматизация, редакция 2", "Комплексная автоматизация, редакция 2"),
        ("Управление торговлей, редакция 11", "Управление торговлей, редакция 11"),
        # Пробелы наружу не уходят.
        ("  Управление торговлей  ", "Управление торговлей"),
        ("", ""),
    ],
)
def test_the_vendor_wrapper_is_taken_off_and_nothing_else(raw, expected):
    assert readable_name(raw) == expected


def test_a_meaningful_prefix_is_not_mistaken_for_the_wrapper():
    """
    «Демонстрационная конфигурация "Управляемое приложение"» остаётся целой.

    Здесь «конфигурация» — часть названия, а не обёртка: сняв её, мы потеряли
    бы «демонстрационная», то есть ровно то, чем эта поставка отличается от
    обычной. Ради этой разницы правило и привязано к НАЧАЛУ строки — на
    настоящем demo.zip платформы 8.3.27 видно, что привязка нужна.
    """
    raw = 'Демонстрационная конфигурация "Управляемое приложение"'

    assert readable_name(raw) == raw
