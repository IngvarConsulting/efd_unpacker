"""
CLI приложение, использующее доменные сервисы.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from ..constants import CLICommands
from ..domain.errors import FileValidationError, UnpackError
from ..domain.file_validator import FileValidator
from ..domain.plan import PlanSettings, build_plan
from ..domain.unpack_service import UnpackService
from ..infrastructure.os_utils import (
    get_1c_configuration_location_default,
    get_distributions_location_default,
)
from ..localization.translator import Translator
from ..runtime import detect_system_language
from .help_text import format_help_text
from .inspector import inspect_all
from .messages import format_unpack_result, format_validation_error
from .report import format_json, format_plan


@dataclass
class CLIResult:
    """Результат выполнения CLI-команды."""

    exit_code: int
    handled: bool


@dataclass(frozen=True)
class InfoRequest:
    """Разобранные аргументы команды info."""

    paths: Tuple[str, ...]
    templates_root: str
    distributions_root: str
    as_json: bool


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

    def run(self, argv: Sequence[str]) -> CLIResult:
        """Обрабатывает аргументы. Возвращает CLIResult, но не завершает процесс."""
        command = argv[1].lower() if len(argv) > 1 else ""
        if command not in (CLICommands.UNPACK, CLICommands.INFO):
            return CLIResult(exit_code=0, handled=False)

        rest = list(argv[2:])
        if wants_help(rest):
            self._output(format_help_text(self._translator))
            return CLIResult(exit_code=0, handled=True)

        if command == CLICommands.INFO:
            return self._run_info(rest)

        parsed = self._parse_unpack(argv[1], rest)
        if parsed is None:
            # Ключевое правило: команда unpack всегда обрабатывается здесь и
            # никогда не проваливается в GUI. Раньше любой неверный хвост
            # возвращал handled=False, и процесс повисал в Qt event loop без
            # единого сообщения — для скрипта и CI это выглядело как зависание.
            self._output(format_help_text(self._translator))
            return CLIResult(exit_code=CLICommands.EXIT_USAGE, handled=True)

        input_path, output_dir = parsed
        try:
            normalized_input = self._validator.validate_input_file(input_path)
            normalized_output = self._validator.prepare_output_directory(output_dir)
            self._unpack_service.unpack(normalized_input, normalized_output)
        except FileValidationError as exc:
            message = format_validation_error(self._translator, exc)
            self._output(f"[ERROR] {message}")
            return CLIResult(exit_code=1, handled=True)
        except UnpackError as exc:
            message = format_unpack_result(self._translator, success=False, error=exc)
            self._output(f"[ERROR] {message}")
            return CLIResult(exit_code=1, handled=True)

        success_text = format_unpack_result(self._translator, success=True)
        self._output(f"[OK] {success_text}")
        return CLIResult(exit_code=0, handled=True)

    def _run_info(self, rest: Sequence[str]) -> CLIResult:
        """
        Осмотр без распаковки. На диск не пишет ничего.

        Отказ на одном файле не обрывает остальные: он становится строкой
        плана, а код возврата 1 сообщает, что решение требуется.
        """
        request = self._parse_info(rest)
        if request is None:
            self._output(format_help_text(self._translator))
            return CLIResult(exit_code=CLICommands.EXIT_USAGE, handled=True)

        started = self._clock()
        inspected = self._inspect_files(request.paths, on_start=self._progress)
        if self._progress is not None:
            self._progress("")  # убрать бегущую строку до печати результата
        plan = build_plan(
            inspected,
            PlanSettings(
                templates_root=request.templates_root,
                distributions_root=request.distributions_root,
                is_installed=self._is_installed,
            ),
        )
        elapsed = self._clock() - started

        if request.as_json:
            self._output(format_json(plan, len(request.paths), elapsed))
        else:
            self._output(format_plan(self._translator, plan, len(request.paths), elapsed))

        return CLIResult(exit_code=1 if plan.failed else 0, handled=True)

    @staticmethod
    def _parse_info(rest: Sequence[str]) -> Optional[InfoRequest]:
        """
        Разбор `info <файл>... [--json] [-tmplts КАТАЛОГ] [-dist КАТАЛОГ]`.

        Неизвестный флаг — ошибка ввода, а не имя файла. Иначе опечатка вроде
        `--jsn` молча превратилась бы в путь, и пользователь получил бы отказ
        «файл не найден» вместо подсказки о синтаксисе.
        """
        paths: List[str] = []
        templates_root: Optional[str] = None
        distributions_root: Optional[str] = None
        as_json = False

        index = 0
        while index < len(rest):
            argument = rest[index]
            if argument == CLICommands.JSON_FLAG:
                as_json = True
                index += 1
                continue
            if argument in (CLICommands.OUTPUT_FLAG, CLICommands.DIST_FLAG):
                value = rest[index + 1] if index + 1 < len(rest) else ""
                if not value or value.startswith("-"):
                    # `info a.efd -tmplts --json` иначе съедал бы --json как имя
                    # каталога: вывод молча оставался человеческим, а пути вели
                    # в каталог «--json». Забытое значение флага — ошибка ввода.
                    # Каталог, чьё имя начинается с дефиса, задаётся как ./-имя.
                    return None
                if argument == CLICommands.OUTPUT_FLAG:
                    templates_root = value
                else:
                    distributions_root = value
                index += 2
                continue
            if not argument or argument.startswith("-"):
                return None
            paths.append(argument)
            index += 1

        if not paths:
            return None

        templates = templates_root or get_1c_configuration_location_default()
        return InfoRequest(
            paths=tuple(paths),
            templates_root=templates,
            distributions_root=distributions_root or get_distributions_location_default(templates),
            as_json=as_json,
        )

    @staticmethod
    def _parse_unpack(command: str, rest: Sequence[str]) -> Optional[Tuple[str, str]]:
        """
        Строгий разбор `unpack <файл> -tmplts <каталог>`.

        Флаг сверяется строкой, а не argparse: allow_abbrev=False отключает
        сокращения только для --опций, и argparse всё равно принял бы `-t out`
        и `-tmp out` как -tmplts (проверено на 3.9). Хвост после каталога
        раньше просто отбрасывался, и `unpack a.efd -tmplts out b.efd`
        отвечал [OK] с кодом 0, обработав только первый файл.
        """
        if command != CLICommands.UNPACK:
            return None
        if len(rest) != 3:
            return None
        input_path, flag, output_dir = rest
        if flag != CLICommands.OUTPUT_FLAG:
            return None
        if not input_path or input_path.startswith("-") or not output_dir:
            return None
        return input_path, output_dir


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
