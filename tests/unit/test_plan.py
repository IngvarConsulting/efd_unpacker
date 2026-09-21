"""
Тесты опознания вида и построения плана.

Построение плана — чистая функция: файловая система трогается только через
внедряемую проверку «уже установлено». Поэтому вся маршрутизация проверяется
без диска, а правила опознания — списком имён.
"""

import pytest

from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain.plan import (
    Action,
    FoundFile,
    FoundSupply,
    Inspected,
    ItemKind,
    PlanSettings,
    SkipReason,
    build_plan,
    classify,
)
from efd_unpacker.domain.supply import Catalog, Entry, SupplyInfo, Template


def files(*names):
    return tuple(FoundFile(trail=(name,), size=1024) for name in names)


def supply(root, version, entries, name="Управление торговлей", lang="ru"):
    parts = tuple(root.split("/"))
    items = tuple(
        Entry(path="\\".join(parts + (filename,)), parts=parts + (filename,),
              modified_at=None, size=size)
        for filename, size in entries
    )
    template = Template(root=parts, version=version, entries=items)
    catalog = Catalog(
        header=1,
        supply_info=(SupplyInfo(lang=lang, name=name, provider='Фирма "1С"', description_path=""),),
        entries=items,
        templates=(template,),
    )
    return FoundSupply(trail=("dist.zip", "1cv8.efd"), catalog=catalog)


def settings(**kwargs):
    base = dict(templates_root="/tmplts", distributions_root="/dist")
    base.update(kwargs)
    return PlanSettings(**base)


# --- опознание ---------------------------------------------------------------


@pytest.mark.parametrize(
    "names, kind, version, component, arch",
    [
        (["setup-full-8.3.27.2342-x86_64.run", "readme.htm"],
         ItemKind.PLATFORM, "8.3.27.2342", "full", "x86_64"),
        (["1c-enterprise-8.3.27.2342-server_8.3.27-2342_amd64.deb"],
         ItemKind.PLATFORM, "8.3.27.2342", "server-deb", "x86_64"),
        (["1cv8-client-8.5.1.1529.pkg", "README.html"],
         ItemKind.PLATFORM, "8.5.1.1529", "client", ""),
        (["postgresql-18_18.4-1.1C_amd64.deb", "libpq5_18.4-1.1C_amd64.deb"],
         ItemKind.PACKAGES, "18.4-1.1C", "packages-deb", "x86_64"),
        (["1cv8.dt"], ItemKind.CONTENT, "", "", ""),
        (["1cv8_en.cf", "1cv8_demo_en.dt"], ItemKind.CONTENT, "", "", ""),
        (["photo.jpg", "notes.txt"], ItemKind.OTHER, "", "", ""),
    ],
    ids=["установщик Linux", "пакеты платформы", "клиент macOS", "postgres",
         "демобаза", "библиотека", "неизвестное"],
)
def test_classification_by_content(names, kind, version, component, arch):
    found = classify(files(*names))

    assert found.kind is kind
    assert found.version == version
    assert found.component == component
    assert found.arch == arch


def test_deb_version_is_read_by_naming_convention():
    """
    Регресс: общая регулярка захватывала «18.4-1.1C_amd64.deb» целиком.

    У deb и rpm имя устроено как <имя>_<версия>_<архитектура>, и версия
    берётся оттуда, а не поиском по всей строке.
    """
    assert classify(files("postgresql-18_18.4-1.1C_amd64.deb")).version == "18.4-1.1C"


def test_platform_rule_wins_over_the_generic_package_rule():
    """Пакеты платформы опознаются как платформа, а не как безымянный набор."""
    found = classify(files("1c-enterprise-8.3.27.2342-server_8.3.27-2342_amd64.deb"))

    assert found.kind is ItemKind.PLATFORM


# --- маршрутизация ------------------------------------------------------------


def test_supply_goes_to_the_templates_root():
    plan = build_plan(
        [Inspected(path="/d/Trade.zip", supplies=(supply("1c/trade/11_6_1_61", "11.6.1.61",
                                                        [("1cv8.cf", 900), ("1cv8.mft", 171)]),))],
        settings(),
    )

    item = plan.items[0]
    assert item.kind is ItemKind.SUPPLY
    assert item.destination == "/tmplts/1c/trade/11_6_1_61"
    assert item.title == "Управление торговлей"
    assert item.version == "11.6.1.61"
    assert item.bytes_total == 1071


def test_distribution_goes_to_the_distributions_root():
    plan = build_plan(
        [Inspected(path="/d/server64.zip", files=files("setup-full-8.3.27.2342-x86_64.run"))],
        settings(),
    )

    assert plan.items[0].destination == "/dist/platform/8.3.27.2342/linux-full-x86_64"


def test_macos_client_keeps_its_component_in_the_path():
    """Регресс: компонента терялась, и каталог выходил «installer»."""
    plan = build_plan(
        [Inspected(path="/d/macos.client.dmg", files=files("1cv8-client-8.5.1.1529.pkg"))],
        settings(),
    )

    assert plan.items[0].destination == "/dist/platform/8.5.1.1529/macos-client"


def test_an_already_unpacked_distribution_is_skipped():
    """
    Та же мерка, что у шаблонов: каталог есть — значит уже распаковано.

    Без этой проверки план обещал записать 192 МБ поверх того, что уже
    лежит, и делал это при каждом запуске. У шаблонов проверка была с самого
    начала, у дистрибутивов её не было вовсе.
    """
    inspected = Inspected(
        path="/d/thin.client.zip",
        files=files("1c-enterprise-8.5.1.1529-thin-client_8.5.1-1529_arm64.deb"),
    )
    installed = "/dist/platform/8.5.1.1529/linux-thin-client-deb-aarch64"

    item = build_plan([inspected], settings(is_installed=lambda path: path == installed)).items[0]

    assert item.action is Action.SKIP
    assert item.reason is SkipReason.ALREADY_INSTALLED
    assert item.destination == installed


def test_a_skipped_distribution_stays_in_the_plan_with_its_size():
    """
    Пропущенное не исчезает из списка: человек должен видеть, что файл
    осмотрен, куда он поехал бы и почему не поехал.

    Молча выбросить строку значило бы потерять исходный файл из плана
    целиком — той же ошибкой, что уже ловили на поставке без шаблонов.
    """
    inspected = Inspected(
        path="/d/thin.client.zip",
        files=files("1c-enterprise-8.5.1.1529-thin-client_8.5.1-1529_arm64.deb"),
    )

    plan = build_plan([inspected], settings(is_installed=lambda _path: True))

    assert len(plan.items) == 1
    assert plan.items[0].bytes_total == 1024
    assert plan.to_write == ()


@pytest.mark.parametrize(
    "names, why",
    [
        (["notes.txt", "photo.jpg"], "«other/<имя файла>» берётся из имени входного файла"),
        (["1cv8_en.cf"], "«content/<имя файла>» — тоже"),
        (["1CEnterprise 8.msi", "Data1.cab"], "версия не прочиталась, каталог «unknown»"),
    ],
    ids=["прочее", "содержимое", "без версии"],
)
def test_an_ambiguous_destination_is_not_taken_for_an_installed_one(names, why):
    """
    «Каталог есть» значит «уже распаковано» только там, где адрес опознаёт
    содержимое.

    Два разных архива с одинаковым именем из разных папок дают один и тот же
    «other/<имя файла>»: второй молча пропустился бы, хотя внутри у него
    другое. То же и с «platform/unknown/…».
    """
    inspected = Inspected(path="/d/foo.zip", files=files(*names))

    item = build_plan([inspected], settings(is_installed=lambda _path: True)).items[0]

    assert item.action is Action.WRITE, why


def test_a_distribution_without_its_folder_is_still_written():
    """Проверка не должна пропускать то, чего на диске нет."""
    inspected = Inspected(
        path="/d/thin.client.zip",
        files=files("1c-enterprise-8.5.1.1529-thin-client_8.5.1-1529_arm64.deb"),
    )

    item = build_plan([inspected], settings()).items[0]

    assert item.action is Action.WRITE
    assert item.reason is None


def test_library_without_efd_goes_to_content():
    """«Распаковать исходники без efd» — форма SSL_Ru_En.zip."""
    plan = build_plan(
        [Inspected(path="/d/SSL_Ru_En.zip", files=files("1cv8_en.cf", "1cv8_demo_en.dt"))],
        settings(),
    )

    assert plan.items[0].kind is ItemKind.CONTENT
    assert plan.items[0].destination == "/dist/content/SSL_Ru_En"


def test_one_efd_with_two_templates_gives_two_rows():
    """Строка плана — это шаблон, а не файл: demo.zip даёт две."""
    first = supply("1c/Platform8Demo/1_0_41_3", "1.0.41.3", [("1cv8.dt", 10)])
    second = supply("1c/Platform8DemoMA/1_0_27", "1.0.27", [("mobileapp.cf", 20)])
    merged = FoundSupply(
        trail=first.trail,
        catalog=Catalog(header=1, supply_info=first.catalog.supply_info,
                        entries=first.catalog.entries + second.catalog.entries,
                        templates=first.catalog.templates + second.catalog.templates),
    )

    plan = build_plan([Inspected(path="/d/demo.zip", supplies=(merged,))], settings())

    assert [item.destination for item in plan.items] == [
        "/tmplts/1c/Platform8Demo/1_0_41_3",
        "/tmplts/1c/Platform8DemoMA/1_0_27",
    ]


def test_destination_parts_are_sanitised():
    """
    Имена внутри архива — чужие данные, и каталог назначения строится из них.

    Без санирования `../../etc` в имени уехал бы прямо в путь.
    """
    with pytest.raises(UnpackError) as ctx:
        build_plan(
            [Inspected(path="/d/evil.zip", files=files("../../etc/passwd.deb"))],
            settings(),
        )

    assert ctx.value.code is UnpackErrorCode.UNSAFE_ENTRY


# --- пропуски -----------------------------------------------------------------


def test_already_installed_is_skipped():
    plan = build_plan(
        [Inspected(path="/d/Trade.zip", supplies=(supply("1c/trade/11_6_1_61", "11.6.1.61",
                                                         [("1cv8.cf", 900)]),))],
        settings(is_installed=lambda destination: destination == "/tmplts/1c/trade/11_6_1_61"),
    )

    assert plan.items[0].action is Action.SKIP
    assert plan.items[0].reason is SkipReason.ALREADY_INSTALLED
    assert plan.bytes_to_write == 0


def test_demo_base_filter_drops_dt_and_shrinks_the_volume():
    """
    Один выбор решает половину вопроса «сколько это займёт»: на восьми
    поставках .cf это 50.5% объёма, .dt — 48.3%.
    """
    found = supply("1c/trade/11_6_1_61", "11.6.1.61", [("1cv8.cf", 900), ("1cv8.dt", 800)])

    full = build_plan([Inspected(path="/d/t.zip", supplies=(found,))], settings())
    filtered = build_plan(
        [Inspected(path="/d/t.zip", supplies=(found,))],
        settings(only_configuration=True),
    )

    assert full.items[0].bytes_total == 1700
    assert filtered.items[0].bytes_total == 900
    assert filtered.items[0].action is Action.WRITE


def test_supply_of_only_demo_base_is_filtered_out_entirely():
    found = supply("1c/demo/1_0", "1.0", [("1cv8.dt", 800)])

    plan = build_plan([Inspected(path="/d/t.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.SKIP
    assert plan.items[0].reason is SkipReason.FILTERED_OUT


def test_template_left_without_a_configuration_is_skipped():
    """
    Шаблон, у которого фильтр унёс единственную конфигурацию, не пишется.

    Записанный, он оказывается каталогом с манифестом и ReadMe — и в 1С
    выглядит пунктом, который ничего не создаёт: человек узнаёт об этом уже
    там, без намёка на причину. Настоящий случай: Platform8Demo/1_0_41_3 из
    demo.zip платформы 8.3.27.
    """
    found = supply("1c/Platform8Demo/1_0_41_3", "1.0.41.3",
                   [("1cv8.dt", 24_000_000), ("1cv8.mft", 395), ("ReadMe.txt", 1200)])

    plan = build_plan([Inspected(path="/d/demo.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.SKIP
    assert plan.items[0].reason is SkipReason.FILTERED_OUT
    assert plan.bytes_to_write == 0


def test_the_same_template_is_written_when_the_filter_is_off():
    """Без фильтра брать нечего: шаблон полон и годен."""
    found = supply("1c/Platform8Demo/1_0_41_3", "1.0.41.3",
                   [("1cv8.dt", 24_000_000), ("1cv8.mft", 395), ("ReadMe.txt", 1200)])

    plan = build_plan([Inspected(path="/d/demo.zip", supplies=(found,))], settings())

    assert plan.items[0].action is Action.WRITE


def test_template_with_both_files_survives_the_filter():
    """
    У «Комплексной автоматизации» в шаблоне и .cf, и .dt.

    Фильтр уносит демобазу, конфигурация остаётся — и шаблон обязан
    записаться, иначе правило било бы по тому, ради чего фильтр и включают.
    """
    found = supply("1c/ARAutomation20/2_6_1_61", "2.6.1.61",
                   [("1cv8.cf", 900), ("1cv8.dt", 800), ("1cv8.mft", 482)])

    plan = build_plan([Inspected(path="/d/a.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.WRITE
    assert plan.items[0].bytes_total == 1382


@pytest.mark.parametrize("name", ["1cv8.cf", "mobileapp.cf", "1cv8.cfu", "payload.bin"])
def test_anything_but_documentation_keeps_the_template(name):
    """
    Уцелело содержимое — шаблон пишется, каким бы оно ни было.

    Списка «из чего 1С делает базу» здесь нет намеренно: его пришлось бы
    угадывать, и ошибка означала бы молча выброшенный шаблон. Поэтому
    перечислено сопровождение, а всё прочее считается содержимым — включая
    .cfu и вовсе незнакомое.

    Рядом обязательно .dt: без него фильтр ничего не уносит, и правило не
    срабатывает вовсе — проверять было бы нечего.
    """
    found = supply("1c/upd/1_0", "1.0",
                   [(name, 900), ("1cv8.dt", 800), ("1cv8.mft", 300)])

    plan = build_plan([Inspected(path="/d/a.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.WRITE
    assert plan.items[0].bytes_total == 1200, "демобаза всё равно отброшена"


def test_template_the_filter_never_touched_is_written():
    """
    Правило не судит о шаблоне, к которому фильтр не прикасался.

    Поставка из одного манифеста и описания для 1С бесполезна и так, но это
    не наша новость и не повод терять её молча.
    """
    found = supply("1c/пусто/1_0", "1.0", [("1cv8.mft", 300), ("ReadMe.txt", 100)])

    plan = build_plan([Inspected(path="/d/a.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.WRITE


def test_template_without_any_known_configuration_is_still_written():
    """
    Правило нарочно одностороннее: оно замечает, что фильтр унёс всё, а не
    решает, годен ли шаблон вообще.

    Незнакомый вид поставки не должен пропадать молча: ошибиться в сторону
    лишней записи здесь безопаснее, чем в сторону тишины.
    """
    found = supply("1c/странное/1_0", "1.0",
                   [("payload.bin", 900), ("1cv8.mft", 300)])

    plan = build_plan([Inspected(path="/d/a.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.WRITE


def test_unknown_payload_survives_next_to_a_filtered_demo_base():
    """
    Незнакомый файл рядом с демобазой — и шаблон всё равно пишется.

    Демобазу фильтр унёс, но `payload.bin` уцелел, и, быть может, он-то и
    есть то, ради чего шаблон нужен. Правило «не осталось знакомой
    конфигурации» выбрасывало его молча; правило «не осталось ничего, кроме
    сопровождения» — нет.
    """
    found = supply("1c/странное/1_0", "1.0",
                   [("payload.bin", 900), ("1cv8.dt", 800), ("1cv8.mft", 300)])

    plan = build_plan([Inspected(path="/d/a.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.WRITE
    assert plan.items[0].bytes_total == 1200, "демобаза всё равно отброшена"


@pytest.mark.parametrize(
    "extra",
    ["ReadMe.txt", "Версии библиотек.txt", "описание.html", "Изменения.pdf", "инструкция.doc"],
)
def test_documentation_alone_does_not_save_the_template(extra):
    """
    Сопровождение базу не делает: манифест, ReadMe, документация.

    Ровно из них и состоял каталог Platform8Demo/1_0_41_3 после «без демобаз»
    — и 1С показывала по нему пункт, который ничего не создаёт.
    """
    found = supply("1c/demo/1_0", "1.0",
                   [("1cv8.dt", 800), ("1cv8.mft", 300), (extra, 100)])

    plan = build_plan([Inspected(path="/d/a.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.SKIP
    assert plan.items[0].reason is SkipReason.FILTERED_OUT


def test_unsupported_container_becomes_a_skip_row():
    """Молча терять файл нельзя: отказ осмотра — тоже строка плана."""
    failure = UnpackError(UnpackErrorCode.CONTAINER_UNSUPPORTED, {"kind": "rar"})

    plan = build_plan([Inspected(path="/d/setuptc64.rar", failure=failure)], settings())

    assert plan.items[0].action is Action.SKIP
    assert plan.items[0].reason is SkipReason.RAR_TOOL_MISSING
    assert plan.items[0].title == "setuptc64.rar"


def test_other_unsupported_container_keeps_its_own_reason():
    failure = UnpackError(UnpackErrorCode.CONTAINER_UNSUPPORTED, {"kind": "dmg"})

    plan = build_plan([Inspected(path="/d/image.dmg", failure=failure)], settings())

    assert plan.items[0].reason is SkipReason.CONTAINER_UNSUPPORTED


def test_empty_container_is_reported_not_dropped():
    plan = build_plan([Inspected(path="/d/empty.zip")], settings())

    assert plan.items[0].reason is SkipReason.NOTHING_FOUND


# --- сводка -------------------------------------------------------------------


def test_plan_sums_only_what_will_be_written():
    plan = build_plan(
        [
            Inspected(path="/d/a.zip", supplies=(supply("1c/a/1_0", "1.0", [("1cv8.cf", 100)]),)),
            Inspected(path="/d/b.rar",
                      failure=UnpackError(UnpackErrorCode.CONTAINER_UNSUPPORTED, {"kind": "rar"})),
        ],
        settings(),
    )

    assert len(plan.items) == 2
    assert len(plan.to_write) == 1
    assert plan.bytes_to_write == 100


def test_planning_never_touches_the_filesystem(tmp_path, monkeypatch):
    """
    Построение плана — чистая функция.

    Диск трогается только через внедряемую is_installed; всё остальное
    сделало бы маршрутизацию непроверяемой без файлов.
    """
    monkeypatch.chdir(tmp_path)
    build_plan(
        [Inspected(path="/d/a.zip", supplies=(supply("1c/a/1_0", "1.0", [("1cv8.cf", 1)]),))],
        settings(),
    )

    assert list(tmp_path.iterdir()) == []


# --- находки обзора ----------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [UnpackErrorCode.CORRUPTED_ARCHIVE, UnpackErrorCode.NESTING_TOO_DEEP,
     UnpackErrorCode.UNSAFE_ENTRY, UnpackErrorCode.TOO_MANY_ENTRIES,
     UnpackErrorCode.PERMISSION],
    ids=lambda code: code.name,
)
def test_inspection_failure_is_not_disguised_as_a_skip(code):
    """
    Регресс: любой отказ осмотра превращался в пропуск «формат не поддержан».

    Хуже всего выглядел UNSAFE_ENTRY — архив, пытавшийся выйти за каталог
    распаковки, показывался как рядовой пропуск, а план казался исполнимым.
    """
    failure = UnpackError(code, {"entry": "x"})

    plan = build_plan([Inspected(path="/d/x.zip", failure=failure)], settings())

    item = plan.items[0]
    assert item.action is Action.FAIL
    assert item.reason is None
    assert item.failure is failure
    assert len(plan.failed) == 1


@pytest.mark.parametrize(
    "kind, reason",
    [("rar", SkipReason.RAR_TOOL_MISSING), ("dmg", SkipReason.CONTAINER_UNSUPPORTED)],
)
def test_unsupported_format_stays_an_expected_skip(kind, reason):
    """«Формат не поддержан» — ожидаемый исход, а не отказ, требующий решения."""
    failure = UnpackError(UnpackErrorCode.CONTAINER_UNSUPPORTED, {"kind": kind})

    plan = build_plan([Inspected(path="/d/x", failure=failure)], settings())

    assert plan.items[0].action is Action.SKIP
    assert plan.items[0].reason is reason
    assert plan.failed == ()


def test_supply_without_templates_keeps_its_row():
    """
    Регресс: поставка без шаблонов исчезала из плана целиком.

    Оглавление прочитано, но устанавливать нечего — строка всё равно нужна,
    иначе исходный файл молча пропадает.
    """
    from efd_unpacker.domain.supply import Catalog as EmptyCatalog

    empty = FoundSupply(trail=("odd.zip", "1cv8.efd"),
                        catalog=EmptyCatalog(header=1, supply_info=(), entries=(), templates=()))

    plan = build_plan([Inspected(path="/d/odd.zip", supplies=(empty,))], settings())

    assert len(plan.items) == 1
    assert plan.items[0].action is Action.SKIP
    assert plan.items[0].reason is SkipReason.NO_TEMPLATES
    assert plan.items[0].source == ("odd.zip", "1cv8.efd")


@pytest.mark.parametrize(
    "name, version",
    [
        ("postgresql18-server-18.4-1PGDG.rhel9.x86_64.rpm", "18.4-1PGDG.rhel9"),
        ("postgresql18-server-18.5-1PGDG.rhel9.x86_64.rpm", "18.5-1PGDG.rhel9"),
        ("libpq5-18.4-1.1C.noarch.rpm", "18.4-1.1C"),
        ("postgresql-18_18.4-1.1C_amd64.deb", "18.4-1.1C"),
    ],
    ids=["rpm 18.4", "rpm 18.5", "rpm noarch", "deb"],
)
def test_package_version_follows_the_naming_convention(name, version):
    """
    Регресс: у rpm подчёркиваний нет вовсе, и deb-правило давало пустую
    версию — разные выпуски сходились в один каталог «unknown».
    """
    assert classify(files(name)).version == version


def test_different_rpm_releases_do_not_share_a_destination():
    first = build_plan(
        [Inspected(path="/d/a.zip", files=files("postgresql18-server-18.4-1PGDG.rhel9.x86_64.rpm"))],
        settings(),
    )
    second = build_plan(
        [Inspected(path="/d/b.zip", files=files("postgresql18-server-18.5-1PGDG.rhel9.x86_64.rpm"))],
        settings(),
    )

    assert first.items[0].destination != second.items[0].destination


def test_file_count_follows_the_filter():
    """
    Число файлов берётся после фильтра, а не до.

    Длина template.entries показала бы больше, чем план собирается писать:
    под --only cf выгрузки .dt отсеиваются.
    """
    found = supply("1c/a/1_0", "1.0", [("1cv8.cf", 100), ("1cv8.dt", 200), ("readme.txt", 5)])

    full = build_plan([Inspected(path="/d/t.zip", supplies=(found,))], settings())
    only_cf = build_plan(
        [Inspected(path="/d/t.zip", supplies=(found,))],
        settings(only_configuration=True),
    )

    assert full.items[0].file_count == 3
    assert only_cf.items[0].file_count == 2, "запись .dt попала в счёт вопреки фильтру"


# --- установщик платформы под Windows ----------------------------------------


@pytest.mark.parametrize(
    "msi, component, arch, title",
    [
        ("1CEnterprise 8 Thin client (x86-64).msi", "thin-client", "x86_64",
         "Платформа 1С:Предприятия для Windows, тонкий клиент"),
        ("1CEnterprise 8 Thin client.msi", "thin-client", "",
         "Платформа 1С:Предприятия для Windows, тонкий клиент"),
        ("1CEnterprise 8 Server (x86-64).msi", "server", "x86_64",
         "Платформа 1С:Предприятия для Windows, сервер"),
        ("1CEnterprise 8 (x86-64).msi", "full", "x86_64",
         "Платформа 1С:Предприятия для Windows"),
        ("1CEnterprise 8.msi", "full", "", "Платформа 1С:Предприятия для Windows"),
    ],
    ids=["тонкий-64", "тонкий-32", "сервер-64", "полный-64", "полный-32"],
)
def test_windows_installer_is_recognised_by_the_msi_name(msi, component, arch, title):
    """
    Критерий #63: установщик опознаётся как платформа с компонентой.

    Все пять форм имени взяты из настоящих архивов. Имя самого архива при
    этом не смотрится принципиально: windows64_* — это СЕРВЕР, а не
    64-битный клиент, и опознание по имени архива соврало бы.
    """
    found = classify(files(msi, "Data1.cab", "setup.exe"))

    assert found.kind is ItemKind.PLATFORM
    assert (found.component, found.arch, found.title) == (component, arch, title)


@pytest.mark.parametrize(
    "bundle, component, title",
    [
        ("all-clients-distr_8.5.4.1683.exe", "server-all-clients",
         "Платформа 1С:Предприятия для Windows, сервер, со всеми клиентами"),
        ("win-mac-clients-distr_8.5.4.1683.exe", "server-win-mac-clients",
         "Платформа 1С:Предприятия для Windows, сервер, с клиентами Windows и macOS"),
    ],
    ids=["все-клиенты", "win-mac"],
)
def test_bundled_clients_get_their_own_folder(bundle, component, title):
    """
    Три серверных архива дают ОДНО И ТО ЖЕ имя msi.

    windows64_, windows64_with_clients_ и windows64_with_all_clients_
    различаются только вложенным установщиком клиентов; Data1.cab у всех
    трёх одинаковый. Без этого различия они легли бы в один каталог и
    затёрли бы друг друга — притом что весят 950 МБ, 1.6 и 2.5 ГБ.
    """
    found = classify(files("1CEnterprise 8 Server (x86-64).msi", "Data1.cab", bundle))

    assert (found.component, found.title) == (component, title)


def test_plain_server_has_no_bundle_in_its_folder():
    found = classify(files("1CEnterprise 8 Server (x86-64).msi", "Data1.cab", "setup.exe"))

    assert found.component == "server"


@pytest.mark.parametrize(
    "names",
    [
        ["OpenOffice 4 (x86-64).msi", "Data1.cab"],
        ["setup.msi", "Data1.cab"],
        ["Data1.cab", "setup.exe", "1049.mst"],
    ],
    ids=["чужой msi", "msi без имени продукта", "без msi вовсе"],
)
def test_foreign_installer_still_goes_to_other(names):
    """Критерий #63: не подошедшее ни под одно правило не угадывается."""
    assert classify(files(*names)).kind is ItemKind.OTHER


def test_version_read_from_the_msi_reaches_the_plan():
    """
    В именах записей версии нет ни у одного из десяти архивов — её приносит
    слой осмотра, прочитав содержимое msi.
    """
    inspected = Inspected(
        path="/d/windows64full_8_5_4_1683.rar",
        files=files("1CEnterprise 8 (x86-64).msi", "Data1.cab"),
        platform_version="8.5.4.1683",
    )

    item = build_plan([inspected], settings()).items[0]

    assert item.version == "8.5.4.1683"
    assert item.destination.endswith("platform/8.5.4.1683/windows-full-x86_64")


def test_missing_version_does_not_break_the_recognition():
    """
    Версию прочитать не удалось — вид, комплектация и разрядность всё равно
    опознаны: каталог просто окажется без номера.
    """
    inspected = Inspected(
        path="/d/windows64full.rar",
        files=files("1CEnterprise 8 (x86-64).msi", "Data1.cab"),
    )

    item = build_plan([inspected], settings()).items[0]

    assert item.kind is ItemKind.PLATFORM
    assert item.destination.endswith("platform/unknown/windows-full-x86_64")


# --- дистрибутивы Linux -------------------------------------------------------


@pytest.mark.parametrize(
    "run, component, title",
    [
        ("setup-full-8.5.1.1529-x86_64.run", "full", "Платформа 1С:Предприятия для Linux"),
        ("setup-thin-8.5.1.1529-x86_64.run", "thin-client",
         "Платформа 1С:Предприятия для Linux, тонкий клиент"),
    ],
    ids=["полный", "тонкий клиент"],
)
def test_run_installer_names_its_own_component(run, component, title):
    """
    Комплектация читается из имени .run, а не зашита в правило.

    Пока правило требовало ровно «setup-full-», thin.client64_*.zip —
    полгигабайта — уезжал в «прочее» целиком.
    """
    found = classify(files(run, "installAsRoot", "readme.htm"))

    assert found.kind is ItemKind.PLATFORM
    assert found.component == component
    assert found.version == "8.5.1.1529"
    assert found.arch == "x86_64"
    assert found.title == title


def test_bundled_clients_are_recognised_next_to_a_run_installer():
    """
    server64_ и server64_with_all_clients_ содержат ОДИН И ТОТ ЖЕ
    setup-full-*.run — байт в байт, до размера записи.

    Отличает их только вложенный установщик клиентов, ровно как под Windows.
    Без него два архива, 1.8 ГБ и 3.3 ГБ, легли бы в один каталог.
    """
    found = classify(files("setup-full-8.5.1.1529-x86_64.run",
                           "all-clients-distr-8.5.1.1529-x86_64.run"))

    assert found.component == "full-all-clients"


def test_a_run_file_that_is_not_an_installer_is_not_a_platform():
    """
    Правило расширено по комплектации, а не по расширению.

    Вложенный установщик клиентов — тоже .run, и сам по себе платформой не
    является: «не знаю» обязано остаться «не знаю».
    """
    found = classify(files("all-clients-distr-8.5.1.1529-x86_64.run"))

    assert found.kind is ItemKind.OTHER


#: Серверный набор: четыре назначения в одном архиве, у каждого ещё и
#: языковой пакет.
SERVER_DEB = (
    "1c-enterprise-8.5.1.1529-common-nls_8.5.1-1529_amd64.deb",
    "1c-enterprise-8.5.1.1529-common_8.5.1-1529_amd64.deb",
    "1c-enterprise-8.5.1.1529-server-nls_8.5.1-1529_amd64.deb",
    "1c-enterprise-8.5.1.1529-server_8.5.1-1529_amd64.deb",
    "1c-enterprise-8.5.1.1529-ws_8.5.1-1529_amd64.deb",
    "1c-enterprise-8.5.1.1529-crs_8.5.1-1529_amd64.deb",
)
THIN_DEB = (
    "1c-enterprise-8.5.1.1529-thin-client-nls_8.5.1-1529_amd64.deb",
    "1c-enterprise-8.5.1.1529-thin-client_8.5.1-1529_amd64.deb",
    "v8-install-deps.sh",
)
THIN_RPM = (
    "1c-enterprise-8.5.1.1529-thin-client-8.5.1-1529.x86_64.rpm",
    "1c-enterprise-8.5.1.1529-thin-client-nls-8.5.1-1529.x86_64.rpm",
)


def test_package_set_is_named_by_its_principal_role():
    """
    Назначение бралось из первого попавшегося пакета — то есть «common».

    Common лежит в КАЖДОМ наборе и потому не различает ничего: серверный
    набор и набор тонкого клиента получали одно имя каталога.
    """
    assert classify(files(*SERVER_DEB)).component == "server-deb"


def test_thin_client_role_is_not_cut_in_half():
    """Регресс: ленивая общая регулярка отрезала от «thin-client» только «thin»."""
    assert classify(files(*THIN_DEB)).component == "thin-client-deb"


def test_language_packages_do_not_change_the_role_of_a_set():
    """
    Рядом с server_*.deb всегда лежит server-nls_*.deb — это тот же сервер.

    Отдельного разбора «-nls» в правиле нет: во всех четырнадцати архивах
    языковой пакет лежит рядом со своим основным, и старшинство находит
    основной само.
    """
    found = classify(files(
        "1c-enterprise-8.5.1.1529-server-nls_8.5.1-1529_amd64.deb",
        "1c-enterprise-8.5.1.1529-server_8.5.1-1529_amd64.deb",
    ))

    assert found.component == "server-deb"


def test_a_language_package_alone_does_not_pretend_to_be_its_base():
    """
    Отрезать «-nls» было бы прямо вредно, и это стоит держать проверенным.

    Языковой пакет без основного — это не серверный набор, и каталог
    настоящего серверного набора он занимать не имеет права.
    """
    alone = classify(files("1c-enterprise-8.5.1.1529-server-nls_8.5.1-1529_amd64.deb"))

    assert alone.component != classify(files(*SERVER_DEB)).component


def test_an_unknown_package_set_is_named_by_everything_in_it():
    """
    Незнакомый набор не имеет права слиться с другим незнакомым.

    Старшее назначение среди незнакомых угадывать нечем, поэтому в имя
    каталога идут все: так два разных набора расходятся, а не перемешиваются.
    """
    one = classify(files("1c-enterprise-9.0.0.1-quantum_9.0.0-1_amd64.deb"))
    two = classify(files("1c-enterprise-9.0.0.1-quantum_9.0.0-1_amd64.deb",
                         "1c-enterprise-9.0.0.1-photon_9.0.0-1_amd64.deb"))

    assert one.component == "quantum-deb"
    assert two.component == "photon-quantum-deb"


def test_deb_and_rpm_of_one_release_do_not_share_a_folder():
    """
    Формат пакетов в имени каталога обязателен.

    Один выпуск приходит и в deb, и в rpm; назначение, версия и — после
    приведения написаний — архитектура у них совпадают до буквы. Без формата
    два разных набора легли бы в один каталог и перемешались.
    """
    assert classify(files(*THIN_DEB)).component != classify(files(*THIN_RPM)).component


@pytest.mark.parametrize(
    "deb, rpm",
    [
        ("1c-enterprise-8.5.1.1529-thin-client_8.5.1-1529_amd64.deb",
         "1c-enterprise-8.5.1.1529-thin-client-8.5.1-1529.x86_64.rpm"),
        ("1c-enterprise-8.5.1.1529-thin-client_8.5.1-1529_arm64.deb",
         "1c-enterprise-8.5.1.1529-thin-client-8.5.1-1529.aarch64.rpm"),
    ],
    ids=["amd64 и x86_64", "arm64 и aarch64"],
)
def test_one_architecture_is_written_one_way(deb, rpm):
    """
    deb и rpm называют одно и то же железо по-разному.

    Разные написания разводили один выпуск по двум каталогам — ровно как
    «x86-64» против «x86_64» в имени msi.
    """
    assert classify(files(deb)).arch == classify(files(rpm)).arch


def test_packages_of_one_kind_keep_their_format_too():
    """
    Правило одно на все наборы пакетов, не только на пакеты платформы.

    После приведения amd64 к x86_64 набор deb и набор rpm одного продукта
    различать стало бы нечем.
    """
    deb = classify(files("postgresql-18_18.4-1.1C_amd64.deb"))
    rpm = classify(files("postgresql-18-18.4-1.1C.x86_64.rpm"))

    assert deb.arch == rpm.arch
    assert deb.component != rpm.component


# --- система дистрибутива -----------------------------------------------------


def test_linux_and_windows_installers_do_not_share_a_folder():
    """
    Комплектации всех систем названы одинаково, и это сделано нарочно:
    «1CEnterprise 8.msi» и setup-full-*.run — один и тот же полный комплект.

    Но, сведя названия, мы убрали последнее, чем система себя выдавала:
    полный установщик Linux 8.5.4.1683 (1.8 ГБ) и полный установщик Windows
    той же версии (1.2 ГБ) совпадали по комплектации, версии и разрядности
    разом и ложились в один каталог.
    """
    linux = Inspected(
        path="/d/server64_8_5_4_1683.zip",
        files=files("setup-full-8.5.4.1683-x86_64.run", "installAsRoot"),
    )
    windows = Inspected(
        path="/d/windows64full_8_5_4_1683.rar",
        files=files("1CEnterprise 8 (x86-64).msi", "Data1.cab"),
        platform_version="8.5.4.1683",
    )

    plan = build_plan([linux, windows], settings())

    assert plan.items[0].destination != plan.items[1].destination


def test_two_systems_do_not_read_as_the_same_row():
    """
    Каталоги разошлись, но человек смотрит в строку плана, а не в путь.

    Без системы в заголовке две строки читались бы слово в слово одинаково —
    и разное место назначения выглядело бы ошибкой программы.
    """
    linux = classify(files("setup-full-8.5.4.1683-x86_64.run"))
    windows = classify(files("1CEnterprise 8 (x86-64).msi", "Data1.cab"))

    assert linux.title != windows.title


@pytest.mark.parametrize(
    "names, system",
    [
        (["setup-full-8.5.4.1683-x86_64.run"], "linux"),
        (["1c-enterprise-8.5.1.1529-server_8.5.1-1529_amd64.deb"], "linux"),
        (["1cv8-client-8.5.1.1529.pkg"], "macos"),
        (["1CEnterprise 8 (x86-64).msi", "Data1.cab"], "windows"),
    ],
    ids=["установщик Linux", "пакеты Linux", "macOS", "Windows"],
)
def test_the_rule_that_matched_names_the_system(names, system):
    """Систему задаёт правило, по которому архив опознан, а не имя архива."""
    assert classify(files(*names)).system == system


def test_a_third_party_package_set_gets_no_system():
    """
    Чужому набору пакетов система не нужна и не ставится.

    Он назван продуктом и форматом, и двух систем под одним таким именем не
    бывает: «linux-» в имени каталога сказало бы ровно то, что уже сказано
    словом «deb».
    """
    found = classify(files("postgresql-18_18.4-1.1C_amd64.deb"))

    assert found.system == ""
    assert found.component == "packages-deb"


#: Настоящий корпус: двадцать четыре дистрибутива — четырнадцать Linux и
#: десять Windows, три версии платформы, четыре архитектуры, оба формата
#: пакетов. Имена записей взяты из архивов как есть: на выдуманных правила не
#: выводятся, почти каждый дефект виден только на ПАРЕ архивов, а не на одном.
#:
#: Третьим полем идёт версия платформы: у Windows её в именах записей нет
#: вовсе, и в план её приносит слой осмотра, прочитав содержимое msi.
CORPUS = (
    ("deb64_8_3_27_2342.zip", (
        "1c-enterprise-8.3.27.2342-common-nls_8.3.27-2342_amd64.deb",
        "1c-enterprise-8.3.27.2342-common_8.3.27-2342_amd64.deb",
        "1c-enterprise-8.3.27.2342-server-nls_8.3.27-2342_amd64.deb",
        "1c-enterprise-8.3.27.2342-server_8.3.27-2342_amd64.deb",
        "1c-enterprise-8.3.27.2342-ws-nls_8.3.27-2342_amd64.deb",
        "1c-enterprise-8.3.27.2342-ws_8.3.27-2342_amd64.deb",
        "1c-enterprise-8.3.27.2342-crs_8.3.27-2342_amd64.deb",
    ), ""),
    ("deb64_8_5_1_1529.zip", SERVER_DEB, ""),
    ("rpm64_8_5_1_1529.zip", (
        "1c-enterprise-8.5.1.1529-common-8.5.1-1529.x86_64.rpm",
        "1c-enterprise-8.5.1.1529-common-nls-8.5.1-1529.x86_64.rpm",
        "1c-enterprise-8.5.1.1529-server-8.5.1-1529.x86_64.rpm",
        "1c-enterprise-8.5.1.1529-server-nls-8.5.1-1529.x86_64.rpm",
        "1c-enterprise-8.5.1.1529-ws-8.5.1-1529.x86_64.rpm",
        "1c-enterprise-8.5.1.1529-crs-8.5.1-1529.x86_64.rpm",
    ), ""),
    ("server64_8_3_27_2342.zip", ("setup-full-8.3.27.2342-x86_64.run", "installAsRoot"), ""),
    ("server64_8_5_1_1529.zip", ("setup-full-8.5.1.1529-x86_64.run", "installAsRoot"), ""),
    ("server64_8_5_4_1683.zip", ("setup-full-8.5.4.1683-x86_64.run", "installAsRoot"), ""),
    ("server64_with_all_clients_8_5_1_1529.zip", (
        "setup-full-8.5.1.1529-x86_64.run", "installAsRoot",
        "all-clients-distr-8.5.1.1529-x86_64.run",
    ), ""),
    ("thin.client.arm.deb64_8.5.1.1529.zip", (
        "1c-enterprise-8.5.1.1529-thin-client-nls_8.5.1-1529_arm64.deb",
        "1c-enterprise-8.5.1.1529-thin-client_8.5.1-1529_arm64.deb",
    ), ""),
    ("thin.client.arm.rpm64_8.5.1.1529.zip", (
        "1c-enterprise-8.5.1.1529-thin-client-8.5.1-1529.aarch64.rpm",
        "1c-enterprise-8.5.1.1529-thin-client-nls-8.5.1-1529.aarch64.rpm",
    ), ""),
    ("thin.client.e2k_8c.deb_8.5.1.1529.zip", (
        "1c-enterprise-8.5.1.1529-thin-client-nls_8.5.1-1529_e2k-8c.deb",
        "1c-enterprise-8.5.1.1529-thin-client_8.5.1-1529_e2k-8c.deb",
    ), ""),
    ("thin.client.e2k_8c.rpm_8.5.1.1529.zip", (
        "1c-enterprise-8.5.1.1529-thin-client-8.5.1-1529.e2k.rpm",
        "1c-enterprise-8.5.1.1529-thin-client-nls-8.5.1-1529.e2k.rpm",
    ), ""),
    ("thin.client64_8_5_1_1529.zip", ("setup-thin-8.5.1.1529-x86_64.run", "installAsRoot"), ""),
    ("thin.client_8_5_1_1529.deb64.zip", THIN_DEB, ""),
    ("thin.client_8_5_1_1529.rpm64.zip", THIN_RPM, ""),
    ("setuptc64_8_3_27_2342.rar", (
        "setup.exe", "1CEnterprise 8 Thin client (x86-64).msi", "Data1.cab",
    ), "8.3.27.2342"),
    ("setuptc64_8_5_4_1683.rar", (
        "setup.exe", "1CEnterprise 8 Thin client (x86-64).msi", "Data1.cab",
    ), "8.5.4.1683"),
    ("setuptc_8_5_4_1683.rar", (
        "1CEnterprise 8 Thin client.msi", "setup.exe", "Data1.cab",
    ), "8.5.4.1683"),
    ("windows64_8_5_4_1683.rar", (
        "vc_redist.x64.exe", "setup.exe", "Data1.cab",
        "1CEnterprise 8 Server (x86-64).msi",
    ), "8.5.4.1683"),
    ("windows64_with_all_clients_8_5_4_1683.rar", (
        "vc_redist.x64.exe", "setup.exe", "all-clients-distr_8.5.4.1683.exe",
        "Data1.cab", "1CEnterprise 8 Server (x86-64).msi",
    ), "8.5.4.1683"),
    ("windows64_with_clients_8_5_4_1683.rar", (
        "vc_redist.x64.exe", "win-mac-clients-distr_8.5.4.1683.exe", "setup.exe",
        "Data1.cab", "1CEnterprise 8 Server (x86-64).msi",
    ), "8.5.4.1683"),
    ("windows64full_8_5_4_1683.rar", (
        "vc_redist.x64.exe", "setup.exe", "Data1.cab", "1CEnterprise 8 (x86-64).msi",
    ), "8.5.4.1683"),
    ("windows64full_with_all_clients_8_5_4_1683.rar", (
        "vc_redist.x64.exe", "setup.exe", "all-clients-distr_8.5.4.1683.exe",
        "Data1.cab", "1CEnterprise 8 (x86-64).msi",
    ), "8.5.4.1683"),
    ("windows64full_with_clients_8_5_4_1683.rar", (
        "vc_redist.x64.exe", "win-mac-clients-distr_8.5.4.1683.exe", "setup.exe",
        "Data1.cab", "1CEnterprise 8 (x86-64).msi",
    ), "8.5.4.1683"),
    ("windows_8_5_4_1683.rar", (
        "setup.exe", "Data1.cab", "vc_redist.x86.exe", "1CEnterprise 8.msi",
    ), "8.5.4.1683"),
)


def corpus_plan():
    return build_plan(
        [
            Inspected(path="/d/%s" % name, files=files(*names), platform_version=version)
            for name, names, version in CORPUS
        ],
        settings(),
    )


def test_no_two_archives_share_a_folder():
    """
    Главное требование: распаковать все двадцать четыре — и ничего не
    перемешать.

    Пар, ложившихся в один каталог, набралось пять. Четыре внутри Linux:
    deb-набор сервера поверх deb-набора тонкого клиента, то же в rpm, deb и
    rpm эльбруса вместе и оба серверных архива 8.5.1.1529. Пятая — между
    системами: полный установщик Linux и полный установщик Windows версии
    8.5.4.1683 совпадали по комплектации, версии и разрядности разом.
    """
    destinations = [item.destination for item in corpus_plan().items]

    assert sorted(destinations) == sorted(set(destinations))


def test_every_archive_is_recognised():
    """Ни один из двадцати четырёх не уезжает в «прочее»."""
    unrecognised = [item.origin for item in corpus_plan().items if item.kind is ItemKind.OTHER]

    assert unrecognised == []
