import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_release_notes_module():
    script_path = ROOT / "scripts" / "release_notes.py"
    spec = importlib.util.spec_from_file_location("release_notes", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- Описание релиза из CHANGELOG.md ----------------------------------------
#
# Описание берётся из раздела с номером тега, а не из коммитов: заголовок
# коммита говорит, что поменялось с прошлого коммита, а не с прошлого релиза,
# и правка к ещё не выпущенному выглядела в нём исправлением того, чего
# у пользователя никогда не было.

CHANGELOG = """\
# История изменений

Преамбула — не раздел.

## [Unreleased]

- Ещё не выпущено.

## [2.0.0] — 2026-09-21

Абзац.

### Подраздел

- Пункт

## [1.9.0] - 2026-01-01

## [1.8.0]

- Без даты.

[Unreleased]: https://example.test/compare/v2.0.0...HEAD
[2.0.0]: https://example.test/compare/v1.9.0...v2.0.0
""".replace("- Пункт\n", "- Пункт  \n")  # хвостовые пробелы — нарочно, для rstrip


def test_parse_changelog_splits_sections_and_keeps_bodies_verbatim():
    module = load_release_notes_module()

    sections = module.parse_changelog(CHANGELOG)

    assert [section.version for section in sections] == ["Unreleased", "2.0.0", "1.9.0", "1.8.0"]
    assert sections[0].body == "- Ещё не выпущено."
    # Тело — как написано, включая подзаголовки; хвостовые пробелы срезаны.
    assert sections[1].body == "Абзац.\n\n### Подраздел\n\n- Пункт"
    assert sections[1].date == "2026-09-21"


def test_parse_changelog_accepts_any_dash_and_no_date():
    module = load_release_notes_module()

    sections = {section.version: section for section in module.parse_changelog(CHANGELOG)}

    assert sections["1.9.0"].date == "2026-01-01"
    assert sections["1.8.0"].date is None


def test_parse_changelog_drops_link_definitions_from_the_last_section():
    """Определения ссылок в конце файла — не текст последнего раздела."""
    module = load_release_notes_module()

    sections = module.parse_changelog(CHANGELOG)

    assert sections[-1].body == "- Без даты."
    assert "example.test" not in "".join(section.body for section in sections)


def test_release_notes_for_takes_the_tagged_section_and_adds_downloads():
    module = load_release_notes_module()

    notes = module.release_notes_for("2.0.0", module.parse_changelog(CHANGELOG))

    assert notes.startswith("Абзац.\n\n### Подраздел")
    assert "## Загрузки" in notes
    # Чужие разделы не подмешиваются.
    assert "Ещё не выпущено" not in notes
    assert "Без даты" not in notes


@pytest.mark.parametrize("version", ["3.0.0", "1.9.0"])
def test_release_notes_for_refuses_missing_or_empty_section(version):
    """
    Пустой раздел — тот же отказ, что отсутствующий: заголовок легко завести
    заранее и забыть наполнить. Релиз с пустым описанием выйти не должен.
    """
    module = load_release_notes_module()

    with pytest.raises(module.ReleaseNotesError, match=re.escape(f"[{version}]")):
        module.release_notes_for(version, module.parse_changelog(CHANGELOG))


def test_preview_notes_shows_unreleased_or_says_it_is_empty():
    module = load_release_notes_module()

    assert module.preview_notes(module.parse_changelog(CHANGELOG)).startswith("- Ещё не выпущено.")
    assert "пуст" in module.preview_notes(module.parse_changelog("## [Unreleased]\n"))
    assert "пуст" in module.preview_notes([])


def test_release_mode_fails_the_process_without_a_section(monkeypatch, capsys):
    """Ошибка должна дойти до CI кодом возврата, а не только текстом."""
    module = load_release_notes_module()
    monkeypatch.setattr(module, "get_current_tag", lambda: "v3.0.0")
    monkeypatch.setattr(module, "load_changelog", lambda: module.parse_changelog(CHANGELOG))

    code = module.main(["release_notes.py", "--release"])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[3.0.0]" in captured.err


def test_release_mode_prints_only_the_notes_to_stdout(monkeypatch, capsys):
    """Makefile перенаправляет stdout в release_notes.md: служебное — в stderr."""
    module = load_release_notes_module()
    monkeypatch.setattr(module, "get_current_tag", lambda: "v2.0.0")
    monkeypatch.setattr(module, "load_changelog", lambda: module.parse_changelog(CHANGELOG))

    code = module.main(["release_notes.py"])

    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("Абзац.")
    assert "Режим" not in captured.out
    assert "Режим" in captured.err


# --- Настоящий CHANGELOG.md -------------------------------------------------


def real_sections():
    module = load_release_notes_module()
    return module.parse_changelog((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))


def test_changelog_starts_with_unreleased_and_then_descending_versions():
    sections = real_sections()

    assert sections[0].version == "Unreleased"
    versions = [tuple(int(part) for part in section.version.split(".")) for section in sections[1:]]
    assert versions, "должен быть хотя бы один выпущенный раздел"
    assert versions == sorted(versions, reverse=True)
    assert len(set(versions)) == len(versions)


def test_every_released_section_has_a_date_and_a_body():
    for section in real_sections()[1:]:
        assert section.date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", section.date), section.version
        assert section.body, section.version
