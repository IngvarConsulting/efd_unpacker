"""
Текст помощи CLI.

Отдельный модуль, потому что помощь нужна и слою CLI, и main: main импортирует
cli, поэтому обратный импорт замкнул бы цикл, а main вдобавок тянет PyQt5 —
слою CLI он ни к чему.
"""

from __future__ import annotations


def format_help_text(translator) -> str:
    """Return localized CLI help while preserving literal command syntax."""
    lines = [
        translator.translate("CLIHelp", "EFD Unpacker - cross-platform EFD file unpacker"),
        "",
        translator.translate("CLIHelp", "CLI modes:"),
        f"  {translator.translate('CLIHelp', '1. GUI mode: open the window and preselect the input file')}",
        f"  {translator.translate('CLIHelp', '2. Headless mode: unpack directly in the console')}",
        f"  {translator.translate('CLIHelp', '3. Inspect mode: show what is inside without unpacking')}",
        "",
        translator.translate("CLIHelp", "Usage:"),
        "  efd_unpacker [--help|-h]",
        "  efd_unpacker <input_file.efd>",
        "  efd_unpacker unpack <input_file.efd> -tmplts <output_dir>",
        "  efd_unpacker info <file>... [--json] [-tmplts <dir>] [-dist <dir>]",
    ]
    return "\n".join(lines)
