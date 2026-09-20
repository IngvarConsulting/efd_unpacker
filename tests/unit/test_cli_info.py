"""
Тесты команды info.

Осмотр здесь подменён: команда отвечает за разбор аргументов, выбор путей,
код возврата и выбор формата — за это и спрашиваем. Что именно находит осмотр,
проверяется в test_inspector.py.
"""

import json

import pytest

from efd_unpacker.application.cli import CLIApplication, terminal_progress
from efd_unpacker.constants import CLICommands
from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain.plan import FoundFile, FoundSupply, Inspected
from efd_unpacker.domain.supply import Catalog, Entry, SupplyInfo, Template


class DummyTranslator:
    def translate(self, _context, source):
        return source


def _template(root=("1c", "Acc", "3_0_1"), size=1024):
    entries = (Entry(path="/".join(root) + "/1cv8.cf", parts=root + ("1cv8.cf",),
                     modified_at=None, size=size),)
    return Template(root=root, version="3.0.1", entries=entries)


def _supply(trail=("a.zip", "1cv8.efd"), templates=None):
    templates = (_template(),) if templates is None else templates
    catalog = Catalog(
        header=1,
        supply_info=(SupplyInfo(lang="ru", name="Бухгалтерия", provider="1С", description_path=""),),
        entries=tuple(entry for template in templates for entry in template.entries),
        templates=templates,
    )
    return Inspected(path="/d/" + trail[0], supplies=(FoundSupply(trail=trail, catalog=catalog),))


def _distribution(name="server64.zip"):
    return Inspected(
        path="/d/" + name,
        files=(FoundFile(trail=(name, "setup-full-8.3.27.2342-x86_64.run"), size=2048),),
    )


def _failure(name="broken.zip", code=UnpackErrorCode.CORRUPTED_ARCHIVE):
    return Inspected(path="/d/" + name, failure=UnpackError(code, {"reason": "broken_container"}))


def build(results=(), **kwargs):
    """CLI с подменённым осмотром, неподвижными часами и собранным выводом."""
    printed = []
    seen = {}

    def fake_inspect(paths, on_start=None):
        seen["paths"] = tuple(paths)
        if on_start is not None:
            for path in paths:
                on_start(path)
        return list(results)

    ticks = iter([10.0, 10.25])
    app = CLIApplication(
        validator=None,
        unpack_service=None,
        translator=DummyTranslator(),
        output=printed.append,
        inspect_files=fake_inspect,
        is_installed=kwargs.pop("is_installed", lambda _destination: False),
        clock=lambda: next(ticks),
        **kwargs,
    )
    return app, printed, seen


# --- разбор аргументов -------------------------------------------------------


def test_paths_are_passed_through_in_order():
    app, _printed, seen = build([_distribution()])

    app.run(["efd_unpacker", "info", "b.zip", "a.zip"])

    assert seen["paths"] == ("b.zip", "a.zip")


def test_command_is_case_insensitive():
    app, printed, _seen = build([_distribution()])

    result = app.run(["efd_unpacker", "INFO", "a.zip"])

    assert result.handled and printed


def test_info_without_paths_is_a_usage_error():
    app, printed, _seen = build()

    result = app.run(["efd_unpacker", "info"])

    assert result.exit_code == CLICommands.EXIT_USAGE
    assert "Usage:" in printed[0]


def test_unknown_flag_is_a_usage_error_not_a_file_name():
    """
    Опечатка в флаге раньше молча стала бы путём.

    Пользователь получил бы «файл не найден» вместо подсказки о синтаксисе.
    """
    app, _printed, seen = build([_distribution()])

    result = app.run(["efd_unpacker", "info", "a.zip", "--jsn"])

    assert result.exit_code == CLICommands.EXIT_USAGE
    assert "paths" not in seen, "осмотр не должен был запуститься"


@pytest.mark.parametrize("tail", [["-tmplts"], ["-dist"], ["-tmplts", ""]])
def test_flag_without_a_value_is_a_usage_error(tail):
    app, _printed, _seen = build()

    result = app.run(["efd_unpacker", "info", "a.zip"] + tail)

    assert result.exit_code == CLICommands.EXIT_USAGE


def test_help_inside_info_shows_help_and_succeeds():
    app, printed, seen = build()

    result = app.run(["efd_unpacker", "info", "--help"])

    assert result.exit_code == 0
    assert "Usage:" in printed[0]
    assert "paths" not in seen


def test_templates_root_is_used_for_destinations():
    app, printed, _seen = build([_supply()])

    app.run(["efd_unpacker", "info", "a.zip", "-tmplts", "/my/tmplts"])

    assert "/my/tmplts/1c/Acc/3_0_1" in printed[0]


def test_distributions_root_defaults_next_to_the_templates_root():
    """Договорённость: «минус tmplts, плюс dist» — один родитель на оба."""
    app, printed, _seen = build([_distribution()])

    app.run(["efd_unpacker", "info", "a.zip", "-tmplts", "/my/1cv8/tmplts"])

    assert "/my/1cv8/dist/platform/8.3.27.2342" in printed[0]


def test_distributions_root_can_be_set_apart():
    app, printed, _seen = build([_distribution()])

    app.run(["efd_unpacker", "info", "a.zip", "-tmplts", "/my/tmplts", "-dist", "/other/dist"])

    assert "/other/dist/platform/8.3.27.2342" in printed[0]


# --- коды возврата -----------------------------------------------------------


def test_clean_inspection_returns_zero():
    app, _printed, _seen = build([_supply(), _distribution()])

    assert app.run(["efd_unpacker", "info", "a.zip"]).exit_code == 0


def test_refusal_returns_one():
    """Отказ осмотра требует решения — это не рядовой успех."""
    app, _printed, _seen = build([_supply(), _failure()])

    assert app.run(["efd_unpacker", "info", "a.zip", "b.zip"]).exit_code == 1


def test_skip_alone_is_still_success():
    """Пропуск — ожидаемый исход, а не проблема."""
    app, _printed, _seen = build([_failure("tc.rar", UnpackErrorCode.CONTAINER_UNSUPPORTED)])

    assert app.run(["efd_unpacker", "info", "tc.rar"]).exit_code == 0


def test_failure_does_not_hide_the_other_rows():
    """Критерий #52: неразобранный файл даёт строку и не прерывает остальных."""
    app, printed, _seen = build([_failure(), _supply(), _distribution()])

    app.run(["efd_unpacker", "info", "a.zip", "b.zip", "c.zip"])

    assert "Бухгалтерия" in printed[0]
    assert "8.3.27.2342" in printed[0]
    assert "error" in printed[0]


# --- формат вывода -----------------------------------------------------------


def test_json_flag_switches_the_format():
    app, printed, _seen = build([_supply()])

    app.run(["efd_unpacker", "info", "a.zip", "--json"])
    document = json.loads(printed[0])

    assert document["items"][0]["kind"] == "supply"
    assert document["totals"]["files"] == 1


def test_json_reports_elapsed_time_from_the_clock():
    app, printed, _seen = build([_supply()])

    app.run(["efd_unpacker", "info", "a.zip", "--json"])

    assert json.loads(printed[0])["totals"]["seconds"] == 0.25


def test_already_installed_destination_becomes_a_skip():
    app, printed, _seen = build([_supply()], is_installed=lambda _destination: True)

    app.run(["efd_unpacker", "info", "a.zip", "--json"])
    entry = json.loads(printed[0])["items"][0]

    assert entry["action"] == "skip"
    assert entry["reason"] == "already_installed"


# --- прогресс ----------------------------------------------------------------


class FakeStream:
    def __init__(self, tty):
        self.tty = tty
        self.written = []

    def isatty(self):
        return self.tty

    def write(self, text):
        self.written.append(text)

    def flush(self):
        pass


def test_progress_is_silent_when_output_is_not_a_terminal():
    """В логе CI бегущая строка с возвратом каретки превращается в мусор."""
    assert terminal_progress(FakeStream(tty=False)) is None


def test_progress_shows_file_names_in_a_terminal():
    stream = FakeStream(tty=True)

    report = terminal_progress(stream)
    report("/downloads/demo.zip")

    assert "demo.zip" in "".join(stream.written)
    assert "/downloads" not in "".join(stream.written), "путь целиком не влезет в строку"


def test_progress_line_is_cleared_before_the_result():
    """Иначе имя последнего файла осталось бы поверх таблицы."""
    stream = FakeStream(tty=True)
    report = terminal_progress(stream)

    report("/downloads/very-long-name.zip")
    report("")

    assert stream.written[-2].strip() == "", "строка не затёрта пробелами"


def test_progress_runs_for_every_file_and_then_clears():
    stream = FakeStream(tty=True)
    app, _printed, _seen = build([_supply(), _supply()], progress=terminal_progress(stream))

    app.run(["efd_unpacker", "info", "a.zip", "b.zip"])
    written = "".join(stream.written)

    assert "a.zip" in written and "b.zip" in written
    assert written.endswith("\r")


# --- команда не перехватывает чужое ------------------------------------------


def test_other_commands_are_left_to_the_gui():
    app, _printed, _seen = build()

    assert app.run(["efd_unpacker", "file.efd"]).handled is False
