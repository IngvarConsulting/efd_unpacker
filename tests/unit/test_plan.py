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
         ItemKind.PLATFORM, "8.3.27.2342", "packages", "amd64"),
        (["1cv8-client-8.5.1.1529.pkg", "README.html"],
         ItemKind.PLATFORM, "8.5.1.1529", "client", ""),
        (["postgresql-18_18.4-1.1C_amd64.deb", "libpq5_18.4-1.1C_amd64.deb"],
         ItemKind.PACKAGES, "18.4-1.1C", "packages", "amd64"),
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

    assert plan.items[0].destination == "/dist/platform/8.3.27.2342/full-x86_64"


def test_macos_client_keeps_its_component_in_the_path():
    """Регресс: компонента терялась, и каталог выходил «installer»."""
    plan = build_plan(
        [Inspected(path="/d/macos.client.dmg", files=files("1cv8-client-8.5.1.1529.pkg"))],
        settings(),
    )

    assert plan.items[0].destination == "/dist/platform/8.5.1.1529/client"


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


@pytest.mark.parametrize("name", ["1cv8.cf", "mobileapp.cf", "1cv8.cfu"])
def test_known_configuration_files_keep_the_template(name):
    """
    .cfu — файл обновления, и шаблон из одних обновлений тоже годен.

    Рядом обязательно .dt: без него правило не срабатывает вовсе, и забытое
    расширение осталось бы незамеченным — шаблон писался бы просто потому,
    что знакомого не нашлось ни до фильтра, ни после.
    """
    found = supply("1c/upd/1_0", "1.0",
                   [(name, 900), ("1cv8.dt", 800), ("1cv8.mft", 300)])

    plan = build_plan([Inspected(path="/d/a.zip", supplies=(found,))],
                      settings(only_configuration=True))

    assert plan.items[0].action is Action.WRITE
    assert plan.items[0].bytes_total == 1200, "демобаза всё равно отброшена"


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
