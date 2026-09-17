import importlib.util
from pathlib import Path

import pytest


def load_release_notes_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "generate_release_notes.py"
    spec = importlib.util.spec_from_file_location("generate_release_notes", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_git_log_output_preserves_subject_and_body():
    module = load_release_notes_module()

    output = (
        "abc123\x1ffeat: Добавлена функция\x1f"
        "feat: Добавлена функция\n\nПодробности изменения\x1e"
    )

    commits = module.parse_git_log_output(output)

    assert len(commits) == 1
    assert commits[0].commit_hash == "abc123"
    assert commits[0].subject == "feat: Добавлена функция"
    assert "Подробности изменения" in commits[0].body


def test_should_skip_release_notes_for_trailer():
    module = load_release_notes_module()

    commit = module.CommitEntry(
        commit_hash="abc123",
        subject="build(windows): Обновлена временная установка Qt6",
        body="Подробности.\n\nRelease-Notes: skip",
    )

    assert module.should_skip_release_notes(commit) is True


def test_should_skip_release_notes_for_inline_marker():
    module = load_release_notes_module()

    commit = module.CommitEntry(
        commit_hash="abc123",
        subject="build: Обновлена диагностика Qt [skip-release-notes]",
        body="",
    )

    assert module.should_skip_release_notes(commit) is True


def test_filter_service_commits_skips_marked_and_service_entries():
    module = load_release_notes_module()

    commits = [
        module.CommitEntry(
            commit_hash="1111111",
            subject="init: Новый git-репозиторий",
            body="",
        ),
        module.CommitEntry(
            commit_hash="2222222",
            subject="build: Временная диагностика Qt",
            body="Release-Notes: skip",
        ),
        module.CommitEntry(
            commit_hash="3333333",
            subject="fix: Исправлена обработка путей",
            body="",
        ),
    ]

    filtered = module.filter_service_commits(commits)

    assert [commit.subject for commit in filtered] == [
        "fix: Исправлена обработка путей"
    ]


@pytest.mark.parametrize(
    "subject, expected_type, expected_scope",
    [
        ("feat: новая функция", "feat", None),
        ("feat(ui): кнопка", "feat", "ui"),
        # '!' — маркер breaking change, раньше такой коммит уезжал в «Прочие».
        ("feat!: сломали совместимость", "feat", None),
        ("feat(ui)!: сломали совместимость", "feat", "ui"),
        ("fix(macos-arm64): дефис в области", "fix", "macos-arm64"),
        ("build(deps/pip): слэш в области", "build", "deps/pip"),
        ("ci(ui2): цифра в области", "ci", "ui2"),
        ("chore(x.y): точка в области", "chore", "x.y"),
    ],
)
def test_parse_commit_recognises_conventional_subjects(subject, expected_type, expected_scope):
    module = load_release_notes_module()

    commit_type, scope, description, commit_hash = module.parse_commit(f"abc1234 {subject}")

    assert commit_type == expected_type
    assert scope == expected_scope
    assert commit_hash == "abc1234"
    assert description


def test_parse_commit_returns_none_type_for_free_form_subject():
    module = load_release_notes_module()

    commit_type, scope, description, commit_hash = module.parse_commit(
        "abc1234 просто текст без конвенции"
    )

    assert commit_type is None
    assert scope is None
    assert description == "просто текст без конвенции"
    assert commit_hash == "abc1234"


@pytest.mark.parametrize(
    "scope, expected",
    [
        ("cli", "описание (CLI)"),
        ("service", "описание (сервисы)"),
        ("ui", "описание (интерфейс)"),
        ("localization", "описание (локализация)"),
        ("macos", "описание (macOS)"),
        # Неизвестная область не должна добавлять пустых скобок.
        ("unknown-scope", "описание"),
        (None, "описание"),
    ],
)
def test_format_commit_description_maps_known_scopes(scope, expected):
    module = load_release_notes_module()

    assert module.format_commit_description("описание", scope) == expected


def test_scope_mapping_covers_documented_scopes():
    """Словарь областей должен совпадать с docs/COMMIT_CONVENTION.md."""
    module = load_release_notes_module()

    documented = {"cli", "ui", "localization", "service", "installer", "linux", "windows", "macos"}
    missing = documented - set(module.SCOPE_MAPPING)
    assert not missing, f"нет в SCOPE_MAPPING: {sorted(missing)}"


def test_breaking_change_commit_lands_in_its_type_section():
    """Регресс: без поддержки '!' коммит уезжал в «Прочие изменения»."""
    module = load_release_notes_module()

    commit_type, _, description, _ = module.parse_commit("abc1234 feat(cli)!: новый синтаксис")

    assert commit_type in module.TYPE_MAPPING
    assert module.format_commit_description(description, "cli") == "новый синтаксис (CLI)"
