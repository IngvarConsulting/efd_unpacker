"""
Исполнение плана: распаковка пачки файлов.

План — значение, исполнение — события. Окно обновляет строки, CLI печатает,
тест утверждает по потоку: возвращаемое значение одно на весь батч и для
показа хода не годится.

Отказ одного элемента не останавливает остальные. Пользователь запустил
двадцать файлов не для того, чтобы на третьем всё встало: он узнает про
отказ из отчёта, а остальные семнадцать к тому времени уже лежат на месте.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .errors import UnpackError, UnpackErrorCode
from .plan import Action, ItemKind, Plan, PlannedItem


@dataclass(frozen=True)
class ItemStarted:
    item: PlannedItem


@dataclass(frozen=True)
class ItemWritten:
    item: PlannedItem


@dataclass(frozen=True)
class ItemSkipped:
    item: PlannedItem


@dataclass(frozen=True)
class ItemFailed:
    item: PlannedItem
    error: UnpackError


@dataclass(frozen=True)
class BatchResult:
    """Итог батча. Списки, а не счётчики: отчёт должен называть файлы."""

    written: Tuple[PlannedItem, ...] = ()
    skipped: Tuple[PlannedItem, ...] = ()
    failed: Tuple[Tuple[PlannedItem, UnpackError], ...] = ()
    cancelled: bool = False

    @property
    def bytes_written(self) -> int:
        return sum(item.bytes_total for item in self.written)


#: Куда уходят события. Ничего не возвращает: исполнение не зависит от того,
#: кто и как их показывает.
Sink = Callable[[object], None]

def run(
    plan: Plan,
    sink: Sink,
    unpack_supply: Callable[[PlannedItem], None],
    extract_other: Callable[[PlannedItem], None],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> BatchResult:
    """
    Исполняет план, сообщая о каждом элементе.

    Сами записи делают внедрённые функции: поставку разворачивает сервис
    распаковки, прочее — спуск по контейнерам или внешняя программа. Здесь
    остаётся то, что одинаково для всех: порядок, отмена, учёт исходов.
    """
    written: List[PlannedItem] = []
    skipped: List[PlannedItem] = []
    failed: List[Tuple[PlannedItem, UnpackError]] = []
    cancelled = False

    for item in plan.items:
        if item.action is not Action.WRITE:
            # Пропуск и отказ осмотра известны заранее — они уже в плане, и
            # переоткрывать источник ради них незачем.
            if item.action is Action.FAIL and item.failure is not None:
                failed.append((item, item.failure))
                sink(ItemFailed(item, item.failure))
            else:
                skipped.append(item)
                sink(ItemSkipped(item))
            continue

        if cancel_check is not None and cancel_check():
            # Проверка между элементами: внутри элемента отмену опрашивает
            # сама распаковка, порциями.
            cancelled = True
            break

        sink(ItemStarted(item))
        try:
            if item.kind is ItemKind.SUPPLY:
                unpack_supply(item)
            else:
                extract_other(item)
        except UnpackError as error:
            if error.code is UnpackErrorCode.CANCELLED:
                cancelled = True
                break
            failed.append((item, error))
            sink(ItemFailed(item, error))
            continue
        except Exception as exc:  # noqa: BLE001 - см. ниже
            # Намеренно широко, по той же причине, что и в осмотре: обещание
            # «отказ одного не останавливает остальные» нельзя держать списком
            # типов исключений — набор открытый.
            error = UnpackError(
                UnpackErrorCode.UNEXPECTED,
                {"entry": item.title, "error": str(exc) or type(exc).__name__},
            )
            failed.append((item, error))
            sink(ItemFailed(item, error))
            continue

        written.append(item)
        sink(ItemWritten(item))

    return BatchResult(
        written=tuple(written),
        skipped=tuple(skipped),
        failed=tuple(failed),
        cancelled=cancelled,
    )
