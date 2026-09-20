"""
CLI приложение, использующее доменные сервисы.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from ..constants import CLICommands
from ..domain.errors import FileValidationError
from ..domain.file_validator import FileValidator
from ..domain.batch import ItemFailed, ItemSkipped, ItemStarted, ItemWritten
from ..domain.batch import run as run_batch
from ..domain.plan import Plan, PlanSettings, build_plan
from ..domain.unpack_service import UnpackService
from ..infrastructure import rar
from ..infrastructure.os_utils import (
    get_1c_configuration_location_default,
    get_distributions_location_default,
)
from ..localization.translator import Translator
from ..runtime import detect_system_language
from .help_text import format_help_text
from .executor import Writers
from .inspector import inspect_all
from .messages import format_validation_error
from .report import format_json, format_plan


@dataclass
class CLIResult:
    """Результат выполнения CLI-команды."""

    exit_code: int
    handled: bool


@dataclass(frozen=True)
class Options:
    """
    Разобранные аргументы info и unpack.

    Один разбор на обе команды: грамматика у них общая, различается только то,
    обязателен ли каталог шаблонов. Два похожих разборщика означали бы, что
    однажды опечатку починят в одном и забудут про другой.
    """

    paths: Tuple[str, ...] = ()
    templates_root: str = ""
    distributions_root: str = ""
    rar_tool: Optional[str] = None
    only_configuration: bool = False
    as_json: bool = False
    dry_run: bool = False
    require_all: bool = False


class CLIApplication:
    """Прикладной слой CLI, отделённый от sys.exit."""

    def __init__(
        self,
        validator: FileValidator,
        unpack_service: UnpackService,
        translator: Translator,
        output = print,
        inspect_files = inspect_all,
        is_installed: Callable[[str], bool] = os.path.isdir,
        clock: Callable[[], float] = time.monotonic,
        progress = None,
        build = build_plan,
        make_writers = Writers,
        batch = run_batch,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._validator = validator
        self._unpack_service = unpack_service
        self._translator = translator
        self._output = output
        # Осмотр, проверка «уже установлено» и часы внедряются, чтобы разбор
        # аргументов и вывод проверялись без диска и без ожидания.
        self._inspect_files = inspect_files
        self._is_installed = is_installed
        self._clock = clock
        self._progress = progress
        # Запись и исполнение внедряются, чтобы разбор аргументов, коды
        # возврата и формат отчёта проверялись без диска.
        self._build = build
        self._make_writers = make_writers
        self._run_batch = batch
        self._cancel_check = cancel_check

    def run(self, argv: Sequence[str]) -> CLIResult:
        """Обрабатывает аргументы. Возвращает CLIResult, но не завершает процесс."""
        command = argv[1].lower() if len(argv) > 1 else ""
        if command not in (CLICommands.UNPACK, CLICommands.INFO):
            return CLIResult(exit_code=0, handled=False)

        rest = list(argv[2:])
        if wants_help(rest):
            self._output(format_help_text(self._translator))
            return CLIResult(exit_code=0, handled=True)

        # Ключевое правило: обе команды всегда обрабатываются здесь и никогда
        # не проваливаются в GUI. Раньше любой неверный хвост возвращал
        # handled=False, и процесс повисал в Qt event loop без единого
        # сообщения — для скрипта и CI это выглядело как зависание.
        options = self._parse(rest, require_templates=command == CLICommands.UNPACK)
        if options is None or argv[1] not in (CLICommands.UNPACK, CLICommands.INFO):
            # Регистр команды проверяется здесь, а не при выборе ветки: UNPACK
            # должен разбираться нами и получать внятный отказ, а не молча
            # открывать окно.
            self._output(format_help_text(self._translator))
            return CLIResult(exit_code=CLICommands.EXIT_USAGE, handled=True)

        rar.configure(options.rar_tool)
        if command == CLICommands.INFO:
            return self._run_info(options)
        return self._run_unpack(options)

    def _run_info(self, options: Options) -> CLIResult:
        """
        Осмотр без распаковки. На диск не пишет ничего.

        Отказ на одном файле не обрывает остальные: он становится строкой
        плана, а код возврата 1 сообщает, что решение требуется.
        """
        plan, elapsed = self._build_plan(options)
        self._show(options, plan, elapsed)
        return CLIResult(exit_code=self._exit_code(plan.failed, ()), handled=True)

    def _run_unpack(self, options: Options) -> CLIResult:
        """
        Массовая распаковка. Первая команда, которая пишет на диск.

        `--dry-run` печатает тот же план и останавливается — это и есть
        обещание «спросить, не заплатив», только у команды, которая платит.
        """
        plan, elapsed = self._build_plan(options)
        if options.dry_run:
            self._show(options, plan, elapsed)
            return CLIResult(exit_code=self._exit_code(plan.failed, ()), handled=True)

        try:
            output_root = self._validator.prepare_output_directory(options.templates_root)
        except FileValidationError as exc:
            self._output("[ERROR] %s" % format_validation_error(self._translator, exc))
            return CLIResult(exit_code=1, handled=True)

        writers = self._make_writers(
            self._unpack_service, output_root, options.only_configuration, self._cancel_check
        )
        started = self._clock()
        result = self._run_batch(
            plan, self._report_event, writers.unpack_supply, writers.extract_other,
            self._cancel_check,
        )
        # Время осмотра плюс время записи: показывать в отчёте о распаковке
        # только осмотр значит отвечать «0.0s» там, где записаны гигабайты.
        elapsed += self._clock() - started

        self._show(options, plan, elapsed, result)
        skipped = result.skipped if options.require_all else ()
        return CLIResult(exit_code=self._exit_code(result.failed, skipped), handled=True)

    def _build_plan(self, options: Options) -> Tuple[Plan, float]:
        started = self._clock()
        inspected = self._inspect_files(options.paths, on_start=self._progress)
        if self._progress is not None:
            self._progress("")  # убрать бегущую строку до печати результата
        plan = self._build(
            inspected,
            PlanSettings(
                templates_root=options.templates_root,
                distributions_root=options.distributions_root,
                only_configuration=options.only_configuration,
                is_installed=self._is_installed,
            ),
        )
        return plan, self._clock() - started

    def _show(self, options: Options, plan: Plan, elapsed: float, result=None) -> None:
        if options.as_json:
            self._output(format_json(plan, len(options.paths), elapsed, result))
        else:
            self._output(format_plan(self._translator, plan, len(options.paths), elapsed, result))

    def _report_event(self, event) -> None:
        """Ход батча в stderr: stdout занят результатом, его разбирает jq."""
        if self._progress is None:
            return
        if isinstance(event, ItemStarted):
            self._progress(event.item.title)
        elif isinstance(event, (ItemWritten, ItemFailed, ItemSkipped)):
            self._progress("")

    @staticmethod
    def _exit_code(failed, skipped) -> int:
        """
        1 — содержательный отказ. Пропуск по умолчанию код не роняет: «уже
        установлено» и «нет программы для .rar» — нормальные исходы, а не
        проблемы. Роняет их только --require-all.
        """
        return 1 if failed or skipped else 0

    @staticmethod
    def _parse(rest: Sequence[str], require_templates: bool) -> Optional[Options]:
        """
        Разбор `<файл>... [флаги]`.

        Правило простое и проверяемое глазами: всё до первого флага — входные
        файлы, дальше только флаги. Голый токен в хвосте — ошибка ввода, а не
        ещё один файл: `unpack a.efd -tmplts out EXTRA` до #15 молча отбрасывал
        EXTRA и отвечал успехом, и возвращать это поведение нельзя.

        Значение, начинающееся с дефиса, значением не считается: забытый
        аргумент флага иначе съедал бы следующий флаг.

        argparse по-прежнему не годится: allow_abbrev=False отключает
        сокращения только для --опций, и `-t out` всё равно принималось бы
        за -tmplts (проверено на 3.9).
        """
        paths: List[str] = []
        values: Dict[str, str] = {}
        switches: Set[str] = set()

        value_flags = {
            CLICommands.OUTPUT_FLAG: "templates_root",
            CLICommands.OUTPUT_FLAG_LONG: "templates_root",
            CLICommands.DIST_FLAG: "distributions_root",
            CLICommands.DIST_FLAG_LONG: "distributions_root",
            CLICommands.RAR_TOOL_FLAG: "rar_tool",
            CLICommands.ONLY_FLAG: "only",
        }
        boolean_flags = {
            CLICommands.JSON_FLAG,
            CLICommands.DRY_RUN_FLAG,
            CLICommands.REQUIRE_ALL_FLAG,
        }

        index = 0
        while index < len(rest) and not rest[index].startswith("-"):
            if not rest[index]:
                return None
            paths.append(rest[index])
            index += 1

        while index < len(rest):
            argument = rest[index]
            if argument in boolean_flags:
                switches.add(argument)
                index += 1
                continue
            if argument in value_flags:
                value = rest[index + 1] if index + 1 < len(rest) else ""
                if not value or value.startswith("-"):
                    return None
                values[value_flags[argument]] = value
                index += 2
                continue
            # Сюда попадают и неизвестный флаг, и голый токен после флагов.
            return None

        if not paths:
            return None
        if values.get("only", CLICommands.ONLY_CONFIGURATION) != CLICommands.ONLY_CONFIGURATION:
            # Единственное поддержанное значение. Принять любое другое значило
            # бы распаковать не то, о чём просили.
            return None

        templates = values.get("templates_root", "")
        if require_templates and not templates:
            return None
        templates = templates or get_1c_configuration_location_default()

        return Options(
            paths=tuple(paths),
            templates_root=templates,
            distributions_root=(
                values.get("distributions_root")
                or get_distributions_location_default(templates)
            ),
            rar_tool=values.get("rar_tool"),
            only_configuration="only" in values,
            as_json=CLICommands.JSON_FLAG in switches,
            dry_run=CLICommands.DRY_RUN_FLAG in switches,
            require_all=CLICommands.REQUIRE_ALL_FLAG in switches,
        )


def is_read_only_command(argv: Sequence[str]) -> bool:
    """
    Обещает ли команда не трогать файловую систему.

    Пока такая команда одна — info. Нужно это снаружи: точка входа до разбора
    аргументов регистрирует команду в PATH, а регистрация пишет на диск.
    """
    return len(argv) > 1 and argv[1].lower() == CLICommands.INFO


def wants_help(argv: Sequence[str]) -> bool:
    """
    Есть ли где-нибудь в аргументах просьба показать помощь.

    Раньше --help искался только в sys.argv[1], поэтому `unpack --help` —
    именно то, что наберёт забывший синтаксис, — поднимал пустое окно.
    """
    return any(argument in CLICommands.HELP_FLAGS for argument in argv)

def run_cli(argv: Optional[Sequence[str]] = None) -> CLIResult:
    """Хелпер для использования без ручного создания зависимостей."""
    cli_app = CLIApplication(
        validator=FileValidator(),
        unpack_service=UnpackService(),
        translator=Translator(lang=detect_system_language()),
        progress=terminal_progress(),
    )
    return cli_app.run(argv or sys.argv)


def terminal_progress(stream = None):
    """
    Показ текущего файла — только когда вывод смотрит человек.

    В конвейере и в CI бегущая строка с возвратом каретки превращается в мусор
    в логе, поэтому в не-терминал не пишем ничего. Прогресс идёт в stderr:
    stdout занят результатом, и `info --json | jq` не должен его разбирать.
    """
    stream = sys.stderr if stream is None else stream
    if not hasattr(stream, "isatty") or not stream.isatty():
        return None

    longest = [0]

    def report(path: str) -> None:
        """Пустой путь — сигнал стереть строку: осмотр закончен."""
        text = os.path.basename(path)
        # Затираем пробелами, а не escape-последовательностью: \033[K понимает
        # не всякая консоль Windows, а пробелы — любая.
        stream.write("\r" + text.ljust(longest[0]))
        if not text:
            stream.write("\r")
        longest[0] = max(longest[0], len(text))
        stream.flush()

    return report
