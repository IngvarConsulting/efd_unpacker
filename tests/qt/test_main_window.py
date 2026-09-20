"""
Тесты окна массовой распаковки.

Осмотр, построение плана и исполнение внедряются, поэтому окно проверяется
без диска и без ожидания настоящей распаковки. Что именно находит осмотр,
проверяется в test_inspector, что пишет исполнитель — в test_executor.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
os.environ.setdefault("QT_API", "pyqt5")

import time

import pytest
from PyQt5.QtCore import Qt, QMimeData, QUrl
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtGui import QCloseEvent, QDropEvent

from efd_unpacker.domain.batch import BatchResult, ItemFailed, ItemStarted, ItemWritten
from efd_unpacker.domain.errors import (
    FileValidationCode,
    FileValidationError,
    UnpackError,
    UnpackErrorCode,
)
from efd_unpacker.domain.file_validator import FileValidator
from efd_unpacker.domain.plan import (
    Action,
    ItemKind,
    Plan,
    PlannedItem,
    SkipReason,
)
from efd_unpacker.domain.supply import Entry, Template
from efd_unpacker.domain.unpack_service import UnpackService
from efd_unpacker.presentation import ui
from efd_unpacker.presentation import rows as row_widgets
from efd_unpacker.presentation.ui import MainWindow


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return source


class DummySettings:
    def __init__(self) -> None:
        self.templates = os.path.join(os.sep, "t", "tmplts")
        self.distributions = os.path.join(os.sep, "t", "dist")
        self.saved = []

    def get_output_path(self) -> str:
        return self.templates

    def get_distributions_path(self) -> str:
        return self.distributions

    def set_output_path(self, path: str) -> None:
        self.saved.append(path)
        self.templates = path


class DummyValidator(FileValidator):
    def __init__(self) -> None:
        super().__init__()
        # Список, а не последнее значение: проверка «лишний каталог не
        # создаётся» иначе не видит лишнего вызова, если он был не последним.
        self.prepared = []

    def prepare_output_directory(self, output_dir: str) -> str:
        self.prepared.append(output_dir)
        return output_dir


class DummyUnpackService(UnpackService):
    def __init__(self) -> None:
        pass


def template(root=("1c", "Acc", "3_0"), files=(("1cv8.cf", 100), ("1cv8.dt", 900))):
    entries = tuple(
        Entry(path="/".join(root + (name,)), parts=root + (name,), modified_at=None, size=size)
        for name, size in files
    )
    return Template(root=root, version="3.0", entries=entries)


def item(title="Бухгалтерия", kind=ItemKind.SUPPLY, action=Action.WRITE, **kwargs):
    defaults = dict(
        kind=kind, title=title, version="3.0", source=(title + ".zip",),
        origin=os.path.join(os.sep, "d", title + ".zip"),
        destination=os.path.join(os.sep, "t", "tmplts", "1c", "Acc", "3_0"),
        bytes_total=1000, action=action, template=template(),
    )
    defaults.update(kwargs)
    return PlannedItem(**defaults)


class _Writers:
    """Запись подменена: сам батч тоже подменён, до неё дело не доходит."""

    def unpack_supply(self, _item) -> None:  # pragma: no cover - не вызывается
        raise AssertionError("запись не должна выполняться в этих тестах")

    def extract_other(self, _item) -> None:  # pragma: no cover - не вызывается
        raise AssertionError("запись не должна выполняться в этих тестах")


def make_window(qtbot, inspected=None, plan=None, batch=None, settings=None, validator=None):
    """Окно с подменённым осмотром, планом и исполнением."""
    calls = {"inspect": [], "build": 0, "batch": []}
    inspected = [object()] if inspected is None else inspected
    plan = Plan(items=(item(),)) if plan is None else plan

    def fake_inspect(paths):
        calls["inspect"].append(tuple(paths))
        return inspected

    def fake_build(_inspected, _settings):
        calls["build"] += 1
        return plan

    def fake_batch(current, sink, unpack_supply, extract_other, cancel_check=None):
        calls["batch"].append(current)
        if batch is not None:
            return batch(current, sink, unpack_supply, extract_other, cancel_check)
        for planned in current.to_write:
            sink(ItemStarted(planned))
            sink(ItemWritten(planned))
        return BatchResult(written=current.to_write)

    window = MainWindow(
        translator=DummyTranslator(),
        settings_service=settings or DummySettings(),
        file_validator=validator or DummyValidator(),
        unpack_service=DummyUnpackService(),
        inspect_files=fake_inspect,
        build=fake_build,
        batch=fake_batch,
        make_writers=lambda *args, **kwargs: _Writers(),
    )
    qtbot.addWidget(window)
    window.calls = calls
    return window


def drop(window, paths):
    """Бросает файлы в окно так же, как это делает система."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
    event = QDropEvent(
        window.rect().center(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    window.dropEvent(event)


# --- приём файлов ------------------------------------------------------------


def test_dropping_files_fills_the_list(qtbot):
    """Критерий #56: перетаскивание даёт список."""
    window = make_window(qtbot)

    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    assert window.calls["inspect"] == [("/d/a.zip",)]
    assert window.button_unpack.isEnabled()


def test_ten_files_go_to_inspection_in_one_call(qtbot):
    """
    Критерий #56: десять файлов дают список за время, неотличимое от
    мгновенного. Осмотр уходит в поток одним вызовом, а не десятью.
    """
    paths = ["/d/f%d.zip" % index for index in range(10)]
    window = make_window(qtbot)

    started = time.monotonic()
    drop(window, paths)
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    assert window.calls["inspect"] == [tuple(paths)]
    assert time.monotonic() - started < 1.0


def test_extension_is_not_checked_on_drop(qtbot):
    """На вход годятся zip, dmg, rar — вид определяется содержимым."""
    window = make_window(qtbot)

    drop(window, ["/d/macos.client.dmg"])
    qtbot.waitUntil(lambda: bool(window.calls["inspect"]), timeout=2000)

    assert window.calls["inspect"][0][0].endswith(".dmg")


def test_second_drop_adds_to_the_list(qtbot):
    """
    Критерий #56: после завершения окно принимает новые файлы без перезапуска.

    Второй набор дополняет список, а не стирает его.
    """
    window = make_window(qtbot, inspected=[object()])

    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    drop(window, ["/d/b.zip"])
    qtbot.waitUntil(lambda: len(window.calls["inspect"]) == 2, timeout=2000)

    assert len(window._inspected) == 2, "второй осмотр не дополнил первый"


# --- показ состояния ---------------------------------------------------------


@pytest.mark.parametrize(
    "planned, expected",
    [
        (item(), row_widgets.PENDING),
        (item(action=Action.SKIP, reason=SkipReason.ALREADY_INSTALLED), row_widgets.UNAVAILABLE),
        (item(action=Action.SKIP, reason=SkipReason.FILTERED_OUT), row_widgets.UNAVAILABLE),
        (item(action=Action.FAIL, failure=UnpackError(UnpackErrorCode.PERMISSION)), row_widgets.FAILED),
    ],
)
def test_state_is_encoded_by_shape(qtbot, planned, expected):
    """
    Состояние кодируется формой, а не только цветом.

    Пропуск и отказ намеренно разные: «уже установлено» — нормальный исход,
    а не проблема.
    """
    window = make_window(qtbot, plan=Plan(items=(planned,)))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    assert window.rows[0].mark.state() == expected


def test_row_names_the_role_not_the_whole_path(qtbot):
    """
    Общее начало пути вынесено в подвал.

    Повторять «/t/tmplts» в каждой строке незачем — оно одно на все.
    """
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    where = window.rows[0].texts()[1]
    assert where == "templates · " + "/".join(("1c", "Acc", "3_0"))
    assert window.label_root.text() == os.path.join(os.sep, "t")
    assert "tmplts" in window.label_inside.text()


def test_skipped_row_shows_the_reason(qtbot):
    window = make_window(
        qtbot, plan=Plan(items=(item(action=Action.SKIP, reason=SkipReason.RAR_TOOL_MISSING),))
    )
    drop(window, ["/d/a.rar"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    assert window.rows[0].texts()[1] == "no program for .rar"


def test_demo_size_is_shown_in_the_option(qtbot):
    """
    Опция заслужила место цифрой: .dt это почти половина объёма поставки.
    """
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    assert "900 Б" in window.check_only_cf.text()


def test_toggling_the_option_rebuilds_without_inspecting_again(qtbot):
    """
    Осмотр стоит секунд, построение плана — микросекунд.

    Переключение не должно трогать диск.
    """
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    before_inspect = len(window.calls["inspect"])
    before_build = window.calls["build"]

    window.check_only_cf.setChecked(True)

    assert len(window.calls["inspect"]) == before_inspect, "осмотр повторился"
    assert window.calls["build"] > before_build, "план не пересобран"


# --- распаковка --------------------------------------------------------------


def test_unpacking_marks_the_rows_done(qtbot):
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window.rows[0].mark.state() == row_widgets.DONE, timeout=2000)

    assert window.button_clear.isEnabled()


def test_failed_item_shows_its_reason_in_the_row(qtbot):
    def batch(current, sink, _supply, _other, _cancel):
        planned = current.items[0]
        sink(ItemStarted(planned))
        sink(ItemFailed(planned, UnpackError(UnpackErrorCode.PERMISSION)))
        return BatchResult(failed=((planned, UnpackError(UnpackErrorCode.PERMISSION)),))

    window = make_window(qtbot, batch=batch)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window.rows[0].mark.state() == row_widgets.FAILED, timeout=2000)

    assert "Permission error" in window.rows[0].texts()[1]


def test_window_is_usable_again_after_unpacking(qtbot):
    """
    Критерий #56: окно не тупиковое.

    После завершения список остаётся, кнопки живы, и можно бросить ещё файлы.
    """
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert len(window.rows) == 1, "список стёрся"
    assert window.button_paths.isEnabled()
    assert window.check_only_cf.isEnabled()
    assert not window.rows[0].button_open.isHidden(), "в готовой строке нет «Открыть папку»"

    drop(window, ["/d/b.zip"])
    qtbot.waitUntil(lambda: len(window.calls["inspect"]) == 2, timeout=2000)


def test_cancel_asks_the_batch_to_stop(qtbot):
    """Критерий #56: отмена на середине останавливает батч."""
    seen = {}

    def batch(current, sink, _supply, _other, cancel_check):
        planned = current.items[0]
        sink(ItemStarted(planned))
        for _ in range(200):
            if cancel_check():
                seen["cancelled"] = True
                break
            time.sleep(0.005)
        return BatchResult(cancelled=bool(seen))

    window = make_window(qtbot, batch=batch)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window.button_stop.isEnabled(), timeout=2000)
    window.cancel()
    qtbot.waitUntil(lambda: not window.button_stop.isEnabled(), timeout=3000)
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert seen.get("cancelled") is True


def test_unpack_does_nothing_while_busy(qtbot):
    """Иначе ссылка на живой QThread потерялась бы и он был бы разрушен на ходу."""
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert len(window.calls["batch"]) == 1


def test_unpreparable_output_directory_is_reported(qtbot, monkeypatch):
    class FailingValidator(DummyValidator):
        def prepare_output_directory(self, output_dir: str) -> str:
            raise FileValidationError(FileValidationCode.OUTPUT_NOT_WRITABLE)

    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(args[2]))
    window = make_window(qtbot, validator=FailingValidator())
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()

    assert shown and "permission" in shown[0].lower()
    assert not window.calls["batch"], "батч запустился при негодном каталоге"


def test_output_path_is_saved_only_after_something_was_written(qtbot):
    settings = DummySettings()
    window = make_window(
        qtbot, settings=settings,
        batch=lambda *args, **kwargs: BatchResult(cancelled=True),
    )
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert settings.saved == [], "путь сохранён, хотя ничего не записано"


# --- папка и закрытие --------------------------------------------------------


def test_failed_folder_open_is_reported_with_the_path(qtbot, monkeypatch):
    """
    Регресс #18: показ через строку состояния прятал саму кнопку «Открыть
    папку», и узнать каталог из окна было больше неоткуда.
    """
    shown = []
    monkeypatch.setattr(ui, "open_folder", lambda _path: False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(args[2]))
    window = make_window(qtbot)

    window.open_output_folder()

    assert shown and os.path.join(os.sep, "t", "tmplts") in shown[0]


def test_successful_folder_open_shows_nothing(qtbot, monkeypatch):
    shown = []
    monkeypatch.setattr(ui, "open_folder", lambda _path: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(args[2]))
    window = make_window(qtbot)

    window.open_output_folder()

    assert shown == []


def test_closing_during_unpacking_asks_first(qtbot, monkeypatch):
    """
    Регресс: окно закрывалось сразу, поток продолжал писать в уже
    разрушаемом приложении, и каталог шаблона оставался неполным.
    """
    def batch(current, sink, _supply, _other, cancel_check):
        for _ in range(200):
            if cancel_check():
                break
            time.sleep(0.005)
        return BatchResult(cancelled=True)

    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: asked.append(args[1]) or QMessageBox.No,
    )
    window = make_window(qtbot, batch=batch)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    window.unpack()
    qtbot.waitUntil(lambda: window.button_stop.isEnabled(), timeout=2000)

    event = QCloseEvent()
    window.closeEvent(event)

    assert asked, "закрытие не спросило"
    assert not event.isAccepted(), "окно закрылось посреди распаковки"

    window.cancel()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)


def test_closing_when_idle_does_not_ask(qtbot, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: asked.append(1))
    window = make_window(qtbot)

    event = QCloseEvent()
    window.closeEvent(event)

    assert asked == []
    assert event.isAccepted()


# --- находки обзора ----------------------------------------------------------


def test_writers_get_the_cancellation_flag(qtbot):
    """
    Отмена должна доходить до писателя, а не только до батча.

    Батч проверяет её на границе между элементами, а пачка из одного архива
    там границы не имеет: после нажатия «Отмена» архив дописывался целиком.
    """
    seen = {}

    def spy(_service, _root, _only_cf, cancel_check, on_progress=None):
        seen["cancel_check"] = cancel_check
        seen["on_progress"] = on_progress
        return _Writers()

    window = make_window(qtbot)
    window._make_writers = spy
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert callable(seen.get("cancel_check")), "писателю передан не флаг отмены"
    assert seen["cancel_check"]() is False
    assert callable(seen.get("on_progress")), "писателю не передан обратный вызов хода"


def test_distribution_only_batch_opens_the_distributions_folder(qtbot, monkeypatch):
    """
    Пачка из одних дистрибутивов пишет не в каталог шаблонов.

    Открывать после неё каталог шаблонов значит показать пустую папку — и
    создать её, если её не было.
    """
    settings = DummySettings()
    planned = item(kind=ItemKind.PACKAGES, destination=os.path.join(os.sep, "t", "dist", "x"))
    window = make_window(qtbot, plan=Plan(items=(planned,)), settings=settings)
    drop(window, ["/d/a.rar"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    opened = []
    monkeypatch.setattr(ui, "open_folder", lambda path: opened.append(path) or True)
    window.open_output_folder()

    assert opened == [settings.distributions]


def test_templates_folder_is_not_created_for_a_distribution_only_batch(qtbot):
    validator = DummyValidator()
    planned = item(kind=ItemKind.PACKAGES, destination=os.path.join(os.sep, "t", "dist", "x"))
    window = make_window(qtbot, plan=Plan(items=(planned,)), validator=validator)
    drop(window, ["/d/a.rar"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert validator.prepared == [os.path.join(os.sep, "t", "dist")], validator.prepared


def test_output_path_is_not_saved_for_a_distribution_only_batch(qtbot):
    """Каталог шаблонов не трогали — запоминать нечего."""
    settings = DummySettings()
    planned = item(kind=ItemKind.PACKAGES, destination=os.path.join(os.sep, "t", "dist", "x"))
    window = make_window(qtbot, plan=Plan(items=(planned,)), settings=settings)
    drop(window, ["/d/a.rar"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert settings.saved == []


def test_closing_during_inspection_waits_for_the_thread(qtbot, monkeypatch):
    """
    QThread, разрушенный на ходу, роняет приложение при выходе.

    Осмотр ничего не пишет и спрашивать не о чем, но дождаться его надо.
    """
    started = {}

    def slow_inspect(paths):
        started["at"] = time.monotonic()
        time.sleep(0.3)
        return [object()]

    window = make_window(qtbot)
    window._inspect_files = slow_inspect
    window.set_input_files(["/d/a.zip"])
    qtbot.waitUntil(lambda: "at" in started, timeout=2000)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert not window._plan_thread.isRunning(), "поток осмотра пережил окно"


def test_inspection_error_keeps_the_existing_plan_runnable(qtbot, monkeypatch):
    """
    Отказ второго осмотра не должен гасить кнопку у уже готового плана.

    Кнопка гасится на время осмотра; не вернуть её значит оставить
    пользователя со списком, который видно, но нельзя запустить.
    """
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: window.button_unpack.isEnabled(), timeout=2000)

    def boom(_paths):
        raise RuntimeError("что-то сломалось")

    window._inspect_files = boom
    drop(window, ["/d/b.zip"])
    qtbot.waitUntil(lambda: window._plan_thread is None, timeout=2000)

    assert len(window.rows) == 1, "список стёрся"
    assert window.button_unpack.isEnabled(), "кнопка осталась погашенной"


def test_same_file_twice_gives_rows_with_their_own_state(qtbot):
    """
    Один файл, брошенный дважды, даёт одинаковые по полям элементы.

    Ключ по полям ставил отметку сразу на обе строки — пользователь видел бы
    записанным то, что ещё не начиналось.
    """
    first, second = item(title="A"), item(title="A")
    window = make_window(qtbot, plan=Plan(items=(first, second)))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 2, timeout=2000)

    window._item_finished(first, None)

    assert window.rows[0].mark.state() == row_widgets.DONE
    assert window.rows[1].mark.state() == row_widgets.PENDING, "отметка встала на обе строки"


def test_rebuilding_the_plan_drops_stale_outcomes(qtbot):
    """
    Исходы привязаны к объектам плана.

    После пересборки объекты создаются заново, и оставшийся исход мог бы
    совпасть по id с новым объектом на месте старого.
    """
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    window._item_finished(window._plan.items[0], None)
    assert window.rows[0].state() == row_widgets.DONE

    window.calls["build"] = 0
    window._build = lambda _inspected, _settings: Plan(items=(item(title="Другое"),))
    window._rebuild_plan()

    assert window.rows[0].state() == row_widgets.PENDING, "исход пережил пересборку плана"


def test_batch_failure_does_not_rewrite_finished_outcomes(qtbot):
    """
    Запасной путь потока не должен объявлять отказом то, что уже записано.

    Иначе пользователь увидит отказ у файла, который лежит на диске целым.
    """
    def batch(current, sink, _supply, _other, _cancel):
        sink(ItemStarted(current.items[0]))
        sink(ItemWritten(current.items[0]))
        raise RuntimeError("сломалось после первого")

    first, second = item(title="A"), item(title="B")
    window = make_window(qtbot, plan=Plan(items=(first, second)), batch=batch)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 2, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert window.rows[0].mark.state() == row_widgets.DONE, "записанное объявлено отказом"
    assert window.rows[1].mark.state() == row_widgets.FAILED
