"""
Тесты исполнения плана.

Здесь проверяется только то, что одинаково для любого элемента: порядок,
учёт исходов, отмена и главное обещание — отказ одного не останавливает
остальные. Сама запись подменена: что и куда пишется, проверяется в
test_executor.py.
"""

import pytest

from efd_unpacker.domain.batch import (
    BatchResult,
    ItemFailed,
    ItemSkipped,
    ItemStarted,
    ItemWritten,
    run,
)
from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain.plan import Action, ItemKind, Plan, PlannedItem, SkipReason


def item(title="Поставка", kind=ItemKind.SUPPLY, action=Action.WRITE, **kwargs):
    defaults = dict(
        kind=kind, title=title, version="1.0", source=(title,), origin="/d/" + title,
        destination="/out/" + title, bytes_total=10, action=action,
    )
    defaults.update(kwargs)
    return PlannedItem(**defaults)


def nothing(_item):
    return None


def explode(error):
    def raising(_item):
        raise error
    return raising


def test_written_items_are_reported_in_order():
    plan = Plan(items=(item("a"), item("b")))
    events = []

    result = run(plan, events.append, nothing, nothing)

    assert [type(event).__name__ for event in events] == [
        "ItemStarted", "ItemWritten", "ItemStarted", "ItemWritten",
    ]
    assert [entry.title for entry in result.written] == ["a", "b"]
    assert result.bytes_written == 20


def test_failure_does_not_stop_the_rest():
    """
    Главное обещание батча.

    Пользователь запустил двадцать файлов не для того, чтобы на третьем всё
    встало: он узнает про отказ из отчёта, а остальные к тому времени уже на
    месте.
    """
    plan = Plan(items=(item("a"), item("плохой"), item("b")))
    failure = UnpackError(UnpackErrorCode.PERMISSION)

    def writer(entry):
        if entry.title == "плохой":
            raise failure

    result = run(plan, lambda _e: None, writer, writer)

    assert [entry.title for entry in result.written] == ["a", "b"]
    assert [entry.title for entry, _error in result.failed] == ["плохой"]


def test_unexpected_exception_becomes_a_domain_failure():
    """
    Перехват намеренно широкий: обещание «отказ одного не останавливает
    остальные» нельзя держать списком типов исключений — набор открытый.
    """
    plan = Plan(items=(item("a"), item("b")))

    def writer(entry):
        if entry.title == "a":
            raise RuntimeError("внутри библиотеки")

    result = run(plan, lambda _e: None, writer, writer)

    assert result.failed[0][1].code is UnpackErrorCode.UNEXPECTED
    assert [entry.title for entry in result.written] == ["b"]


def test_supply_and_other_go_to_different_writers():
    plan = Plan(items=(item("поставка"), item("пакеты", kind=ItemKind.PACKAGES)))
    seen = {"supply": [], "other": []}

    result = run(
        plan, lambda _e: None,
        lambda entry: seen["supply"].append(entry.title),
        lambda entry: seen["other"].append(entry.title),
    )

    assert seen == {"supply": ["поставка"], "other": ["пакеты"]}
    assert len(result.written) == 2


def test_planned_skip_does_not_touch_the_writers():
    """Пропуск известен заранее — открывать источник ради него незачем."""
    plan = Plan(items=(item("уже есть", action=Action.SKIP,
                            reason=SkipReason.ALREADY_INSTALLED),))
    events = []

    result = run(plan, events.append, explode(AssertionError("писать не должны")),
                 explode(AssertionError("писать не должны")))

    assert [entry.title for entry in result.skipped] == ["уже есть"]
    assert isinstance(events[0], ItemSkipped)


def test_inspection_failure_stays_a_failure():
    """Отказ осмотра уже в плане: он не пропуск и код возврата обязан ронять."""
    failure = UnpackError(UnpackErrorCode.CORRUPTED_ARCHIVE, {"reason": "broken_container"})
    plan = Plan(items=(item("битый", action=Action.FAIL, failure=failure),))
    events = []

    result = run(plan, events.append, nothing, nothing)

    assert result.failed == ((plan.items[0], failure),)
    assert isinstance(events[0], ItemFailed)
    assert not result.skipped


def test_cancel_stops_between_items():
    """
    Проверка между элементами. Внутри элемента отмену опрашивает сама
    распаковка, порциями — это есть с #11.
    """
    plan = Plan(items=(item("a"), item("b"), item("c")))
    done = []

    result = run(plan, lambda _e: None, done.append, done.append,
                 cancel_check=lambda: len(done) >= 1)

    assert [entry.title for entry in result.written] == ["a"]
    assert result.cancelled is True


def test_cancel_raised_inside_a_writer_is_not_a_failure():
    """
    Отмена — не отказ.

    Иначе остановленная пользователем распаковка отчитывалась бы как
    повреждённый архив.
    """
    plan = Plan(items=(item("a"), item("b")))

    result = run(plan, lambda _e: None,
                 explode(UnpackError(UnpackErrorCode.CANCELLED)),
                 explode(UnpackError(UnpackErrorCode.CANCELLED)))

    assert result.cancelled is True
    assert not result.failed
    assert not result.written


def test_empty_plan_gives_an_empty_result():
    assert run(Plan(), lambda _e: None, nothing, nothing) == BatchResult()


@pytest.mark.parametrize("event_type", [ItemStarted, ItemWritten])
def test_events_carry_the_item(event_type):
    plan = Plan(items=(item("a"),))
    events = []

    run(plan, events.append, nothing, nothing)

    matching = [event for event in events if isinstance(event, event_type)]
    assert matching and matching[0].item.title == "a"
