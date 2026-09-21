"""
Тесты окна массовой распаковки.

Осмотр, построение плана и исполнение внедряются, поэтому окно проверяется
без диска и без ожидания настоящей распаковки. Что именно находит осмотр,
проверяется в test_inspector, что пишет исполнитель — в test_executor.
"""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
os.environ.setdefault("QT_API", "pyqt5")

import time

import pytest
from PyQt5.QtCore import Qt, QMimeData, QUrl
from PyQt5.QtWidgets import QMessageBox, QRadioButton
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


    def translate_n(self, context: str, source: str, n: int) -> str:
        """Множественная форма: двойнику достаточно подставить число."""
        return self.translate(context, source).replace("%n", str(n))
class DummySettings:
    def __init__(self) -> None:
        self.templates = os.path.join(os.sep, "t", "tmplts")
        self.distributions = os.path.join(os.sep, "t", "dist")
        self.explicit_distributions = None
        self.saved = []

    def get_output_path(self) -> str:
        return self.templates

    def get_distributions_path(self) -> str:
        return self.explicit_distributions or self.distributions

    def set_output_path(self, path: str) -> None:
        self.saved.append(path)
        self.templates = path

    def output_path_is_stored(self) -> bool:
        return bool(self.saved)

    def set_distributions_path(self, path) -> None:
        self.explicit_distributions = path or None

    def distributions_path_is_explicit(self) -> bool:
        return self.explicit_distributions is not None

    def get_output_path_items(self, manual_selected_path=None):
        from efd_unpacker.infrastructure.settings_service import (
            ORIGIN_DEFAULT,
            ORIGIN_LAST_USED,
            PathChoice,
        )

        return [
            PathChoice(path=self.templates, origin=ORIGIN_LAST_USED, label=self.templates),
            PathChoice(
                path=os.path.join(os.sep, "другой", "tmplts"),
                origin=ORIGIN_DEFAULT,
                label="другой",
            ),
        ]


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


#: Манифеста у подставного элемента нет: чтение с диска в тестах окна
#: означало бы проверять две вещи разом. Формат разбирается в test_manifest.
from efd_unpacker.domain.manifest import Manifest as _Manifest
_NO_MANIFEST = _Manifest()


class _Writers:
    """Запись подменена: сам батч тоже подменён, до неё дело не доходит."""

    def unpack_supply(self, _item) -> None:  # pragma: no cover - не вызывается
        raise AssertionError("запись не должна выполняться в этих тестах")

    def extract_other(self, _item) -> None:  # pragma: no cover - не вызывается
        raise AssertionError("запись не должна выполняться в этих тестах")


def make_window(qtbot, inspected=None, plan=None, batch=None, settings=None, validator=None,
                read_manifest=None):
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
        read_manifest=read_manifest or (lambda _directory: _NO_MANIFEST),
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


# --- находки обзора оформления ----------------------------------------------


def test_mark_is_reachable_from_the_keyboard(qtbot):
    """
    Строку надо уметь отметить без мыши.

    Голый виджет со щелчком по mousePressEvent не брал фокус и не отвечал на
    пробел — отметить строку с клавиатуры было нельзя вовсе.
    """
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    mark = window.rows[0].mark

    assert mark.focusPolicy() != Qt.NoFocus, "знак не берёт фокус"
    assert mark.accessibleName(), "у знака нет имени для средств доступности"

    mark.click()  # то же, что пробел или Enter на кнопке
    assert mark.state() == row_widgets.UNCHECKED


def test_unavailable_mark_cannot_be_toggled(qtbot):
    """«Уже установлено» не переключить ни мышью, ни клавишей."""
    planned = item(action=Action.SKIP, reason=SkipReason.ALREADY_INSTALLED)
    window = make_window(qtbot, plan=Plan(items=(planned,)))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    mark = window.rows[0].mark
    assert not mark.isEnabled()
    mark.click()
    assert mark.state() == row_widgets.UNAVAILABLE


def test_duplicate_rows_keep_their_own_marks(qtbot):
    """
    Один файл, брошенный дважды, даёт совпадающие по полям элементы.

    Ключа по полям мало: снятая отметка у второго переезжала на первый при
    пересборке плана, и снятыми оказывались обе строки.
    """
    first, second = item(title="A"), item(title="A")
    window = make_window(qtbot, plan=Plan(items=(first, second)))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 2, timeout=2000)

    window.rows[1].mark.click()
    assert [row.mark.state() for row in window.rows] == [
        row_widgets.PENDING, row_widgets.UNCHECKED,
    ]

    window._rebuild_plan()

    assert [row.mark.state() for row in window.rows] == [
        row_widgets.PENDING, row_widgets.UNCHECKED,
    ], "снятая отметка переехала на соседнюю строку"


def test_unrelated_roots_are_not_shown_as_one(qtbot):
    """
    Вложенность каталогов считается по частям пути.

    startswith считает «/tmp/dist» лежащим внутри «/t» — ровно та ошибка, от
    которой уходили в resolve_entry_path.
    """
    settings = DummySettings()
    settings.templates = os.path.join(os.sep, "t", "tmplts")
    settings.distributions = os.path.join(os.sep, "tmp", "dist")
    window = make_window(qtbot, settings=settings)

    assert window.label_root.text() == settings.templates
    assert window.label_inside.text() == settings.distributions


def test_footer_names_both_folders_under_a_shared_root(qtbot):
    settings = DummySettings()
    settings.templates = os.path.join(os.sep, "home", "u", "1cv8", "tmplts")
    settings.distributions = os.path.join(os.sep, "home", "u", "1cv8", "dist")
    window = make_window(qtbot, settings=settings)

    assert window.label_root.text() == os.path.join(os.sep, "home", "u", "1cv8")
    assert ",," not in window.label_inside.text(), "запятая задвоилась"
    assert window.label_inside.text().count(",") == 1, window.label_inside.text()
    assert "tmplts" in window.label_inside.text()
    assert "dist" in window.label_inside.text()


def test_status_is_cleared_when_nothing_was_written(qtbot):
    """
    Батч, в котором всё отказало, не должен оставлять счёт оставшегося времени.

    Элемент успевает сообщить о части байт и упасть — остаток времени от него
    врёт: работы больше нет.
    """
    planned = item()

    def batch(current, sink, _supply, _other, _cancel):
        sink(ItemStarted(planned))
        sink(ItemFailed(planned, UnpackError(UnpackErrorCode.PERMISSION)))
        return BatchResult(failed=((planned, UnpackError(UnpackErrorCode.PERMISSION)),))

    window = make_window(qtbot, plan=Plan(items=(planned,)), batch=batch)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    window.label_status.setText("осталось ≈ 4 мин")

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert window.label_status.text() == "", "в шапке остался счёт времени"


def test_finished_row_cannot_be_toggled_back(qtbot):
    """
    Готовую строку не переключить.

    Знак гасится не только при создании, но и при смене состояния: иначе
    после распаковки по нему можно было щёлкнуть и снять отметку с того, что
    уже лежит на диске.
    """
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    mark = window.rows[0].mark
    assert mark.state() == row_widgets.DONE
    assert not mark.isEnabled(), "готовую строку можно переключить"


def test_partial_progress_before_a_failure_does_not_leave_an_eta(qtbot):
    """
    Элемент успел сообщить часть байт и упал.

    Остаток времени считается от записанного, и после отказа он врёт: работы
    больше нет. Без части байт этот случай не воспроизводится — ноль
    записанного и так очищает строку состояния.
    """
    planned = item()
    failure = UnpackError(UnpackErrorCode.PERMISSION)

    def batch(current, sink, _supply, _other, _cancel):
        sink(ItemStarted(planned))
        window._item_bytes(planned, planned.bytes_total // 2, "1cv8.cf")
        sink(ItemFailed(planned, failure))
        return BatchResult(failed=((planned, failure),))

    window = make_window(qtbot, plan=Plan(items=(planned,)), batch=batch)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert window.label_status.text() == "", "в шапке остался счёт времени"


def test_russian_footer_reads_as_one_sentence(qtbot):
    """
    Подвал проверяется на настоящем каталоге переводов, а не на заглушке.

    Пунктуация живёт в строке формата, но перевод может принести свою: так и
    вышло — «для шаблонов,» плюс запятая формата давали «для шаблонов,,».
    С подставным переводчиком этого не видно, потому что он отдаёт исходную
    строку без запятой.
    """
    from efd_unpacker.localization.translator import Translator

    settings = DummySettings()
    settings.templates = os.path.join(os.sep, "home", "u", "1cv8", "tmplts")
    settings.distributions = os.path.join(os.sep, "home", "u", "1cv8", "dist")
    window = MainWindow(
        translator=Translator(lang="ru"),
        settings_service=settings,
        file_validator=DummyValidator(),
        unpack_service=DummyUnpackService(),
        inspect_files=lambda paths: [],
        build=lambda _i, _s: Plan(),
        batch=lambda *args, **kwargs: BatchResult(),
        make_writers=lambda *args, **kwargs: _Writers(),
        read_manifest=lambda _directory: _NO_MANIFEST,
    )
    qtbot.addWidget(window)

    text = window.label_inside.text()
    assert text.count(",") == 1, text
    assert "шаблонов" in text and "дистрибутивов" in text


# --- экраны настроек ---------------------------------------------------------


def test_menu_opens_three_screens(qtbot):
    """В макетах у шестерёнки три пункта: пути, инструменты, о программе."""
    window = make_window(qtbot)

    actions = [action for action in window.menu().actions() if not action.isSeparator()]

    assert [action.text() for action in actions] == [
        "Where to unpack…", "Tools for .rar", "About",
    ]


def test_folders_cannot_be_changed_while_unpacking(qtbot):
    """
    Посреди распаковки писатели уже получили корень.

    Смена настройки развела бы обещанное в окне и то, что пишется на диск, —
    а увидел бы это пользователь только по готовым файлам не в том каталоге.
    """
    running = threading.Event()
    release = threading.Event()

    def batch(plan, sink, *_args, **_kwargs):
        # Батч зовётся из потока распаковки. Виджеты меню собираются в потоке
        # окна и только там: собрать QMenu отсюда значит проверять одно, а
        # ломать другое. Поэтому поток лишь замирает, а меню читает тест.
        running.set()
        release.wait(5)
        return BatchResult(written=plan.to_write)

    window = make_window(qtbot, batch=batch)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(running.is_set, timeout=3000)
    try:
        items = [
            (action.text(), action.isEnabled())
            for action in window.menu().actions()
            if not action.isSeparator()
        ]
    finally:
        release.set()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert items[0] == ("Where to unpack…", False)
    assert items[1][1] is True, "инструменты читать можно всегда"


def test_tools_count_is_shown_only_when_it_is_known(qtbot, monkeypatch):
    """
    Цифра рядом с пунктом берётся из кеша, а не новым поиском.

    Меню открывается в потоке окна, а поиск запускает каждого кандидата за
    номером версии: предел ожидания такого запуска — двадцать секунд.
    """
    window = make_window(qtbot)

    monkeypatch.setattr(ui.rar, "found", lambda: None)
    assert window._tools_title() == "Tools for .rar"

    monkeypatch.setattr(ui.rar, "found", lambda: (object(), object()))
    assert window._tools_title().endswith("2")


def test_changing_the_folder_updates_the_list_and_the_footer(qtbot):
    """
    Критерий #66: смена каталога меняет список и подвал без перезапуска.

    Нижний ярус строки показывает путь относительно корня, поэтому одной
    подписи в подвале мало: без пересборки список говорил бы про старый
    каталог до самого перезапуска.
    """
    settings = DummySettings()
    other = os.path.join(os.sep, "другой", "tmplts")
    window = make_window(qtbot, settings=settings)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.show_paths()
    before = (window.rows[0].texts()[1], window.label_root.text())
    window._paths.findChild(QRadioButton, "templates-1").click()

    assert settings.get_output_path() == other
    assert window.calls["build"] > 1, "план не пересобран"
    assert (window.rows[0].texts()[1], window.label_root.text()) != before
    assert "другой" in window.label_root.text()


def test_needed_volume_comes_from_the_marked_rows(qtbot):
    """Подвал экрана путей говорит про то, что поедет, а не про весь список."""
    window = make_window(qtbot, plan=Plan(items=(item(bytes_total=4096),)))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.show_paths()
    with_one = window._paths.label_space.text()
    window.rows[0].mark.click()
    window.show_paths()

    assert "4" in with_one
    assert window._paths.label_space.text() != with_one


def test_back_returns_to_the_list(qtbot):
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.show_about()
    assert window.pages.currentIndex() != 0

    window._about.button_back.click()
    assert window.pages.currentIndex() == 0


def test_row_without_a_rar_program_leads_to_the_tools_screen(qtbot):
    """
    Экран инструментов достижим по месту, а не только из меню.

    Строка сообщает, что программы нет; ей же и сказать, где про неё прочитать.
    """
    skipped = item(
        action=Action.SKIP, reason=SkipReason.RAR_TOOL_MISSING, destination="", bytes_total=0,
    )
    window = make_window(qtbot, plan=Plan(items=(skipped,)))
    drop(window, ["/d/setup.rar"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    row = window.rows[0]
    assert row.button_open.isVisible() or row.button_open.text() == "Tools…"
    row.button_open.click()

    assert window.pages.currentWidget() is window._tools
    window._tools.wait()


def test_other_rows_still_open_their_folder(qtbot, monkeypatch):
    """Подмена ссылки у .rar не должна отнять «Открыть папку» у остальных."""
    opened = []
    monkeypatch.setattr(ui, "open_folder", lambda path: opened.append(path) is None)
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.rows[0].open_requested.emit()

    assert opened == [window._plan.items[0].destination]
    assert window.pages.currentIndex() == 0


def test_closing_waits_for_the_tools_search(qtbot):
    """
    QThread, разрушенный на ходу, роняет приложение при выходе.

    Поиск программ — такой же поток, как осмотр, и ждать его при закрытии
    обязательно.
    """
    window = make_window(qtbot)
    window.show_tools()

    window.closeEvent(QCloseEvent())

    assert not window._tools._thread or not window._tools._thread.isRunning()


def test_labels_inside_bands_are_not_framed(qtbot):
    """
    QLabel — наследник QFrame, и правило «QFrame { border… }» бьёт по нему.

    Полосы окна — шапка, сводка, подвал и нижний ряд — каждая рисует свою
    черту, и безымянное правило обводило рамкой каждую подпись внутри них.
    Видно это только глазами, поэтому подписи проверяются рисунком: ни один
    пиксель цвета черты не должен лежать по краю подписи.
    """
    window = make_window(qtbot)
    window.resize(760, 540)
    # Без show(): плагин minimal валится на настоящем окне QMainWindow, и даже
    # WA_DontShowOnScreen его не спасает. Рамка видна и без показа: подписи
    # рисуются по своей геометрии, а её даёт активация разметки.
    window.layout().activate()
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    framed = [
        label.objectName() or label.text()
        for label in (
            window.label_root_caption, window.label_root, window.label_inside,
            window.label_counts, window.label_status,
        )
        if _has_border(label)
    ]

    assert not framed, "подписи в рамке: %s" % framed


def _has_border(label):
    """Есть ли на краю подписи пиксели цвета разделительной черты."""
    from PyQt5.QtGui import QColor

    from PyQt5.QtGui import QImage, QPainter

    if label.width() < 3 or label.height() < 3:
        return False
    image = QImage(label.width(), label.height(), QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    label.render(painter)
    painter.end()
    edges = (
        [(x, 0) for x in range(image.width())]
        + [(x, image.height() - 1) for x in range(image.width())]
        + [(0, y) for y in range(image.height())]
        + [(image.width() - 1, y) for y in range(image.height())]
    )
    lines = {ui.style.LINE.upper(), ui.style.LINE_SOFT.upper(), ui.style.LINE_FAINT.upper()}
    return any(QColor(image.pixel(x, y)).name().upper() in lines for x, y in edges)


def test_tools_screen_shows_a_probe_made_after_it_was_first_opened(qtbot, monkeypatch):
    """
    Строки экрана собираются один раз, а запись о проверке появляется позже.

    Распаковали .rar — и «проверена на вашем архиве» обязана показаться при
    следующем заходе. «Искать заново» вместо этого не годится: она сначала
    забывает всё, что знала, включая саму запись.
    """
    from efd_unpacker.infrastructure import rar as rar_module

    found = rar_module.Tool(path="/usr/bin/bsdtar", family=rar_module.LIBARCHIVE, version="")
    monkeypatch.setattr(rar_module, "last_probe", lambda: None)
    window = make_window(qtbot)
    window._tools = ui.screens.ToolsScreen(
        window.translator, discover=lambda: (found,), start_search=lambda: None
    )
    window._tools.show_tools((found,))
    # Только в стопку окна: за qtbot экран закрывался бы второй раз, уже
    # после того, как его удалило окно.
    window.pages.addWidget(window._tools)
    assert not _lines(window._tools, "checked on setup.rar")

    monkeypatch.setattr(
        rar_module, "last_probe",
        lambda: rar_module.Probe(tool=found, archive="setup.rar", entries=44),
    )
    window.show_tools()

    assert _lines(window._tools, "checked on setup.rar")


def _lines(widget, needle):
    """
    Подписи, содержащие строку.

    Искать по «checked on» нельзя: ровно эта подстрока есть и в пояснении
    внизу экрана, про проверку на самом архиве.
    """
    from PyQt5.QtWidgets import QLabel

    return [label.text() for label in widget.findChildren(QLabel) if needle in label.text()]


def test_paths_screen_is_told_what_goes_to_each_folder(qtbot):
    """
    Нужное делится по каталогам: они бывают на разных томах.

    Одной цифрой экран путей спросил бы про место только том шаблонов, и
    пачка дистрибутивов на полный диск выглядела бы благополучно.
    """
    plan = Plan(items=(
        item(kind=ItemKind.SUPPLY, bytes_total=2000),
        item(title="Платформа", kind=ItemKind.PLATFORM, bytes_total=5000),
    ))
    window = make_window(qtbot, plan=plan)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 2, timeout=2000)

    window.show_paths()

    assert window._paths._needed == {"templates": 2000, "distributions": 5000}


# --- «В 1С появится…» --------------------------------------------------------


def test_finished_supply_row_says_what_appears_in_1c(qtbot):
    """
    Критерий #67: после распаковки строка называет то, что человек увидит в 1С.

    Это строка Catalog из 1cv8.mft — самое понятное описание из всех, что у
    нас есть: понятнее и имени каталога, и версии.
    """
    from efd_unpacker.domain.manifest import Config, Manifest

    window = make_window(qtbot, read_manifest=lambda _directory: Manifest(
        configs=(Config(catalog="1С:Комплексная автоматизация 2/КА 2"),),
    ))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    row = window.rows[0]
    assert "In 1C it will appear as:" in row.texts()[1]
    # Полное название — в подсказке: в строку оно влезает не всегда, а узнать
    # его целиком человек должен без распаковки заново.
    assert "1С:Комплексная автоматизация 2 → КА 2" in row.label_detail.toolTip()

    # Начало названия видно и в укороченной строке: узнать продукт по нему
    # можно, а дочитать до конца — в подсказке.
    assert "1С:Комплексная автомати" in row.texts()[1]


def test_distribution_row_keeps_its_path(qtbot):
    """Манифеста у дистрибутива нет, и придумывать ему описание нечем."""
    from efd_unpacker.domain.manifest import Config, Manifest

    asked = []
    plan = Plan(items=(item(title="Платформа", kind=ItemKind.PLATFORM),))
    window = make_window(qtbot, plan=plan, read_manifest=lambda directory: (
        asked.append(directory) or Manifest(configs=(Config(catalog="Выдумка"),))
    ))
    drop(window, ["/d/setup.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert asked == [], "манифест у дистрибутива даже не спрашивается"
    assert "Выдумка" not in window.rows[0].texts()[1]


def test_row_without_a_manifest_keeps_its_path(qtbot):
    """
    Критерий #67: украшение, а не условие успеха.

    Манифеста нет — строка остаётся прежней, с путём, и распаковка всё так же
    считается удавшейся.
    """
    from efd_unpacker.domain.manifest import Manifest

    window = make_window(qtbot, read_manifest=lambda _directory: Manifest())
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert window.rows[0].state() == row_widgets.DONE
    assert window.rows[0].texts()[1] == window._detail(window._plan.items[0])


def test_markup_in_a_configuration_name_is_not_rendered(qtbot):
    """
    Название приходит из чужого файла и попадает в разметку.

    Без экранирования «<b>» из манифеста стало бы жирным начертанием, а
    что-нибудь подлиннее — съело бы остаток строки.
    """
    from efd_unpacker.domain.manifest import Config, Manifest

    # Без косой черты: в значении Catalog она разделяет группу и элемент, и
    # «</b>» проверяло бы заодно и разбор дерева — две вещи разом.
    name = "<img src=x> и <b>жирное"
    window = make_window(qtbot, read_manifest=lambda _directory: Manifest(
        configs=(Config(catalog=name),),
    ))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    # Видимый текст, а не исходник: разметка проверяется тем, что показано.
    label = window.rows[0].label_detail
    assert name in _rendered(label)
    # И в подсказке тоже: у неё нет режима «только текст», Qt решает сам —
    # и голый «<img>» превратился бы в попытку нарисовать картинку ровно там,
    # где обещано полное название.
    assert name in _tooltip_text(label)


def _tooltip_text(widget) -> str:
    """Что человек увидит в подсказке, а не что ей передали."""
    from PyQt5.QtGui import QTextDocument

    document = QTextDocument()
    document.setHtml(widget.toolTip())
    return document.toPlainText()


def _rendered(label) -> str:
    """Что Qt действительно нарисует из разметки подписи."""
    from PyQt5.QtGui import QTextDocument

    document = QTextDocument()
    document.setHtml(label.text())
    return document.toPlainText()


# --- объёмы, которые бывают на самом деле ------------------------------------


def test_a_batch_of_eleven_gigabytes_starts(qtbot):
    """
    Границы QProgressBar — 32-битные, и байтами их задавать нельзя.

    Пачка от двух гигабайт отвечала OverflowError прямо на нажатии
    «Распаковать» и не записывала ни байта — то есть ровно тот случай, ради
    которого окно и делалось: в описании #68 на кнопке «Распаковать 9 · 11 ГБ».
    """
    plan = Plan(items=(
        item(title="Комплексная автоматизация", bytes_total=9 * 1024 ** 3),
        item(title="Платформа", kind=ItemKind.PLATFORM, bytes_total=2 * 1024 ** 3),
    ))
    window = make_window(qtbot, plan=plan)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 2, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    assert [row.state() for row in window.rows] == [row_widgets.DONE, row_widgets.DONE]
    assert window.progress_total.value() == ui.style.PROGRESS_STEPS


def test_progress_inside_a_huge_item_does_not_overflow(qtbot):
    """
    Один .cf «Комплексной автоматизации» — 1.4 ГБ, и это обычный размер.

    Обработчик зовётся прямо, из потока окна: в бою его вызывает сигнал,
    который Qt в этот поток и доставляет, а трогать виджеты из потока
    распаковки нельзя.
    """
    big = item(bytes_total=3 * 1024 ** 3)
    # Через unpack(), чтобы границы полосы выставил рабочий код, а не тест:
    # иначе пропавший setMaximum остался бы незамеченным. Сам батч ничего не
    # сообщает, и обработчики зовутся ниже — из потока окна, как в бою.
    window = make_window(qtbot, plan=Plan(items=(big,)),
                         batch=lambda plan, sink, *a, **k: BatchResult())
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)
    window._started_at = time.monotonic() - 1

    window._item_bytes(big, 2 * 1024 ** 3, "1cv8.cf")

    assert window.rows[0].progress.value() > 0
    assert window.rows[0].progress.maximum() == ui.style.PROGRESS_STEPS


def test_time_left_appears_inside_a_single_large_archive(qtbot):
    """
    Пачка из одного архива — обычный случай, и остаток времени в ней нужен.

    Считая только законченные элементы, окно молчало бы до самого конца:
    до последнего байта сделано ровно ноль, а после — уже незачем.
    """
    big = item(bytes_total=4 * 1024 ** 3)
    # Через unpack(), чтобы границы полосы выставил рабочий код, а не тест:
    # иначе пропавший setMaximum остался бы незамеченным. Сам батч ничего не
    # сообщает, и обработчики зовутся ниже — из потока окна, как в бою.
    window = make_window(qtbot, plan=Plan(items=(big,)),
                         batch=lambda plan, sink, *a, **k: BatchResult())
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)
    window._started_at = time.monotonic() - 1

    window._item_bytes(big, big.bytes_total // 4, "1cv8.cf")

    assert window.label_status.text(), "остаток времени не показан"
    assert 0 < window.progress_total.value() < ui.style.PROGRESS_STEPS


def test_progress_forgets_the_unfinished_item_once_it_ends(qtbot):
    """
    Недописанные байты живут только до конца элемента.

    Иначе они сложились бы с его полным объёмом, и полоса ушла бы вперёд
    настоящего — а на последнем элементе показала бы больше ста процентов.
    """
    first = item(bytes_total=1024 ** 3)
    # Через unpack(), чтобы границы полосы выставил рабочий код, а не тест:
    # иначе пропавший setMaximum остался бы незамеченным. Сам батч ничего не
    # сообщает, и обработчики зовутся ниже — из потока окна, как в бою.
    window = make_window(qtbot, plan=Plan(items=(first,)),
                         batch=lambda plan, sink, *a, **k: BatchResult())
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)
    window._started_at = time.monotonic() - 1

    window._item_bytes(first, first.bytes_total // 2, "1cv8.cf")
    window._item_finished(first, None)

    assert window._current_bytes == 0
    assert window.progress_total.value() == ui.style.PROGRESS_STEPS


def test_long_configuration_name_is_shortened_with_an_ellipsis(qtbot):
    """
    Не влезло — обрывается многоточием, а не молча по границе виджета.

    Мерить приходится тем же шрифтом, каким рисуют: размер из таблицы стилей
    в QWidget.font() не попадает, и по меркам гарнитуры по умолчанию строка
    укорачивалась до трети настоящей длины.
    """
    from efd_unpacker.domain.manifest import Config, Manifest

    name = "Демонстрационные конфигурации мобильного приложения → " + "очень длинное " * 6
    window = make_window(qtbot, read_manifest=lambda _directory: Manifest(
        configs=(Config(catalog=name.replace(" → ", "/")),),
    ))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window._batch_thread is None, timeout=3000)

    label = window.rows[0].label_detail
    label.resize(400, label.height())
    assert "…" in label.text()
    assert "Демонстрационные конфигурации мобильного приложения" in label.toolTip()


def test_markup_in_a_supply_name_is_not_rendered_in_the_tooltip(qtbot):
    """
    Наименование поставки тоже из чужого файла, и тоже уходит в подсказку.

    У знака состояния она называет строку целиком — и «<b>» в наименовании
    превращало бы её в жирный шрифт, а «<img>» — в попытку нарисовать
    картинку.
    """
    name = "<img src=x> Бухгалтерия <b>КОРП"
    window = make_window(qtbot, plan=Plan(items=(item(title=name),)))
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    assert name in _tooltip_text(window.rows[0].mark)


# --- #14: окно не тупиковое ---------------------------------------------------


def failing_batch(current, sink, _supply, _other, _cancel=None):
    """Батч, в котором отказывает всё. Ничего не записано — повтор осмыслен."""
    failures = []
    for planned in current.to_write:
        sink(ItemStarted(planned))
        error = UnpackError(UnpackErrorCode.PERMISSION)
        sink(ItemFailed(planned, error))
        failures.append((planned, error))
    return BatchResult(failed=tuple(failures))


def test_a_failed_row_can_be_marked_again_and_re_run(qtbot):
    """
    #14: после отказа повторить распаковку было нечем.

    Знак отказавшей строки не переключался, значит выбранных строк не
    оставалось, значит «Распаковать» гасла. А отказы здесь — кончилось место,
    права на файлах от прошлой распаковки, вынутая флешка — чинятся снаружи
    программы, и после починки человек хочет ровно повтора. Единственным
    выходом было бросить тот же файл ещё раз.
    """
    window = make_window(qtbot, batch=failing_batch)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)

    window.unpack()
    qtbot.waitUntil(lambda: window.rows[0].mark.state() == row_widgets.FAILED, timeout=2000)
    assert not window.button_unpack.isEnabled(), "отказ сам по себе не должен быть выбран"

    window.rows[0].mark.click()

    assert window.rows[0].mark.state() == row_widgets.PENDING
    assert window.button_unpack.isEnabled()

    window.unpack()
    qtbot.waitUntil(lambda: len(window.calls["batch"]) == 2, timeout=3000)


def test_a_cancelled_drag_does_not_lose_the_list(qtbot):
    """
    #14: начатое и отменённое перетаскивание стирало показ выбранного файла,
    хотя сам файл оставался выбранным.

    В прежнем окне метка выбора и БЫЛА состоянием, поэтому подсказка в зоне
    броска затирала выбор. Теперь состояние — список, а надпись в зоне только
    подсказка; проверка держит это врозь.
    """
    window = make_window(qtbot)
    drop(window, ["/d/a.zip"])
    qtbot.waitUntil(lambda: len(window.rows) == 1, timeout=2000)
    before = window.rows[0].texts()

    window._set_drag_active(True)
    window._set_drag_active(False)

    assert len(window.rows) == 1
    assert window.rows[0].texts() == before
    assert window.button_unpack.isEnabled()


class TwoFolders(DummySettings):
    """
    Двойник с двумя РАЗНЫМИ каталогами на выбор.

    DummySettings отдаёт второй пункт неизменным, и после выбора именно его
    оба пункта становятся одним путём: список вырождается, и «выбор держится»
    на нём не проверить. Здесь текущий каталог всегда первый, другой — второй.
    """

    FIRST = os.path.join(os.sep, "t", "tmplts")
    SECOND = os.path.join(os.sep, "другой", "tmplts")

    def get_output_path_items(self, manual_selected_path=None):
        from efd_unpacker.infrastructure.settings_service import (
            ORIGIN_DEFAULT,
            ORIGIN_LAST_USED,
            PathChoice,
        )

        other = self.SECOND if self.templates == self.FIRST else self.FIRST
        return [
            PathChoice(path=self.templates, origin=ORIGIN_LAST_USED, label=self.templates),
            PathChoice(path=other, origin=ORIGIN_DEFAULT, label=other),
        ]


def test_a_chosen_folder_does_not_roll_back_on_the_next_choice(qtbot):
    """
    #14: выбранный вручную каталог откатывался на «использованный прошлый
    раз» при следующем выборе из списка, и распаковка уходила не туда.

    Выпадающего списка больше нет, но последовательность осталась: выбрать
    один пункт, потом другой. Список вариантов пересобирается после каждого
    выбора — ровно то место, где прежняя версия его и теряла.
    """
    settings = TwoFolders()
    window = make_window(qtbot, settings=settings)
    window.show_paths()

    for expected in (TwoFolders.SECOND, TwoFolders.FIRST, TwoFolders.SECOND):
        other = window._paths.findChild(QRadioButton, "templates-1")
        assert other.text() == expected
        other.click()

        current = window._paths.findChild(QRadioButton, "templates-0")
        assert settings.get_output_path() == expected
        assert (current.text(), current.isChecked()) == (expected, True)
