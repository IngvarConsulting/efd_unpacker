import unittest
from typing import List

import pytest

from efd_unpacker.application.cli import CLIApplication, CLIResult, wants_help
from efd_unpacker.constants import CLICommands
from efd_unpacker.domain.errors import FileValidationError, FileValidationCode, UnpackError, UnpackErrorCode
from efd_unpacker.domain.batch import BatchResult
from efd_unpacker.domain.file_validator import FileValidator
from efd_unpacker.domain.plan import Action, ItemKind, Plan, PlannedItem
from efd_unpacker.domain.unpack_service import UnpackService


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return source


class StubValidator(FileValidator):
    def __init__(self) -> None:
        super().__init__()
        self.validated_input = None
        self.prepared_output = None

    def validate_input_file(self, file_path: str) -> str:
        self.validated_input = file_path
        return file_path

    def prepare_output_directory(self, output_dir: str) -> str:
        self.prepared_output = output_dir
        return output_dir


class StubUnpackService(UnpackService):
    def __init__(self) -> None:
        pass

    def unpack(self, input_file: str, output_dir: str) -> None:
        self.last_call = (input_file, output_dir)


class _NoWriters:
    """Заглушка записи: сам батч тоже подменён, до неё дело не доходит."""

    def unpack_supply(self, _item) -> None:  # pragma: no cover - не вызывается
        raise AssertionError("запись не должна выполняться в этих тестах")

    def extract_other(self, _item) -> None:  # pragma: no cover - не вызывается
        raise AssertionError("запись не должна выполняться в этих тестах")


class TestCLIApplication(unittest.TestCase):
    def setUp(self) -> None:
        self.translator = DummyTranslator()
        self.validator = StubValidator()
        self.unpack_service = StubUnpackService()
        self.messages: List[str] = []
        self.inspected: tuple = ()
        self.batch_calls: List[object] = []
        self.plan = Plan(items=(PlannedItem(
            kind=ItemKind.SUPPLY, title="Поставка", version="1.0", source=("input.zip",),
            origin="input.zip", destination="out/1c/D/1_0", bytes_total=10,
            action=Action.WRITE,
        ),))
        self.batch_result = BatchResult(written=self.plan.items)

    def _create_app(self) -> CLIApplication:
        """
        Осмотр, запись и исполнение подменены.

        Тесты здесь про разбор аргументов, коды возврата и формат отчёта; что
        именно находит осмотр, проверяется в test_inspector, а что пишет
        исполнитель — в test_executor.
        """
        def fake_inspect(paths, on_start=None):
            self.inspected = tuple(paths)
            return []

        def fake_batch(plan, sink, unpack_supply, extract_other, cancel_check=None):
            self.batch_calls.append(plan)
            return self.batch_result

        return CLIApplication(
            validator=self.validator,
            unpack_service=self.unpack_service,
            translator=self.translator,
            output=self.messages.append,
            inspect_files=fake_inspect,
            build=lambda _inspected, _settings: self.plan,
            batch=fake_batch,
            make_writers=lambda *args, **kwargs: _NoWriters(),
        )

    def test_run_returns_unhandled_when_no_args(self) -> None:
        app = self._create_app()
        result = app.run(["efd_unpacker"])
        self.assertEqual(result, CLIResult(exit_code=0, handled=False))
        self.assertEqual(self.messages, [])

    def test_run_returns_unhandled_for_gui_mode_file_argument(self) -> None:
        app = self._create_app()
        result = app.run(["efd_unpacker", "input.efd"])
        self.assertEqual(result, CLIResult(exit_code=0, handled=False))
        self.assertEqual(self.messages, [])

    def test_run_unpacks_through_the_batch(self) -> None:
        """
        2.0: unpack идёт через план и батч, а не через одиночный вызов сервиса.

        Проверка входного файла на расширение .efd больше не делается: на вход
        теперь принимаются и zip, и dmg, и вид определяется содержимым.
        Показывается та же таблица, что у info, — с исходом вместо намерения.
        """
        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "input.zip", "-tmplts", "out"])

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.handled)
        self.assertEqual(self.validator.prepared_output, "out")
        self.assertIn("files: 1", self.messages[0])

    def test_run_accepts_several_input_files(self) -> None:
        """Ради этого и переписана грамматика: до 2.0 здесь был код 2."""
        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "a.zip", "b.zip", "-tmplts", "out"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.inspected, ("a.zip", "b.zip"))

    def test_run_validation_error(self) -> None:
        """Каталог шаблонов не удалось подготовить — писать некуда."""
        class FailingValidator(StubValidator):
            def prepare_output_directory(self, output_dir: str) -> str:
                raise FileValidationError(FileValidationCode.OUTPUT_NOT_WRITABLE)

        self.validator = FailingValidator()
        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "input.zip", "-tmplts", "out"])

        self.assertEqual(result.exit_code, 1)
        self.assertTrue(result.handled)
        self.assertTrue(self.messages[0].startswith("[ERROR]"))

    def test_failed_item_gives_exit_code_one(self) -> None:
        """Содержательный отказ внутри батча роняет код возврата."""
        item = self.plan.items[0]
        failure = UnpackError(UnpackErrorCode.PERMISSION)
        self.batch_result = BatchResult(failed=((item, failure),))

        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "input.zip", "-tmplts", "out"])

        self.assertEqual(result.exit_code, 1)

    def test_skip_alone_does_not_break_the_exit_code(self) -> None:
        """«Уже установлено» — нормальный исход, а не проблема."""
        self.batch_result = BatchResult(skipped=(self.plan.items[0],))

        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "input.zip", "-tmplts", "out"])

        self.assertEqual(result.exit_code, 0)

    def test_require_all_turns_a_skip_into_a_failure(self) -> None:
        """Для случая «мне нужен именно этот дистрибутив»."""
        self.batch_result = BatchResult(skipped=(self.plan.items[0],))

        app = self._create_app()
        result = app.run(
            ["efd_unpacker", "unpack", "input.zip", "-tmplts", "out", "--require-all"]
        )

        self.assertEqual(result.exit_code, 1)

    def test_dry_run_does_not_execute_the_batch(self) -> None:
        """Критерий #53: печатает план и не создаёт ничего."""
        app = self._create_app()
        result = app.run(["efd_unpacker", "unpack", "input.zip", "-tmplts", "out", "--dry-run"])

        self.assertEqual(result.exit_code, 0)
        self.assertFalse(self.batch_calls, "батч запустился при --dry-run")
        self.assertIsNone(self.validator.prepared_output, "каталог создан при --dry-run")



class _Recorder:
    """Собирает вывод CLI, чтобы проверить, что пользователь что-то увидел."""

    def __init__(self):
        self.lines = []

    def __call__(self, message):
        self.lines.append(message)

    @property
    def text(self):
        return "\n".join(self.lines)


def _cli_with_output(output):
    return CLIApplication(
        validator=FileValidator(),
        unpack_service=UnpackService(),
        translator=DummyTranslator(),
        output=output,
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["efd_unpacker", "unpack", "a.efd", "--tmplts", "out"],
        ["efd_unpacker", "unpack", "-tmplts", "out", "a.efd"],
        ["efd_unpacker", "UNPACK", "a.efd", "-tmplts", "out"],
        ["efd_unpacker", "unpack", "a.efd"],
        ["efd_unpacker", "unpack"],
        ["efd_unpacker", "unpack", "a.efd", "-tmplts", "out", "EXTRA"],
        ["efd_unpacker", "unpack", "a.efd", "-t", "out"],
        ["efd_unpacker", "unpack", "a.efd", "-tmp", "out"],
        ["efd_unpacker", "unpack", "a.efd", "-tmplts", ""],
    ],
    ids=[
        "--tmplts", "перепутан порядок", "верхний регистр", "без флага",
        "только команда", "лишний хвост", "сокращение -t", "сокращение -tmp",
        "пустой каталог",
    ],
)
def test_malformed_unpack_prints_usage_instead_of_opening_the_gui(argv):
    """
    Регресс #15: любой неверный хвост возвращал handled=False, процесс
    проваливался в Qt event loop и висел до убийства — ни сообщения, ни кода.

    Сокращения проверяются отдельно: allow_abbrev=False в argparse отключает
    их только для --опций, и `-t out` он принял бы как -tmplts.
    """
    output = _Recorder()

    result = _cli_with_output(output).run(argv)

    assert result.handled is True
    assert result.exit_code == 2
    assert "efd_unpacker unpack <file>... -tmplts <dir>" in output.text


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_after_the_command_prints_help(flag):
    """`unpack --help` — именно то, что наберёт забывший синтаксис."""
    output = _Recorder()

    result = _cli_with_output(output).run(["efd_unpacker", "unpack", flag])

    assert result == CLIResult(exit_code=0, handled=True)
    assert "efd_unpacker unpack <file>... -tmplts <dir>" in output.text


def test_help_wins_over_a_malformed_tail():
    output = _Recorder()

    result = _cli_with_output(output).run(["efd_unpacker", "unpack", "a.efd", "--help", "x"])

    assert result.exit_code == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["efd_unpacker"],
        ["efd_unpacker", "/path/file.efd"],
        ["efd_unpacker", "-platform", "offscreen"],
        ["efd_unpacker", "unpacked.efd"],
    ],
    ids=["без аргументов", "файл для GUI", "флаг Qt", "имя, похожее на команду"],
)
def test_non_unpack_arguments_still_go_to_the_gui(argv):
    """GUI-режим трогать нельзя: без команды unpack CLI обязан отдать управление."""
    result = _cli_with_output(_Recorder()).run(argv)

    assert result == CLIResult(exit_code=0, handled=False)


def test_wants_help_scans_every_position():
    assert wants_help(["unpack", "a.efd", "--help"]) is True
    assert wants_help(["-h"]) is True
    assert wants_help(["unpack", "a.efd", "-tmplts", "out"]) is False


@pytest.mark.parametrize("value", ["dt", "all", "CF", ""])
def test_only_accepts_just_cf(value):
    """
    Единственное поддержанное значение.

    Принять любое другое значило бы распаковать не то, о чём просили, — и
    узнал бы об этом пользователь только по содержимому каталога.
    """
    argv = ["efd_unpacker", "unpack", "a.zip", "-tmplts", "out", "--only", value]

    assert _cli_with_output(_Recorder()).run(argv).exit_code == CLICommands.EXIT_USAGE


def test_only_cf_is_accepted():
    app = _cli_with_output(_Recorder())

    assert app._parse(["a.zip", "-tmplts", "out", "--only", "cf"], True).only_configuration


def test_failure_during_writing_shows_its_reason():
    """
    Отказ при записи обязан назвать причину.

    Показывать обещанный путь назначения у строки, которая никуда не поехала,
    значит оставить пользователя с «отказ» без объяснения.
    """
    item = PlannedItem(
        kind=ItemKind.SUPPLY, title="Поставка", version="1.0", source=("input.zip",),
        origin="input.zip", destination="out/1c/D/1_0", bytes_total=10, action=Action.WRITE,
    )
    plan = Plan(items=(item,))
    messages = []
    app = CLIApplication(
        validator=StubValidator(), unpack_service=StubUnpackService(),
        translator=DummyTranslator(), output=messages.append,
        inspect_files=lambda paths, on_start=None: [],
        build=lambda _i, _s: plan,
        make_writers=lambda *args, **kwargs: _NoWriters(),
        batch=lambda *args, **kwargs: BatchResult(
            failed=((item, UnpackError(UnpackErrorCode.PERMISSION)),)
        ),
    )

    result = app.run(["efd_unpacker", "unpack", "input.zip", "-tmplts", "out"])

    assert result.exit_code == 1
    assert "Permission error" in messages[0], messages
    assert "out/1c/D/1_0" not in messages[0], "показан путь вместо причины"
