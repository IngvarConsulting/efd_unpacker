#!/usr/bin/env python3
"""
Описание GitHub Release из CHANGELOG.md.

Раньше описание собиралось из заголовков коммитов, и в него попадали правки
к ещё не выпущенному: «Не печатать дерево 1С трижды» читалось исправлением
того, чего в прошлой версии не было вовсе. Заголовок коммита отвечает на
вопрос «что поменялось в коде с прошлого коммита», а описание релиза — «что
поменялось для человека с прошлого релиза». Это разные вопросы, и из первого
второе не выводится.

Источник описания — раздел CHANGELOG.md с номером тега, написанный руками.
Без него релиз не выходит: лучше упасть на теге, чем опубликовать пересказ
истории git. Скрипт ничего не сочиняет: вырезает раздел и дописывает хвост
про загрузки.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
UNRELEASED = "Unreleased"

#: Заголовок раздела: «## [2.0.0] — 2026-09-21» или «## [Unreleased]».
#: Тире принимается любое — на клавиатуре его набирают по-разному.
SECTION_HEADING = re.compile(
    r"^## \[(?P<version>[^\]]+)\](?:\s*[-—–]\s*(?P<date>\S+))?\s*$"
)
#: Определение ссылки в конце файла: «[2.0.0]: https://…». Не часть раздела.
LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s*\S+")

DOWNLOADS_FOOTER = (
    "## Загрузки\n"
    "\n"
    "Выберите подходящий файл для вашей операционной системы из списка ниже.\n"
    "\n"
    "Для подробных инструкций по установке и использованию см. "
    "[README](https://github.com/IngvarConsulting/efd_unpacker#readme)."
)


@dataclass(frozen=True)
class Section:
    """Раздел CHANGELOG.md: версия, дата из заголовка и тело как есть."""

    version: str
    date: Optional[str]
    body: str


class ReleaseNotesError(Exception):
    """Описание релиза составить нельзя; текст говорит, что сделать."""


def parse_changelog(text: str) -> List[Section]:
    """Разделы в порядке файла. Всё до первого заголовка — преамбула, не раздел."""
    sections: List[Section] = []
    version: Optional[str] = None
    date: Optional[str] = None
    lines: List[str] = []

    def close() -> None:
        if version is not None:
            sections.append(Section(version, date, "\n".join(lines).strip()))

    for line in text.splitlines():
        heading = SECTION_HEADING.match(line)
        if heading:
            close()
            version = heading.group("version")
            date = heading.group("date")
            lines = []
        elif version is not None:
            lines.append(line.rstrip())
    close()
    if sections:
        sections[-1] = without_link_footer(sections[-1])
    return sections


def without_link_footer(section: Section) -> Section:
    """
    Снимает блок определений ссылок, стоящий в самом низу файла.

    Определения вида «[2.0.0]: https://…» относятся ко всему CHANGELOG.md, а
    не к разделу, под которым оказались, поэтому в описание релиза им нельзя.
    Отрезается ровно хвост последнего раздела: определение ВНУТРИ раздела —
    часть его текста, и выбросить его значило бы опубликовать ссылку,
    которой некуда вести.
    """
    body = section.body.splitlines()
    while body and (not body[-1].strip() or LINK_DEFINITION.match(body[-1])):
        body.pop()
    return Section(section.version, section.date, "\n".join(body).strip())


def find_section(sections: List[Section], version: str) -> Optional[Section]:
    for section in sections:
        if section.version == version:
            return section
    return None


def load_changelog() -> List[Section]:
    if not CHANGELOG_PATH.exists():
        raise ReleaseNotesError(f"Нет {CHANGELOG_PATH.name} в корне репозитория.")
    return parse_changelog(CHANGELOG_PATH.read_text(encoding="utf-8"))


def release_notes_for(version: str, sections: List[Section]) -> str:
    """
    Тело GitHub Release для выпущенной версии.

    Пустой раздел — такой же отказ, как отсутствующий: заголовок легко
    завести заранее и забыть наполнить, а релиз с пустым описанием ничем не
    лучше релиза с пересказом коммитов.
    """
    section = find_section(sections, version)
    if section is None:
        raise ReleaseNotesError(
            f"В {CHANGELOG_PATH.name} нет раздела «## [{version}]». "
            f"Опишите, что изменилось для пользователя, и переставьте тег."
        )
    if not section.body:
        raise ReleaseNotesError(
            f"Раздел «## [{version}]» в {CHANGELOG_PATH.name} пуст. "
            f"Опишите, что изменилось для пользователя, и переставьте тег."
        )
    return f"{section.body}\n\n{DOWNLOADS_FOOTER}"


def preview_notes(sections: List[Section]) -> str:
    """Что уйдёт в описание следующего релиза, если тег поставить сейчас."""
    section = find_section(sections, UNRELEASED)
    body = section.body if section else ""
    if not body:
        body = "_Раздел [Unreleased] в CHANGELOG.md пока пуст._"
    return f"{body}\n\n{DOWNLOADS_FOOTER}"


# --- Режим выпуска: тег на HEAD -------------------------------------------


def get_current_tag() -> Optional[str]:
    """Тег на HEAD, если он есть."""
    try:
        result = subprocess.run(
            ["git", "describe", "--exact-match", "--tags", "HEAD"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return None
    return result.stdout.strip() or None


def get_version_from_tag(tag: str) -> str:
    """Извлекает версию из тега, убирая префикс 'v' если есть."""
    return tag[1:] if tag.startswith("v") else tag


# --- Точка входа ------------------------------------------------------------

HELP = """\
Использование:
  python scripts/release_notes.py [--release | --preview]

Описание релиза берётся из CHANGELOG.md, из раздела с номером версии.

  --release  Раздел «## [<версия тега>]». Без тега на HEAD, без раздела или
             с пустым разделом — код возврата 1: релиз не должен выйти.
  --preview  Раздел «## [Unreleased]»: что уйдёт в следующий релиз.

Без опции режим выбирается по тегу на HEAD: есть — --release, нет — --preview.
Служебные строки идут в stderr, само описание — в stdout.
"""


def main(argv: List[str]) -> int:
    mode = None
    if len(argv) > 1:
        option = argv[1]
        if option in ('-h', '--help'):
            print(HELP, end="")
            return 0
        if option in ('--release', '--preview'):
            mode = option[2:]
        else:
            print(f"Неизвестная опция: {option}", file=sys.stderr)
            print("Используйте --help для справки", file=sys.stderr)
            return 1

    try:
        if mode is None:
            mode = "release" if get_current_tag() else "preview"

        sections = load_changelog()
        if mode == "release":
            tag = get_current_tag()
            if not tag:
                raise ReleaseNotesError(
                    "HEAD не помечен тегом: описание выпуска брать не для чего. "
                    "Для следующего релиза используйте --preview."
                )
            version = get_version_from_tag(tag)
            print(f"Режим: выпуск {version}", file=sys.stderr)
            print(release_notes_for(version, sections))
            return 0

        print("Режим: предварительный просмотр [Unreleased]", file=sys.stderr)
        print(preview_notes(sections))
        return 0
    except ReleaseNotesError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
