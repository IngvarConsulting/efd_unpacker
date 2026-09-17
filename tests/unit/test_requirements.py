"""
Проверка requirements-файлов.

Ни линтер, ни тесты не смотрели на эти файлы, поэтому строка
`PyQt5==5.15.11ruff>=0.6` — результат дописывания в файл без завершающего
перевода строки — доехала до CI и уронила установку зависимостей целиком,
до линтера, тестов и сборки.
"""

from pathlib import Path

import pytest
from packaging.requirements import InvalidRequirement, Requirement

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT_FILES = ["requirements.txt", "requirements-test.txt", "requirements-build.txt"]


def _lines(name: str):
    text = (ROOT / name).read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


@pytest.mark.parametrize("name", REQUIREMENT_FILES)
def test_requirements_file_exists(name):
    assert (ROOT / name).is_file()


@pytest.mark.parametrize("name", REQUIREMENT_FILES)
def test_every_requirement_parses(name):
    broken = []
    for line in _lines(name):
        try:
            Requirement(line)
        except InvalidRequirement as exc:
            broken.append(f"{line!r}: {exc}")

    assert not broken, "\n".join(broken)


@pytest.mark.parametrize("name", REQUIREMENT_FILES)
def test_file_ends_with_newline(name):
    """
    Без завершающего перевода строки следующее `>>` склеит новую зависимость
    с последней строкой — именно так и появился PyQt5==5.15.11ruff>=0.6.
    """
    assert (ROOT / name).read_text(encoding="utf-8").endswith("\n")


def test_pyqt_pin_matches_across_files():
    """Рассинхрон пинов между runtime и тестами даст переустановку в CI."""
    runtime = {Requirement(line).name.lower(): line for line in _lines("requirements.txt")}
    tests = {Requirement(line).name.lower(): line for line in _lines("requirements-test.txt")}

    shared = set(runtime) & set(tests)
    mismatched = [name for name in shared if runtime[name] != tests[name]]

    assert not mismatched, f"разные пины: {[(runtime[n], tests[n]) for n in mismatched]}"
