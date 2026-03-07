import importlib.util
from pathlib import Path


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
