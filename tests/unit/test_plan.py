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
