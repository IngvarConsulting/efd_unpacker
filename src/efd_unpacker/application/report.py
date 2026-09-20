"""
Показ плана: таблица для человека и JSON для машины.

Одно и то же значение `Plan` рисуется двумя способами. В таблице — переводимые
слова, в JSON — константы enum: разбирать локализованную строку невозможно, а
менять ключи вслед за языком интерфейса нельзя.
"""

from __future__ import annotations

import json
from typing import Dict, List, Sequence, Tuple

from ..domain.plan import Action, ItemKind, Plan, PlannedItem, SkipReason
from ..localization.translator import Translator
from .messages import format_unpack_result

#: Версия формата --json. Растёт, когда меняется смысл существующих ключей,
#: а не когда добавляется новый: потребитель обязан пережить незнакомое поле.
JSON_SCHEMA = 1

KIND_KEYS = {
    ItemKind.SUPPLY: "template",
    ItemKind.PLATFORM: "distribution",
    ItemKind.PACKAGES: "packages",
    ItemKind.CONTENT: "content",
    ItemKind.OTHER: "other",
}

REASON_KEYS = {
    SkipReason.ALREADY_INSTALLED: "already installed",
    SkipReason.FILTERED_OUT: "excluded by filter",
    SkipReason.CONTAINER_UNSUPPORTED: "format is not supported",
    SkipReason.RAR_TOOL_MISSING: "no program for .rar",
    SkipReason.NOTHING_FOUND: "nothing found inside",
    SkipReason.NO_TEMPLATES: "no templates inside",
}

ACTION_KEYS = {
    Action.SKIP: "skipped",
    Action.FAIL: "error",
}

_UNITS = ("B", "K", "M", "G", "T")


def format_plan(
    translator: Translator, plan: Plan, source_count: int, elapsed: float, result=None
) -> str:
    """
    Таблица плана целиком, вместе с заголовком путей и итогом.

    `result` появляется после исполнения: те же строки, но исход в первой
    колонке уже свершившийся, а не намеченный. Показывать план как есть после
    распаковки нельзя — он обещал записать то, что могло и не записаться.
    """
    outcomes = _outcomes(result)
    rows = [_row(translator, item, outcomes) for item in plan.items]
    prefix = _common_prefix([item.destination for item in plan.items if item.destination])

    lines: List[str] = []
    if prefix:
        lines.append("%s %s" % (translator.translate("Report", "paths:"), prefix))
        lines.append("")
        rows = [(kind, title, version, size, _strip(where, prefix)) for kind, title, version, size, where in rows]

    lines.extend(_aligned(rows))
    if rows:
        lines.append("")
    lines.append(_summary(translator, plan, source_count, elapsed, result))
    return "\n".join(lines)


def _outcomes(result) -> Dict[Tuple[str, ...], Tuple[str, object]]:
    """
    Что с каждым элементом случилось на самом деле, по ключу «откуда и куда».

    Вместе с исходом хранится и ошибка: без неё отказавшая при записи строка
    показывала путь назначения вместо причины — «отказ» без объяснения.

    Ключ — источник плюс назначение: в одном файле бывает несколько шаблонов,
    и одного имени файла для различения мало.
    """
    if result is None:
        return {}
    outcomes: Dict[Tuple[str, ...], Tuple[str, object]] = {}
    for item in result.written:
        outcomes[_key(item)] = ("written", None)
    for item, error in result.failed:
        outcomes[_key(item)] = ("error", error)
    return outcomes


def _key(item: PlannedItem) -> Tuple[str, ...]:
    return item.source + (item.destination,)


def _row(
    translator: Translator, item: PlannedItem, outcomes: Dict[Tuple[str, ...], Tuple[str, object]]
) -> Tuple[str, str, str, str, str]:
    outcome, error = outcomes.get(_key(item), (None, None))
    return (
        translator.translate("Report", outcome) if outcome else _kind_label(translator, item),
        item.title,
        item.version,
        human_bytes(item.bytes_total) if item.bytes_total else "",
        _where(translator, item, error),
    )


def _kind_label(translator: Translator, item: PlannedItem) -> str:
    """
    Первая колонка: вид для того, что будет записано, и исход для всего прочего.

    Пропуск и отказ важнее вида: пользователь ищет глазами, что не поедет, а
    «дистрибутив» в строке, которая никуда не распакуется, вводит в заблуждение.
    """
    key = ACTION_KEYS.get(item.action) or KIND_KEYS[item.kind]
    return translator.translate("Report", key)


def _where(translator: Translator, item: PlannedItem, error=None) -> str:
    """Последняя колонка: куда поедет, либо почему не поехало."""
    if error is not None:
        # Отказ случился при записи: обещанный путь здесь уже неинтересен,
        # пользователю нужна причина.
        return format_unpack_result(translator, success=False, error=error)
    if item.action is Action.FAIL:
        return format_unpack_result(translator, success=False, error=item.failure)
    if item.action is Action.SKIP:
        key = REASON_KEYS.get(item.reason) if item.reason else None
        return translator.translate("Report", key) if key else ""
    return item.destination


def _aligned(rows: Sequence[Tuple[str, ...]]) -> List[str]:
    """
    Колонки по ширине самой длинной ячейки.

    Размер прижат вправо: числа сравнивают взглядом по правому краю, и
    «2.3G» под «135M» иначе не выстроятся.
    """
    if not rows:
        return []
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    lines = []
    for row in rows:
        cells = [
            row[column].rjust(widths[column]) if column == 3 else row[column].ljust(widths[column])
            for column in range(len(row))
        ]
        lines.append("  ".join(cells).rstrip())
    return lines


def _summary(
    translator: Translator, plan: Plan, source_count: int, elapsed: float, result=None
) -> str:
    """
    Итоговая строка.

    Числа стоят после двоеточия, а не перед существительным: в русском «1 файл»,
    «2 файла», «5 файлов» — три разные формы, а загрузчик переводов множественных
    форм Qt пока не умеет. Форма «файлов: 1» верна при любом числе.
    """
    counts = _counts(plan)
    parts = ["%s %d" % (translator.translate("Report", "files:"), source_count)]
    for key, value in counts:
        if value:
            parts.append("%s %d" % (translator.translate("Report", key), value))
    if result is None:
        parts.append("%s %s" % (
            translator.translate("Report", "to write:"), human_bytes(plan.bytes_to_write)))
    else:
        parts.append("%s %s" % (
            translator.translate("Report", "written:"), human_bytes(result.bytes_written)))
        if result.cancelled:
            parts.append(translator.translate("Report", "stopped"))
    parts.append("%.1fs" % elapsed)
    return " · ".join(parts)


def _counts(plan: Plan) -> List[Tuple[str, int]]:
    kinds = {kind: 0 for kind in ItemKind}
    skipped = failed = 0
    for item in plan.items:
        if item.action is Action.FAIL:
            failed += 1
        elif item.action is Action.SKIP:
            skipped += 1
        else:
            kinds[item.kind] += 1
    return [
        ("templates:", kinds[ItemKind.SUPPLY]),
        ("distributions:", kinds[ItemKind.PLATFORM] + kinds[ItemKind.PACKAGES]),
        ("other:", kinds[ItemKind.CONTENT] + kinds[ItemKind.OTHER]),
        ("skipped:", skipped),
        ("errors:", failed),
    ]


def format_json(plan: Plan, source_count: int, elapsed: float, result=None) -> str:
    """
    План машинно. Ключи kind/action/reason — значения enum, а не переводы.

    Сортировка ключей отключена намеренно: порядок задан здесь и совпадает с
    порядком чтения, а не с алфавитом.
    """
    outcomes = _outcomes(result)
    document = {
        "schema": JSON_SCHEMA,
        "items": [_json_item(item, outcomes) for item in plan.items],
        "totals": _json_totals(plan, source_count, elapsed, result),
    }
    return json.dumps(document, ensure_ascii=False, indent=2)


def _json_item(item: PlannedItem, outcomes: Dict[Tuple[str, ...], str]) -> Dict[str, object]:
    document: Dict[str, object] = {
        "kind": item.kind.value,
        "action": item.action.value,
        "name": item.title,
        "version": item.version,
        "source": list(item.source),
        "files": item.file_count,
        "bytes": item.bytes_total,
    }
    if item.destination:
        document["destination"] = item.destination
    if item.reason is not None:
        document["reason"] = item.reason.value
    if item.failure is not None:
        document["error"] = _json_error(item.failure)
    outcome, error = outcomes.get(_key(item), (None, None))
    if outcome is not None:
        # Отдельный ключ, а не подмена action: потребителю нужно и то, что
        # планировалось, и то, что вышло.
        document["outcome"] = "written" if outcome == "written" else "failed"
    if error is not None:
        document["error"] = _json_error(error)
    return document


def _json_error(failure) -> Dict[str, object]:
    """Ошибка в машинном виде: код enum и детали как есть."""
    return {
        "code": failure.code.value,
        "details": {key: _plain(value) for key, value in (failure.details or {}).items()},
    }


def _plain(value: object) -> object:
    """Детали ошибки собирались для человека, поэтому в JSON идут строками."""
    return value if isinstance(value, (int, float, bool, str)) or value is None else str(value)


def _json_totals(
    plan: Plan, source_count: int, elapsed: float, result=None
) -> Dict[str, object]:
    totals: Dict[str, object] = {
        "files": source_count,
        "items": len(plan.items),
        "write": len(plan.to_write),
        "skip": sum(1 for item in plan.items if item.action is Action.SKIP),
        "fail": len(plan.failed),
        "bytes": plan.bytes_to_write,
        "seconds": round(elapsed, 3),
    }
    if result is not None:
        totals["written"] = len(result.written)
        totals["failed"] = len(result.failed)
        totals["skipped"] = len(result.skipped)
        totals["bytes_written"] = result.bytes_written
        totals["cancelled"] = result.cancelled
    return totals


def human_bytes(size: int) -> str:
    """
    Размер коротко: 135M, 2.3G.

    Дробная часть только там, где она различает значения: «2.3G» против «2G»
    полезно, а «135.0M» — шум.
    """
    value = float(size)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            if unit == "B" or value >= 10:
                return "%d%s" % (round(value), unit)
            return "%.1f%s" % (value, unit)
        value /= 1024
    return "%d%s" % (round(value), _UNITS[-1])  # pragma: no cover - цикл всегда выходит раньше


def _common_prefix(paths: Sequence[str]) -> str:
    """
    Общее начало путей назначения, чтобы не повторять его в каждой строке.

    Берётся по частям пути, а не по символам: общее начало строк «…/tmplts» и
    «…/tmplts-old» — «…/tmplts», а это разные каталоги.
    """
    if len(paths) < 2:
        return ""
    split = [path.split("/") for path in paths]
    common: List[str] = []
    for parts in zip(*split):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    # Если какой-то путь совпал с общим началом целиком, его строка осталась бы
    # пустой — «куда» превратилось бы в пробел. Отступаем, пока такой путь есть.
    while common and any(len(parts) == len(common) for parts in split):
        common.pop()
    return "/".join(common) if len(common) > 1 else ""


def _strip(path: str, prefix: str) -> str:
    if path.startswith(prefix + "/"):
        return path[len(prefix) + 1 :]
    return path
