"""
Запись по плану: открыть источник заново и положить содержимое на место.

План намеренно остаётся значением — ни потоков, ни дескрипторов, — поэтому
источник открывается повторно, по `item.origin`. Цена невелика: повторный
обход zip занимает миллисекунды, а оглавление .efd читается по началу потока.
Плата за это — план можно отдать в `--json`, сохранить и исполнить позже.

Пишем через соседний временный файл и os.replace, как и записи .efd: при
обрыве на месте остаётся либо прежняя версия, либо новая целиком.
"""

from __future__ import annotations

import os
import tempfile
from typing import Callable, Iterator, Optional, Set

from ..domain.errors import UnpackError, UnpackErrorCode
from ..domain.plan import PlannedItem, keeps_configuration
from ..domain.supply import safe_relative_parts
from ..domain.unpack_service import UnpackService
from ..infrastructure.containers import Leaf, walk

CHUNK = 1024 * 1024


class Writers:
    """
    Пара исполнителей для батча: поставки и всё остальное.

    Класс, а не две замкнутые функции: обе половины делят настройки и кеш
    обхода, и держать это в замыканиях значит прятать состояние.
    """

    def __init__(
        self,
        unpack_service: UnpackService,
        templates_root: str,
        only_configuration: bool = False,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._service = unpack_service
        self._templates_root = templates_root
        self._only_configuration = only_configuration
        self._cancel_check = cancel_check

    def unpack_supply(self, item: PlannedItem) -> None:
        """
        Разворачивает один шаблон поставки в каталог шаблонов.

        Каталог назначения — корень tmplts, а не путь элемента: записи .efd
        несут внутри себя полный путь `<поставщик>/<конфигурация>/<версия>/…`,
        и складывать их ещё раз внутрь него значило бы удвоить путь.
        """
        keep = self._keep_for(item)
        with self._open(item) as handle:
            self._service.unpack_stream(
                handle, self._templates_root, self._cancel_check, keep=keep
            )

    def extract_other(self, item: PlannedItem) -> None:
        """Раскладывает файлы дистрибутива в его каталог назначения."""
        wanted = {found.trail for found in item.files}
        written = 0
        for leaf in self._leaves(item.origin):
            if leaf.trail not in wanted:
                continue
            self._raise_if_cancelled()
            self._write_leaf(leaf, item.destination)
            written += 1

        if written != len(wanted):
            # Между осмотром и записью файл успел измениться, либо внешняя
            # программа отдала другое оглавление. Молча положить половину
            # нельзя: план обещал конкретный состав.
            raise UnpackError(
                UnpackErrorCode.CORRUPTED_ARCHIVE,
                {"reason": "broken_container", "entry": item.title,
                 "expected": len(wanted), "actual": written},
            )

    def _keep_for(self, item: PlannedItem) -> Callable[[str], bool]:
        """
        Отбор записей: только этот шаблон и, если просили, без выгрузок.

        Пути берутся из самого оглавления, а не по префиксу: один .efd несёт
        несколько шаблонов, и сравнение строк-префиксов спутало бы
        `1c/Demo/1_0` с `1c/Demo/1_0_1`.
        """
        template = item.template
        allowed: Set[str] = (
            {entry.path for entry in template.entries} if template is not None else set()
        )
        only_configuration = self._only_configuration

        def keep(src_path: str) -> bool:
            if template is not None and src_path not in allowed:
                return False
            return keeps_configuration(src_path) if only_configuration else True

        return keep

    def _open(self, item: PlannedItem):
        for leaf in self._leaves(item.origin):
            if leaf.trail == item.source:
                return leaf.opener()
        raise UnpackError(
            UnpackErrorCode.FILE_NOT_FOUND,
            {"entry": " → ".join(item.source), "path": item.origin},
        )

    def _leaves(self, origin: str) -> Iterator[Leaf]:
        """
        Обход источника с переводом отказов файловой системы в домен.

        Между осмотром и записью файл могли удалить или закрыть доступ. Без
        перевода пользователь видел бы «Неожиданная ошибка» там, где точный
        код «Файл не найден» уже есть.
        """
        try:
            for leaf in walk(origin):
                yield leaf
        except FileNotFoundError as exc:
            raise UnpackError(UnpackErrorCode.FILE_NOT_FOUND, {"path": origin}) from exc
        except PermissionError as exc:
            raise UnpackError(
                UnpackErrorCode.PERMISSION, {"path": origin, "error": str(exc)}
            ) from exc

    def _write_leaf(self, leaf: Leaf, destination: str) -> None:
        """Один файл из контейнера, атомарно."""
        parts = []
        # Первый элемент тропы — сам архив, внутрь которого мы уже вошли.
        for element in leaf.trail[1:]:
            parts.extend(safe_relative_parts(element))
        path = os.path.join(destination, *parts)
        os.makedirs(os.path.dirname(path) or destination, exist_ok=True)

        descriptor, temporary = tempfile.mkstemp(
            dir=os.path.dirname(path) or destination, prefix=".efd-", suffix=".part"
        )
        try:
            with os.fdopen(descriptor, "wb") as out_file, leaf.opener() as source:
                while True:
                    self._raise_if_cancelled()
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    out_file.write(chunk)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _raise_if_cancelled(self) -> None:
        if self._cancel_check is not None and self._cancel_check():
            raise UnpackError(UnpackErrorCode.CANCELLED)
