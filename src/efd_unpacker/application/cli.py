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
        parsed = self._parse_arguments(argv)
        if not parsed:
            return CLIResult(exit_code=0, handled=False)

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
    def _parse_arguments(argv: Sequence[str]) -> Optional[Tuple[str, str]]:
        if len(argv) >= 5 and argv[1] == CLICommands.UNPACK and argv[3] == CLICommands.OUTPUT_FLAG:
            return argv[2], argv[4]
        return None

def run_cli(argv: Optional[Sequence[str]] = None) -> CLIResult:
    """Хелпер для использования без ручного создания зависимостей."""
    cli_app = CLIApplication(
        validator=FileValidator(),
        unpack_service=UnpackService(),
        translator=Translator(lang=detect_system_language()),
    )
    return cli_app.run(argv or sys.argv)
