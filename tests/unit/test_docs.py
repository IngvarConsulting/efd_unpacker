"""
Сторож документации.

Проверяется не содержание, а то, что документ вообще доходит до читателя:
ссылка на удалённый файл даёт 404 ровно в той точке, с которой начинают
знакомство с проектом.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Ссылка вида [текст](цель). Якоря, протоколы и почта отсеиваются: здесь
#: проверяются только файлы репозитория.
LINK = re.compile(r"\]\(([^)]+)\)")


def documents():
    return [ROOT / "README.md"] + sorted((ROOT / "docs").rglob("*.md"))


def test_every_relative_link_points_at_something():
    """
    Регресс #20: README и BUILD.md ссылались на удалённый документ.

    Проверяется обходом, а не списком известных ссылок: список пришлось бы
    обновлять руками, а это ровно та работа, про которую и забыли.
    """
    broken = []
    for document in documents():
        text = document.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = (document.parent / target.split("#")[0]).resolve()
            if not path.exists():
                broken.append("%s → %s" % (document.relative_to(ROOT), target))

    assert broken == []


def test_the_documentation_index_is_not_empty():
    """
    Обход проверяет цели, но не то, что ссылки вообще есть.

    Снести весь список из README — и предыдущий тест останется зелёным,
    потому что проверять станет нечего.
    """
    index = (ROOT / "README.md").read_text(encoding="utf-8")

    assert len([link for link in LINK.findall(index) if link.startswith("docs/")]) >= 5
