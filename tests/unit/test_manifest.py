"""
Тесты чтения 1cv8.mft.

Разбор проверен на четырёх настоящих манифестах: три из скачанных поставок 1С
(«Комплексная автоматизация» 2.6.1.61, демонстрационная конфигурация 1.0.41.3,
демонстрационное мобильное приложение 1.0.27) и один из нашей собственной
фикстуры tests/data/1cv8.efd. Сами поставки в репозиторий не кладутся — это
полтора гигабайта чужих файлов, — но фикстура распаковывается здесь и читается
по-настоящему.

Про кодировки. Все четыре оказались UTF-8 с BOM; cp1251 в живом виде мне не
попался, и проверен он собранным файлом. Это честная разница в уверенности,
и она отражена в названиях тестов.
"""

import os
from pathlib import Path

import pytest

from efd_unpacker.domain import manifest

ROOT = Path(__file__).resolve().parents[2]

#: Форма настоящего манифеста: ключи до первой секции, CRLF, две секции, из
#: которых вторая — демонстрационная база в .dt.
REAL_SHAPE = (
    'Vendor=Фирма "1С"\r\n'
    "Name=КомплекснаяАвтоматизация\r\n"
    "Version=2.6.1.61\r\n"
    "AppVersion=8.3\r\n"
    "[Config1]\r\n"
    "Catalog=1С:Комплексная автоматизация 2/Комплексная автоматизация 2\r\n"
    "Destination=1C\\ARAutomation20\r\n"
    "Source=1cv8.cf\r\n"
    "[Config2]\r\n"
    "Catalog=1С:Комплексная автоматизация 2/Комплексная автоматизация 2 (демо)\r\n"
    "Destination=1C\\DemoARAutomation20\r\n"
    "Source=1cv8.dt\r\n"
)


def write(directory, text, encoding="utf-8-sig", name=manifest.NAME):
    path = Path(directory) / name
    path.write_bytes(text.encode(encoding))
    return str(directory)


# --- разбор ------------------------------------------------------------------


def test_keys_before_the_first_section_are_read():
    """
    Ключи манифеста идут ДО первой секции, и это не мелочь.

    configparser на такой файл отвечает MissingSectionHeaderError и не отдаёт
    ничего — ни заголовка, ни секций.
    """
    parsed = manifest.parse(REAL_SHAPE)

    assert parsed.vendor == 'Фирма "1С"'
    assert parsed.name == "КомплекснаяАвтоматизация"
    assert parsed.version == "2.6.1.61"


def test_every_config_section_is_read():
    """Секций бывает несколько: конфигурация и демобаза — разные пункты в 1С."""
    parsed = manifest.parse(REAL_SHAPE)

    assert [config.source for config in parsed.configs] == ["1cv8.cf", "1cv8.dt"]
    assert parsed.configs[1].destination == "1C\\DemoARAutomation20"


def test_catalog_is_shown_as_the_tree_1c_draws():
    """`Catalog` — это путь в дереве 1С: группа и элемент в ней."""
    parsed = manifest.parse(REAL_SHAPE)

    assert parsed.configs[0].title == (
        "1С:Комплексная автоматизация 2 → Комплексная автоматизация 2"
    )


def test_section_without_a_catalog_is_not_a_configuration():
    """Секция без Catalog не описывает пункт в 1С, и показывать по ней нечего."""
    parsed = manifest.parse("[Config1]\nSource=1cv8.cf\n[Config2]\nCatalog=Имя\n")

    assert [config.catalog for config in parsed.configs] == ["Имя"]


@pytest.mark.parametrize(
    "text",
    ["", "мусор без единого знака равенства", "[Config1]", "=значение без ключа"],
    ids=["пусто", "мусор", "пустая секция", "без ключа"],
)
def test_unreadable_text_gives_an_empty_manifest_not_an_error(text):
    """Манифест — украшение: он не имеет права поднимать исключение."""
    assert not manifest.parse(text)


def test_comments_and_blank_lines_are_skipped():
    parsed = manifest.parse("; комментарий\n\n# ещё\n[Config1]\nCatalog=Имя\n")

    assert [config.catalog for config in parsed.configs] == ["Имя"]


def test_value_with_an_equals_sign_survives():
    """Знак равенства в значении встречается, и делить надо по первому."""
    parsed = manifest.parse("[C]\nCatalog=Отчётность 1С:БГУ 2.0 = основная\n")

    assert parsed.configs[0].catalog == "Отчётность 1С:БГУ 2.0 = основная"


# --- кодировки ---------------------------------------------------------------


def test_utf8_with_bom_is_read(tmp_path):
    """
    Так выглядят все четыре манифеста, которые удалось посмотреть живьём.

    BOM обязан сниматься: иначе первым ключом станет «﻿Vendor», и ни одно
    поле заголовка не найдётся.
    """
    parsed = manifest.read(write(tmp_path, REAL_SHAPE, "utf-8-sig"))

    assert parsed.vendor == 'Фирма "1С"'


def test_utf8_without_bom_is_read(tmp_path):
    parsed = manifest.read(write(tmp_path, REAL_SHAPE, "utf-8"))

    assert parsed.name == "КомплекснаяАвтоматизация"


def test_cp1251_is_read(tmp_path):
    """
    Кодировка из задачи #67. Настоящей поставки с ней мне не попалось —
    файл собран здесь, и это проверка разборщика, а не наблюдение.

    Порядок кодировок важен: cp1251 принимает почти любой байт и ошибки не
    даёт никогда, поэтому строгий UTF-8 обязан идти первым — иначе кириллица
    из UTF-8 молча превратилась бы в «ÐšÐ¾Ð¼Ð¿».
    """
    parsed = manifest.read(write(tmp_path, REAL_SHAPE, "cp1251"))

    assert parsed.vendor == 'Фирма "1С"'
    assert parsed.configs[0].title.startswith("1С:Комплексная автоматизация 2")


def test_utf8_is_not_mistaken_for_cp1251(tmp_path):
    """Обратная сторона порядка: UTF-8 не должен читаться как cp1251."""
    parsed = manifest.read(write(tmp_path, REAL_SHAPE, "utf-8"))

    assert "Ð" not in parsed.vendor


def test_undecodable_bytes_do_not_lose_the_whole_manifest(tmp_path):
    """Одна испорченная буква лучше, чем пустая строка вместо описания."""
    path = tmp_path / manifest.NAME
    path.write_bytes(b"[C]\nCatalog=\xff\xfe\xfd name\n")

    parsed = manifest.read(str(tmp_path))

    assert parsed.configs and "name" in parsed.configs[0].catalog


# --- чтение с диска ----------------------------------------------------------


def test_missing_manifest_is_not_a_failure(tmp_path):
    """Критерий #67: отсутствующий манифест не влияет на исход распаковки."""
    assert not manifest.read(str(tmp_path))


def test_manifest_that_cannot_be_read_is_not_a_failure(tmp_path, monkeypatch):
    """
    Критерий #67: битый или недоступный манифест не влияет на исход.

    Распаковка к этому моменту уже состоялась, и уронить её из-за украшения —
    худшее, что может сделать чтение манифеста.
    """
    write(tmp_path, REAL_SHAPE)

    def refuse(*_args, **_kwargs):
        raise OSError("нет прав")

    monkeypatch.setattr("builtins.open", refuse)

    assert not manifest.read(str(tmp_path))


def test_a_directory_named_like_the_manifest_is_survived(tmp_path):
    """Каталог с именем 1cv8.mft читается как файл — и отвечает отказом."""
    (tmp_path / manifest.NAME).mkdir()

    assert not manifest.read(str(tmp_path))


def test_huge_file_is_not_read_into_memory(tmp_path):
    """
    Настоящие манифесты — от 171 до 482 байт.

    Однофамилец на сотню мегабайт читаться целиком не должен: строка Catalog
    этого не стоит.
    """
    path = tmp_path / manifest.NAME
    path.write_bytes(b"x" * (manifest.SIZE_LIMIT + 1))

    assert not manifest.read(str(tmp_path))


# --- что действительно легло на диск -----------------------------------------


def test_only_configurations_whose_file_exists_are_promised(tmp_path):
    """
    С «без демобаз» файл .dt не пишется вовсе.

    Обещать демонстрационную базу в 1С значило бы соврать ровно там, где
    человек пойдёт её искать — в списке при создании базы.
    """
    write(tmp_path, REAL_SHAPE)
    (tmp_path / "1cv8.cf").write_bytes(b"x")

    parsed = manifest.read(str(tmp_path))

    assert [config.source for config in parsed.configs] == ["1cv8.cf", "1cv8.dt"]
    assert [config.source for config in parsed.delivered(str(tmp_path))] == ["1cv8.cf"]


def test_nothing_is_promised_when_no_configuration_was_written(tmp_path):
    """
    Шаблон, у которого единственная конфигурация — .dt, при «без демобаз»
    остаётся каталогом с манифестом и без единого файла для 1С. Так и
    показываем: ничего не появится.
    """
    write(tmp_path, "[Config1]\nCatalog=Демо\nSource=1cv8.dt\n")

    assert not manifest.read(str(tmp_path)).delivered(str(tmp_path))


def test_configuration_without_a_source_is_kept(tmp_path):
    """Манифест не сказал, из чего конфигурация берётся, — проверять нечего."""
    write(tmp_path, "[Config1]\nCatalog=Имя\n")

    assert len(manifest.read(str(tmp_path)).delivered(str(tmp_path))) == 1


# --- настоящий манифест из фикстуры ------------------------------------------


def test_real_manifest_from_the_bundled_supply(tmp_path):
    """
    Критерий #67: строка Catalog прочитана из настоящей поставки.

    Фикстура распаковывается по-настоящему, а не подкладывается текстом:
    манифест приезжает из .efd тем же путём, что и у пользователя.
    """
    from efd_unpacker.domain.unpack_service import UnpackService

    UnpackService().unpack(str(ROOT / "tests" / "data" / "1cv8.efd"), str(tmp_path))
    template = next(
        os.path.join(current) for current, _dirs, files in os.walk(str(tmp_path))
        if manifest.NAME in files
    )

    parsed = manifest.read(template)

    assert parsed.vendor == "Ingvar Consulting, LLC"
    assert [config.title for config in parsed.configs] == ["Test", "Test (демо)"]
    assert len(parsed.delivered(template)) == 2, "оба файла распакованы, оба и обещаны"
