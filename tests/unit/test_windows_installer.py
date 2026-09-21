"""
Сторож установщика Windows.

Собрать MSI на macOS нечем — WiX живёт только на Windows, — поэтому здесь
проверяется то, что видно в исходнике: идентификаторы, которые обязаны быть
настоящими, и регистрация типа файла, которая не должна отбирать чужое.

Оба дефекта тихие. Коллизия GUID проявляется только на машине, где стоит
чужой пакет с тем же кодом, а перехват расширения — только после удаления
приложения, когда .efd остаётся ни с чем.
"""

import pathlib
import re
import xml.etree.ElementTree as ET

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer" / "windows" / "installer.wxs"
WIX = "{http://schemas.microsoft.com/wix/2006/wi}"


def document():
    return ET.parse(INSTALLER).getroot()


def identifiers():
    """Все GUID файла: код семейства продукта и коды компонентов."""
    text = INSTALLER.read_text(encoding="utf-8")
    return re.findall(r'(?:Guid|UpgradeCode)="([0-9A-Fa-f-]{36})"', text)


def test_no_identifier_is_a_tutorial_placeholder():
    """
    Заглушки вида 12345678-… и 11111111-… — самые растиражированные GUID.

    Оба идентификатора глобальны в базе Windows Installer. Чужой пакет с тем
    же UpgradeCode наш MajorUpgrade считает предыдущей версией и сносит; с
    тем же Component GUID — держит счётчик ссылок, и наши ярлыки остаются в
    Пуске после удаления.
    """
    trivial = []
    for value in identifiers():
        digits = value.replace("-", "").lower()
        if len(set(digits)) <= 2 or digits.startswith(("12345678", "87654321")):
            trivial.append(value)

    assert trivial == []


def test_the_product_family_code_is_present_and_fixed():
    """
    UpgradeCode обязан быть, и менять его нельзя после первого релиза.

    Рядом с ним стоит комментарий «не менять никогда» — проверяется и он:
    без объяснения следующий читатель сочтёт код обычным значением.
    """
    text = INSTALLER.read_text(encoding="utf-8")
    product = document().find("%sProduct" % WIX)

    assert product is not None
    assert len(product.get("UpgradeCode") or "") == 36
    assert "НЕ МЕНЯТЬ НИКОГДА" in text


def test_the_extension_default_value_is_left_alone():
    """
    Критерий #17: расширение не отбирается у прежней программы.

    Запись без атрибута Name — это значение по умолчанию ключа. Прежняя
    версия писала туда своё имя типа: при установке затирала чужой
    обработчик, а при удалении уносила значение с собой, потому что Windows
    Installer прежнее не запоминает. На машине с 1С:Предприятием, где .efd
    уже назначен, это ровно тот случай, который и происходит.
    """
    hijack = [
        value for value in document().iter("%sRegistryValue" % WIX)
        if value.get("Key") == ".efd" and value.get("Name") is None
    ]

    assert hijack == []


def test_the_application_registers_itself_as_one_of_the_handlers():
    """Себя в «Открыть с помощью» — вместо захвата расширения."""
    handlers = [
        value for value in document().iter("%sRegistryValue" % WIX)
        if value.get("Key") == ".efd\\OpenWithProgids"
    ]

    assert len(handlers) == 1
    assert handlers[0].get("Name"), "обработчик записан без имени ProgId"


def test_the_package_is_built_and_installed_as_64_bit():
    """
    Exe собирается 64-битным, и пакет обязан быть таким же.

    Без -arch x64 MSI получался 32-битным, ProgramFilesFolder вёл в
    Program Files (x86), и 64-битное приложение оказывалось в каталоге для
    32-битных. Смоук-тест в CI это скрывал, перебирая три пути вместо одного.
    """
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "build-and-release.yml").read_text(
        encoding="utf-8"
    )
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "candle -arch x64 installer/windows/installer_temp.wxs" in makefile
    assert "ProgramFiles64Folder" in installer
    assert re.search(r'Id="ProgramFilesFolder"', installer) is None

    # Проверяется отсутствие ПЕРЕБОРА, а не слов «Program Files (x86)»:
    # они законно встречаются в объяснении рядом, и первая редакция этой
    # проверки ловила собственный комментарий.
    assert "$exeCandidates" not in workflow, "перебор путей вернулся"
    assert r'$exe = "C:\Program Files\EFD Unpacker\EFDUnpacker.exe"' in workflow


@pytest.mark.parametrize(
    "path",
    ["installer/windows/installer.wxs", "installer/windows/bundle.wxs"],
)
def test_the_installer_definitions_are_well_formed(path):
    """
    XML с комментарием посреди списка атрибутов не собирается, а WiX здесь
    нет — значит поймать это можно только так.
    """
    ET.parse(ROOT / path)
