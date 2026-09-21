"""
Сторож лицензирования бинарных сборок.

Код проекта под MIT, а собранные бинарники — под GPL v3: PyQt5 линкуется
внутрь исполняемого файла, и целое наследует его условия. GPL v3 требует,
чтобы текст лицензии ехал ВМЕСТЕ с программой, а не лежал по ссылке, — и
проверяется здесь именно это: что тексты есть и что каждый артефакт их несёт.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Строки, по которым видно, что перед нами настоящий текст, а не заглушка.
#: Берутся из начала и конца — обрезанный файл так не пройдёт.
TEXTS = {
    "licenses/GPL-3.0.txt": (
        "GNU GENERAL PUBLIC LICENSE",
        "Version 3, 29 June 2007",
        "How to Apply These Terms to Your New Programs",
    ),
    "licenses/LGPL-3.0.txt": (
        "GNU LESSER GENERAL PUBLIC LICENSE",
        "Version 3, 29 June 2007",
    ),
    "LICENSE": ("MIT License",),
}

#: Чем в каждой цели доказывается, что тексты попадают в артефакт.
#:
#: Проверяются именно эти строки, а не слово «licenses»: в цели DMG рядом
#: стоит mkdir на ту же папку, и поиск по слову оставался зелёным, даже когда
#: копирование убирали. Пути берутся целиком ещё и потому, что
#: «licenses/GPL-3.0.txt» — НЕ подстрока «licenses/LGPL-3.0.txt», а вот
#: «GPL-3.0.txt» подстрока, и проверка на неё прошла бы при удалённом файле.
ARTIFACT_TARGETS = {
    "build-linux-executable": (
        '--add-data "licenses$(PYI_DATASEP)licenses"',
        '--add-data "LICENSE$(PYI_DATASEP)licenses"',
        '--add-data "build/BUILD-MANIFEST.txt$(PYI_DATASEP)licenses"',
    ),
    "build-windows-executable": (
        '--add-data "licenses$(PYI_DATASEP)licenses"',
        '--add-data "LICENSE$(PYI_DATASEP)licenses"',
        '--add-data "build/BUILD-MANIFEST.txt$(PYI_DATASEP)licenses"',
    ),
    "create-linux-appimage": (
        "licenses/GPL-3.0.txt", "licenses/LGPL-3.0.txt", "build/BUILD-MANIFEST.txt",
    ),
    "create-linux-deb": (
        "licenses/GPL-3.0.txt", "licenses/LGPL-3.0.txt", "build/BUILD-MANIFEST.txt",
    ),
    "create-macos-dmg": (
        "licenses/GPL-3.0.txt", "licenses/LGPL-3.0.txt", "build/BUILD-MANIFEST.txt",
    ),
}


def paragraphs(name: str):
    return (ROOT / name).read_text(encoding="utf-8").split("\n\n")


def makefile_target(name: str) -> str:
    """Тело цели: от её заголовка до первой пустой строки за ним."""
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^%s:.*?(?=\n\n)" % re.escape(name), text, re.S | re.M)
    assert match is not None, "нет цели %s" % name
    return match.group(0)


@pytest.mark.parametrize("path, markers", list(TEXTS.items()), ids=list(TEXTS))
def test_the_full_text_is_in_the_repository(path, markers):
    """Ссылки на gnu.org недостаточно: GPL v3 требует копию рядом с программой."""
    text = (ROOT / path).read_text(encoding="utf-8")

    for marker in markers:
        assert marker in text, "в %s нет строки %r" % (path, marker)


@pytest.mark.parametrize("target, markers", list(ARTIFACT_TARGETS.items()),
                         ids=list(ARTIFACT_TARGETS))
def test_every_artifact_carries_the_license_texts(target, markers):
    """
    Артефакт без текстов лицензий — нарушение условий, на которых его отдают.

    Проверяется по телу конкретной цели, а не по всему Makefile: иначе одна
    уцелевшая строчка где-нибудь прикрывала бы все остальные.
    """
    body = makefile_target(target)

    for marker in markers:
        assert marker in body, "в цели %s нет %r" % (target, marker)


def test_the_macos_app_carries_them_through_the_spec():
    """У .app свой путь: он собирается по спеке, а не строкой --add-data."""
    spec = (ROOT / "installer" / "EFDUnpacker.spec.in").read_text(encoding="utf-8")

    assert 'glob("licenses/*")' in spec
    assert '("LICENSE", "licenses")' in spec


def test_the_windows_installer_puts_them_next_to_the_application():
    """У msi свой путь: файлы перечислены в компоненте WiX."""
    wxs = (ROOT / "installer" / "windows" / "installer.wxs").read_text(encoding="utf-8")

    assert "licenses\\GPL-3.0.txt" in wxs
    assert "licenses\\LGPL-3.0.txt" in wxs


def test_the_installer_promises_the_files_it_actually_installs():
    """
    Экран согласия называет файлы по именам — и эти имена не должны разойтись
    с тем, что установщик кладёт.

    Проверяется соответствие имён, а не формулировка: как именно написан
    абзац, дело редактуры, а вот обещать LICENSE.txt и положить LICENSE —
    это уже обман получателя.
    """
    wxs = (ROOT / "installer" / "windows" / "installer.wxs").read_text(encoding="utf-8")
    rtf = (ROOT / "installer" / "windows" / "license.rtf").read_text(encoding="ascii")

    installed = re.findall(r'Id="License\w+" Name="([^"]+)"', wxs)

    assert set(installed) == {
        "LICENSE.txt", "GPL-3.0.txt", "LGPL-3.0.txt", "BUILD-MANIFEST.txt",
    }, "установщик кладёт не тот набор: %r" % sorted(installed)
    for name in installed:
        assert name in rtf, "установщик кладёт %s, но на экране о нём ни слова" % name


def test_the_installer_license_screen_shows_the_whole_gpl():
    """
    Экран согласия в установщике Windows показывает условия целиком.

    Файл потребляется WiX-бутстраппером как RtfLicense, поэтому он обязан
    оставаться валидным RTF: скобки сбалансированы, текст разбит на \\par.
    Сверяется с самим licenses/GPL-3.0.txt — пересобрали один, а второй
    забыли, и расхождение видно сразу.
    """
    rtf = (ROOT / "installer" / "windows" / "license.rtf").read_text(encoding="ascii")
    gpl = (ROOT / "licenses" / "GPL-3.0.txt").read_text(encoding="ascii")

    assert rtf.count("{") == rtf.count("}")
    assert rtf.startswith("{\\rtf1")
    missing = [line for line in gpl.split("\n") if line and line not in rtf]
    assert missing == [], "в экране лицензии нет строк: %r" % missing[:3]


def test_the_manifest_is_made_before_anything_is_built():
    """
    GPL v3 обещает получателю исходники, СООТВЕТСТВУЮЩИЕ его бинарю.

    Закрепить версии в requirements.txt нельзя: под Windows колесо PyQt5-Qt5
    публикуется только до 5.15.2, под macOS и Linux — новее, и пин на любую
    из них ломает сборку на другой системе (так и вышло: windows-2022 упал на
    «No matching distribution»). Поэтому состав записывается по факту, и
    записан он должен быть ДО того, как собран первый артефакт.
    """
    text = (ROOT / "Makefile").read_text(encoding="utf-8")

    for target in ("build-macos", "build-linux", "build-windows"):
        line = re.search(r"^%s:.*$" % re.escape(target), text, re.M)
        assert line is not None, "нет цели %s" % target
        assert "create-build-manifest" in line.group(0), (
            "%s собирает артефакт, не записав состав" % target
        )


def test_the_manifest_records_the_versions_and_not_just_the_names():
    """
    Манифест без версий бесполезен: имя пакета не даёт исходников.

    pip list --format=freeze печатает «имя==версия»; обычный pip list рисует
    таблицу, и разница между ними — ровно то, ради чего манифест заведён.
    """
    body = makefile_target("create-build-manifest")

    assert "--format=freeze" in body


def test_the_documents_say_what_the_builds_are_licensed_under():
    """
    Человек не обязан лезть в licenses/, чтобы узнать условия.

    Это первое, что спрашивают про поставку, и ответ должен быть в README и
    в документе о лицензиях, а не выводиться из перечня компонентов.
    """
    for name in ("README.md", "docs/LICENSES.md"):
        # Одного «GPL v3» где-нибудь в тексте мало: слово встречается и в
        # перечне компонентов, и в абзаце про то, где лежат тексты. Нужен
        # абзац, который называет САМИ артефакты: их перечисление и есть
        # утверждение «условия относятся к тому, что вы скачали».
        said = [
            block for block in paragraphs(name)
            if "GPL v3" in block and ".AppImage" in block and ".deb" in block
        ]

        assert said, "в %s нет абзаца про лицензию готовых сборок" % name
