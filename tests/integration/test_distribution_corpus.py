"""
Правила опознания на настоящих дистрибутивах — Linux и Windows вместе.

Архивы в репозиторий не кладутся — двадцать шесть гигабайтов чужих файлов, —
поэтому проверка пропускается, когда их нет под рукой: так она не врёт про
то, чего на машине сборки не было. Ровно так же сделано для чтения версии из
msi в tests/unit/test_msi.py.

Те же имена записей продублированы таблицей CORPUS в tests/unit/test_plan.py
и проверяются в CI всегда. Здесь проверяется то, чего таблица проверить не
может: что она не разошлась с действительностью.

Осмотр zip читает только оглавление и ни одного байта не пишет на диск;
у rar к этому добавляется чтение версии из msi — три мегабайта из ста сорока.
"""

import os
from pathlib import Path

import pytest

from efd_unpacker.application.inspector import inspect_all
from efd_unpacker.domain.plan import ItemKind, PlanSettings, build_plan
from efd_unpacker.infrastructure import rar

DOWNLOADS = Path.home() / "Downloads"

#: Архив и каталог, в который он обязан лечь. Двадцать четыре дистрибутива:
#: две системы, три версии платформы, четыре архитектуры, оба формата
#: пакетов, установщики и наборы пакетов.
EXPECTED = (
    ("deb64_8_3_27_2342.zip", "platform/8.3.27.2342/linux-server-deb-x86_64"),
    ("deb64_8_5_1_1529.zip", "platform/8.5.1.1529/linux-server-deb-x86_64"),
    ("rpm64_8_5_1_1529.zip", "platform/8.5.1.1529/linux-server-rpm-x86_64"),
    ("server64_8_3_27_2342.zip", "platform/8.3.27.2342/linux-full-x86_64"),
    ("server64_8_5_1_1529.zip", "platform/8.5.1.1529/linux-full-x86_64"),
    ("server64_8_5_4_1683.zip", "platform/8.5.4.1683/linux-full-x86_64"),
    ("server64_with_all_clients_8_5_1_1529.zip",
     "platform/8.5.1.1529/linux-full-all-clients-x86_64"),
    ("thin.client.arm.deb64_8.5.1.1529.zip",
     "platform/8.5.1.1529/linux-thin-client-deb-aarch64"),
    ("thin.client.arm.rpm64_8.5.1.1529.zip",
     "platform/8.5.1.1529/linux-thin-client-rpm-aarch64"),
    ("thin.client.e2k_8c.deb_8.5.1.1529.zip",
     "platform/8.5.1.1529/linux-thin-client-deb-e2k"),
    ("thin.client.e2k_8c.rpm_8.5.1.1529.zip",
     "platform/8.5.1.1529/linux-thin-client-rpm-e2k"),
    ("thin.client64_8_5_1_1529.zip", "platform/8.5.1.1529/linux-thin-client-x86_64"),
    ("thin.client_8_5_1_1529.deb64.zip",
     "platform/8.5.1.1529/linux-thin-client-deb-x86_64"),
    ("thin.client_8_5_1_1529.rpm64.zip",
     "platform/8.5.1.1529/linux-thin-client-rpm-x86_64"),
    ("setuptc64_8_3_27_2342.rar", "platform/8.3.27.2342/windows-thin-client-x86_64"),
    ("setuptc64_8_5_4_1683.rar", "platform/8.5.4.1683/windows-thin-client-x86_64"),
    ("setuptc_8_5_4_1683.rar", "platform/8.5.4.1683/windows-thin-client"),
    ("windows64_8_5_4_1683.rar", "platform/8.5.4.1683/windows-server-x86_64"),
    ("windows64_with_all_clients_8_5_4_1683.rar",
     "platform/8.5.4.1683/windows-server-all-clients-x86_64"),
    ("windows64_with_clients_8_5_4_1683.rar",
     "platform/8.5.4.1683/windows-server-win-mac-clients-x86_64"),
    ("windows64full_8_5_4_1683.rar", "platform/8.5.4.1683/windows-full-x86_64"),
    ("windows64full_with_all_clients_8_5_4_1683.rar",
     "platform/8.5.4.1683/windows-full-all-clients-x86_64"),
    ("windows64full_with_clients_8_5_4_1683.rar",
     "platform/8.5.4.1683/windows-full-win-mac-clients-x86_64"),
    ("windows_8_5_4_1683.rar", "platform/8.5.4.1683/windows-full"),
)


@pytest.fixture(autouse=True)
def keep_the_rar_cache_to_itself(monkeypatch):
    """
    Осмотр .rar заполняет глобальный кэш найденных программ для rar.

    Меню шестерёнки показывает рядом с пунктом количество найденного и пишет
    число только когда поиск уже был — «не знаем, не пишем». Кэш, оставленный
    заполненным, менял текст пункта в чужом тесте: он краснел, и только при
    прогоне всего набора целиком.
    """
    monkeypatch.setattr(rar, "_cache", dict(rar._cache))


def test_the_expected_folders_are_all_different():
    """
    Сама таблица — утверждение: двадцать четыре архива, двадцать четыре
    каталога.

    Проверяется всегда, даже без архивов под рукой: опечатка в ожидаемом
    каталоге иначе прошла бы незамеченной там, где вся задача — не дать двум
    дистрибутивам лечь в одно место.
    """
    folders = [folder for _, folder in EXPECTED]

    assert sorted(folders) == sorted(set(folders))


@pytest.mark.parametrize("archive, folder", EXPECTED, ids=[name for name, _ in EXPECTED])
def test_real_distribution_goes_to_its_own_folder(archive, folder):
    path = DOWNLOADS / archive
    if not path.is_file():
        pytest.skip("нет архива %s под рукой" % archive)
    if archive.lower().endswith(".rar") and not rar.discover():
        pytest.skip("нет программы для rar")

    plan = build_plan(
        inspect_all([str(path)]),
        PlanSettings(templates_root=os.sep + "tmplts", distributions_root="/dist"),
    )

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.kind is ItemKind.PLATFORM
    assert item.destination == "/dist/" + folder
