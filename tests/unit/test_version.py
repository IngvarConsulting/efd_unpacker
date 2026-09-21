"""
Сторож версии приложения.

Номер был вписан в исходник руками и расходился бы с релизом на первом же
теге: в окне стояло 2.0.0 независимо от того, что собрали. Теперь он читается
из version.txt, и проверяется здесь именно связь — показанное совпадает с
записанным, а не с ожидаемой строкой.
"""

import pathlib

import pytest

from efd_unpacker.application.help_text import format_help_text
from efd_unpacker import runtime

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Literal:
    def translate(self, _context: str, source: str) -> str:
        return source


@pytest.fixture
def released(tmp_path, monkeypatch):
    """Поставка с записанным номером: version.txt лежит там, где его ищут."""
    (tmp_path / "version.txt").write_text("4.5.6\n", encoding="utf-8")
    monkeypatch.setattr(
        runtime, "resource_path", lambda *parts: str(tmp_path.joinpath(*parts))
    )
    return "4.5.6"


def test_the_version_comes_from_the_file_the_build_writes(released):
    assert runtime.app_version() == released


def test_a_trailing_newline_does_not_reach_the_title(tmp_path, monkeypatch):
    """
    Makefile пишет номер через echo, то есть с переводом строки.

    Необрезанный, он уехал бы прямо в заголовок окна и в подпись шапки.
    """
    (tmp_path / "version.txt").write_text("1.2.3\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "resource_path", lambda *p: str(tmp_path.joinpath(*p)))

    assert runtime.app_version() == "1.2.3"


@pytest.mark.parametrize(
    "content", ["", "   \n"], ids=["пустой", "пробелы"],
)
def test_an_empty_file_does_not_leave_the_version_blank(tmp_path, monkeypatch, content):
    """Пустой version.txt — сорванная сборка, а не версия без номера."""
    (tmp_path / "version.txt").write_text(content, encoding="utf-8")
    monkeypatch.setattr(runtime, "resource_path", lambda *p: str(tmp_path.joinpath(*p)))

    assert runtime.app_version() == runtime.DEV_VERSION


def test_a_checkout_without_a_build_says_so(tmp_path, monkeypatch):
    """
    В рабочем дереве version.txt нет, и это нормально: релиза там тоже нет.

    Показать выдуманный номер было бы хуже, чем сказать «dev», — тем же
    словом подписывает сборку без тега и сам Makefile.
    """
    monkeypatch.setattr(runtime, "resource_path", lambda *p: str(tmp_path.joinpath(*p)))

    assert runtime.app_version() == runtime.DEV_VERSION


def test_the_help_shows_the_version(released):
    assert released in format_help_text(Literal())


def test_the_build_puts_the_file_where_the_application_looks():
    """
    Версия читается в рантайме, значит файл обязан быть в бандле.

    Без него настоящий релиз показывал бы «dev» — ровно та ошибка, от которой
    уходили, только с другой стороны.
    """
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    spec = (ROOT / "installer" / "EFDUnpacker.spec.in").read_text(encoding="utf-8")

    assert makefile.count('--add-data "version.txt$(PYI_DATASEP)."') == 2
    assert '("version.txt", ".")' in spec
