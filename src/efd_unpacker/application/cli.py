"""
CLI приложение, использующее доменные сервисы.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from ..constants import CLICommands
from ..domain.errors import FileValidationError, UnpackError
from ..domain.file_validator import FileValidator
from ..domain.unpack_service import UnpackService
from ..localization.translator import Translator
from ..runtime import detect_system_language
from .help_text import format_help_text
from .messages import format_unpack_result, format_validation_error


@dataclass
class CLIResult:
    """Результат выполнения CLI-команды."""

    exit_code: int
    handled: bool


class CLIApplication:
    """Прикладной слой CLI, отделённый от sys.exit."""

    def __init__(
        self,
        validator: FileValidator,
        unpack_service: UnpackService,
        translator: Translator,
        output = print,
    ) -> None:
        self._validator = validator
        self._unpack_service = unpack_service
        self._translator = translator
        self._output = output

    def run(self, argv: Sequence[str]) -> CLIResult:
        """Обрабатывает аргументы. Возвращает CLIResult, но не завершает процесс."""
        if not self._is_unpack_command(argv):
            return CLIResult(exit_code=0, handled=False)

        rest = list(argv[2:])
        if wants_help(rest):
            self._output(format_help_text(self._translator))
            return CLIResult(exit_code=0, handled=True)

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

    @staticmethod
    def _is_unpack_command(argv: Sequence[str]) -> bool:
        """
        Регистронезависимо — чтобы UNPACK тоже разбирался здесь.

        Приняли бы мы его или нет, решает _parse_unpack; важно, что такой ввод
        не должен молча уводить пользователя в GUI.
        """
        return len(argv) > 1 and argv[1].lower() == CLICommands.UNPACK


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
    )
    return cli_app.run(argv or sys.argv)
