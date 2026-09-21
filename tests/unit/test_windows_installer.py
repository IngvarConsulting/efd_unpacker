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
    # Именно это значение, а не «какой-нибудь GUID из 36 знаков»: смена на
    # другой, столь же настоящий, ломает семейство продукта ровно так же, и
    # проверка на длину этого не заметила бы.
    assert product.get("UpgradeCode") == "24200E4F-43B8-4B51-B5E3-34C8172A128B"
    assert "НЕ МЕНЯТЬ НИКОГДА" in text


def test_only_our_own_registry_keys_are_touched():
    """
    Критерий #17: у расширения не отбирают ни обработчик, ни сведения о нём.

    Под ключом .efd всё общее. Значение по умолчанию — обработчик: прежняя
    версия писала туда своё имя типа, при установке затирая чужое, а при
    удалении унося его с собой, потому что Windows Installer прежнее не
    запоминает. На машине с 1С:Предприятием расширение оставалось ни с чем.

    Именованные значения ничем не лучше: Content Type, который я сперва
    оставил, — та же общая запись, только с именем. Общая база MIME — тоже:
    ключ назван нашим типом, но раздел не наш, и удаление унесло бы чужое
    значение.

    Поэтому проверка перевёрнута: разрешены ровно два места — собственный
    тип EFDUnpacker.efd и подключ .efd\\OpenWithProgids, куда себя
    добавляют. Всё остальное — чужое.
    """
    # Проверяется HKCR — общий раздел классов, где живут чужие ассоциации.
    # Собственные настройки под HKCU\\Software\\EFD Unpacker к делу не
    # относятся: это наше пространство имён, и ничьё больше.
    allowed = ("EFDUnpacker.efd", ".efd\\OpenWithProgids")
    intrusions = [
        value.get("Key") for value in document().iter("%sRegistryValue" % WIX)
        if value.get("Root") == "HKCR" and not value.get("Key", "").startswith(allowed)
    ]

    assert intrusions == []


def test_the_only_placeholder_left_is_the_transitional_one():
    """
    Заглушка допустима ровно в одном месте — в переходном снятии старого
    выпуска, и ровно на один релиз.

    Без него цепочка обновления рвётся: Burn ставит новую цепочку и ТОЛЬКО
    ПОТОМ снимает старый бандл, а удаление старого MSI уносит файлы и
    ярлыки, которые новый уже положил — GUID компонентов сменились, и
    счётчик ссылок их не защищает.
    """
    text = INSTALLER.read_text(encoding="utf-8")
    legacy = "12345678-1234-1234-1234-123456789012"
    upgrade = document().find(".//%sUpgrade" % WIX)

    assert text.count(legacy) == 1, "заглушка встречается не только в переходном блоке"
    assert upgrade is not None and upgrade.get("Id") == legacy
    version = upgrade.find("%sUpgradeVersion" % WIX)
    assert version is not None and version.get("OnlyDetect") == "no", (
        "старый выпуск только обнаруживается, но не снимается"
    )
    assert "Удалить в следующем релизе" in text, "не сказано, что блок временный"

    # Сузить снятие до НАШЕГО продукта нечем: Upgrade различает пакеты по
    # коду семейства, версии и языку, а ProductCode у нас Id="*" — свой у
    # каждой сборки. Единственное, что сужается, — диапазон версий, и он
    # обязан покрывать только реально выпускавшиеся 1.x.
    assert (version.get("Minimum"), version.get("Maximum")) == ("1.0.0", "2.0.0")
    assert version.get("IncludeMaximum") == "no"


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


def test_a_component_with_several_files_names_its_guid():
    """
    Авто-GUID «*» многофайловому компоненту WiX v3 не выдаёт — разве что
    KeyPath у него ВЕРСИОНИРОВАННЫЙ файл, а остальные без версии.

    Exe от PyInstaller версии не несёт: --version-file мы не передаём. Пока
    в компоненте лежал один exe, «*» работал; четыре текста лицензий рядом
    сделали компонент многофайловым, и линковка легла с LGHT0367 — но узналось
    это только через четыре дня, на первой же сборке под Windows. Здесь WiX
    нет, а правило видно в исходнике.
    """
    offenders = []
    for component in document().iter(WIX + "Component"):
        files = component.findall(WIX + "File")
        if len(files) > 1 and component.get("Guid") == "*":
            offenders.append(component.get("Id"))

    assert offenders == [], (
        "многофайловый компонент с авто-GUID, WiX откажет на линковке: %s"
        % ", ".join(offenders)
    )
