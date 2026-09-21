"""
Правила опознания на настоящих дистрибутивах Linux.

Архивы в репозиторий не кладутся — тринадцать гигабайтов чужих файлов, —
поэтому проверка пропускается, когда их нет под рукой: так она не врёт про
то, чего на машине сборки не было. Ровно так же сделано для установщиков
Windows в tests/unit/test_msi.py.

Имена записей продублированы таблицей CORPUS в tests/unit/test_plan.py и
проверяются в CI всегда. Здесь проверяется то, чего таблица проверить не
может: что она не разошлась с действительностью.

Осмотр zip читает только оглавление, поэтому все четырнадцать архивов —
13 ГБ — проходят за доли секунды и ни одного байта не пишут на диск.
"""

import os
from pathlib import Path

import pytest

from efd_unpacker.application.inspector import inspect_all
from efd_unpacker.domain.plan import ItemKind, PlanSettings, build_plan

DOWNLOADS = Path.home() / "Downloads"

#: Архив и каталог, в который он обязан лечь. Четырнадцать архивов: две
#: версии платформы, четыре архитектуры, оба формата пакетов, установщик и
#: наборы пакетов.
EXPECTED = (
    ("deb64_8_3_27_2342.zip", "platform/8.3.27.2342/server-deb-x86_64"),
    ("deb64_8_5_1_1529.zip", "platform/8.5.1.1529/server-deb-x86_64"),
    ("rpm64_8_5_1_1529.zip", "platform/8.5.1.1529/server-rpm-x86_64"),
    ("server64_8_3_27_2342.zip", "platform/8.3.27.2342/full-x86_64"),
    ("server64_8_5_1_1529.zip", "platform/8.5.1.1529/full-x86_64"),
    ("server64_8_5_4_1683.zip", "platform/8.5.4.1683/full-x86_64"),
    ("server64_with_all_clients_8_5_1_1529.zip",
     "platform/8.5.1.1529/full-all-clients-x86_64"),
    ("thin.client.arm.deb64_8.5.1.1529.zip",
     "platform/8.5.1.1529/thin-client-deb-aarch64"),
    ("thin.client.arm.rpm64_8.5.1.1529.zip",
     "platform/8.5.1.1529/thin-client-rpm-aarch64"),
    ("thin.client.e2k_8c.deb_8.5.1.1529.zip",
     "platform/8.5.1.1529/thin-client-deb-e2k"),
    ("thin.client.e2k_8c.rpm_8.5.1.1529.zip",
     "platform/8.5.1.1529/thin-client-rpm-e2k"),
    ("thin.client64_8_5_1_1529.zip", "platform/8.5.1.1529/thin-client-x86_64"),
    ("thin.client_8_5_1_1529.deb64.zip",
     "platform/8.5.1.1529/thin-client-deb-x86_64"),
    ("thin.client_8_5_1_1529.rpm64.zip",
     "platform/8.5.1.1529/thin-client-rpm-x86_64"),
)


def test_the_expected_folders_are_all_different():
    """
    Сама таблица — утверждение: четырнадцать архивов, четырнадцать каталогов.

    Проверяется всегда, даже без архивов под рукой: опечатка в ожидаемом
    каталоге иначе прошла бы незамеченной там, где вся задача — не дать двум
    дистрибутивам лечь в одно место.
    """
    folders = [folder for _, folder in EXPECTED]

    assert sorted(folders) == sorted(set(folders))


@pytest.mark.parametrize("archive, folder", EXPECTED, ids=[name for name, _ in EXPECTED])
def test_real_linux_distribution_goes_to_its_own_folder(archive, folder):
    path = DOWNLOADS / archive
    if not path.is_file():
        pytest.skip("нет архива %s под рукой" % archive)

    plan = build_plan(
        inspect_all([str(path)]),
        PlanSettings(templates_root=os.sep + "tmplts", distributions_root="/dist"),
    )

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.kind is ItemKind.PLATFORM
    assert item.destination == "/dist/" + folder
