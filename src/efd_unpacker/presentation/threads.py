"""
Фоновые потоки окна: осмотр и распаковка.

Обе фазы уводятся из потока интерфейса. Осмотр десяти zip занимает доли
секунды, но образ .dmg монтируется через hdiutil около 0.4 с каждый, и делать
это в потоке окна значит подвесить его на ровном месте.

Сигналы, а не возвращаемые значения: таблица обновляется построчно по мере
исполнения, а результат целиком приходит один раз в конце.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from PyQt5.QtCore import QThread, pyqtSignal

from ..domain.batch import BatchResult, ItemFailed, ItemStarted, ItemWritten
from ..domain.errors import UnpackError, UnpackErrorCode
from ..domain.plan import Plan


class PlanThread(QThread):
    """
    Осмотр файлов. Отдаёт результат осмотра, а не готовый план.

    План строится в окне: `build_plan` — чистая функция и стоит микросекунды,
    а осмотр стоит секунд. Переключение «без демобаз» пересобирает план из уже
    осмотренного, не трогая диск.
    """

    # Именно ready, а не finished: одноимённый сигнал затенял бы встроенный
    # QThread.finished, и повесить на него deleteLater было бы нельзя.
    ready = pyqtSignal(object, object)

    def __init__(self, paths: Sequence[str], inspect_files: Callable) -> None:
        super().__init__()
        self._paths = tuple(paths)
        self._inspect_files = inspect_files

    def run(self) -> None:  # pragma: no cover - потоковая логика
        try:
            self.ready.emit(list(self._inspect_files(self._paths)), None)
        except Exception as exc:  # noqa: BLE001 - поток не должен падать молча
            # Из потока исключение уходит в никуда: окно осталось бы с пустым
            # списком и без единого слова о причине. Сам осмотр отказы уже
            # переводит в строки плана, сюда попадает только неожиданное.
            error = exc if isinstance(exc, UnpackError) else UnpackError(
                UnpackErrorCode.UNEXPECTED, {"error": str(exc) or type(exc).__name__}
            )
            self.ready.emit([], error)


class BatchThread(QThread):
    """Исполнение плана с построчным отчётом о ходе."""

    item_progress = pyqtSignal(object)
    item_finished = pyqtSignal(object, object)
    completed = pyqtSignal(object)

    def __init__(self, plan: Plan, writers, run_batch: Callable) -> None:
        super().__init__()
        self._plan = plan
        self._writers = writers
        self._run_batch = run_batch
        self._cancelled = False

    def cancel(self) -> None:
        """Просит распаковку остановиться на ближайшей границе."""
        self._cancelled = True

    def cancelled(self) -> bool:
        return self._cancelled

    def _emit(self, event) -> None:
        if isinstance(event, ItemStarted):
            self.item_progress.emit(event.item)
        elif isinstance(event, ItemWritten):
            self.item_finished.emit(event.item, None)
        elif isinstance(event, ItemFailed):
            self.item_finished.emit(event.item, event.error)

    def run(self) -> None:  # pragma: no cover - потоковая логика
        try:
            result = self._run_batch(
                self._plan,
                self._emit,
                self._writers.unpack_supply,
                self._writers.extract_other,
                self.cancelled,
            )
        except Exception as exc:  # noqa: BLE001 - поток не должен умирать молча
            # Из потока исключение уходит в никуда: окно осталось бы с живой
            # кнопкой «Отмена» и без единого слова о том, что всё кончилось.
            # Сам батч отказы уже переводит в строки, сюда попадает только
            # неожиданное.
            failure = UnpackError(
                UnpackErrorCode.UNEXPECTED, {"error": str(exc) or type(exc).__name__}
            )
            for planned in self._plan.to_write:
                self.item_finished.emit(planned, failure)
            result = BatchResult(failed=tuple((planned, failure) for planned in self._plan.to_write))
        self.completed.emit(result)


def describe_failure(translator, error: Optional[UnpackError]) -> str:
    """Причина отказа для показа в строке таблицы."""
    from ..application.messages import format_unpack_result

    if error is None:
        return ""
    return format_unpack_result(translator, success=False, error=error)
