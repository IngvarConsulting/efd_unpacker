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
from contextlib import contextmanager
from typing import Callable, List, Optional, Set, Tuple

from ..domain.errors import UnpackError, UnpackErrorCode
from ..domain.plan import PlannedItem, keeps_configuration
from ..domain.supply import safe_relative_parts
from ..domain.unpack_service import UnpackService
from ..domain.writing import apply_file_mode, reject_conflicting_entries, resolve_entry_path
from ..infrastructure.containers import Leaf
from .sources import leaves_of

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
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        self._service = unpack_service
        self._templates_root = templates_root
        self._only_configuration = only_configuration
        self._cancel_check = cancel_check
        # Ход внутри элемента: сколько байт уже легло и что пишется сейчас.
        # Окну этого не хватало — оно видело только «начал» и «закончил».
        self._on_progress = on_progress

    def unpack_supply(self, item: PlannedItem) -> None:
        """
        Разворачивает один шаблон поставки в каталог шаблонов.

        Каталог назначения — корень tmplts, а не путь элемента: записи .efd
        несут внутри себя полный путь `<поставщик>/<конфигурация>/<версия>/…`,
        и складывать их ещё раз внутрь него значило бы удвоить путь.
        """
        keep = self._keep_for(item)
        with self._source(item.origin) as leaves:
            handle = self._pick(leaves, item)
            with handle:
                self._service.unpack_stream(
                    handle, self._templates_root, self._cancel_check, keep=keep,
                    on_progress=self._on_progress,
                )

    def extract_other(self, item: PlannedItem) -> None:
        """Раскладывает файлы дистрибутива в его каталог назначения."""
        wanted = {found.trail for found in item.files}
        written = 0
        with self._source(item.origin) as leaves:
            chosen = [leaf for leaf in leaves if leaf.trail in wanted]
            # Проверяем все имена и только потом пишем: отклонить на середине
            # значит оставить пользователю половину файлов. Заодно ловится
            # случай, когда `a.txt` и `./a.txt` дают один и тот же путь.
            names = [self._relative(leaf) for leaf in chosen]
            reject_conflicting_entries(
                [leaf.display_path for leaf in chosen], [list(parts) for parts in names]
            )
            done = 0
            for leaf, parts in zip(chosen, names):
                self._raise_if_cancelled()
                self._write_leaf(leaf, item.destination, parts)
                written += 1
                done += leaf.size
                if self._on_progress is not None:
                    self._on_progress(done, leaf.name)

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

    @staticmethod
    def _pick(leaves, item: PlannedItem):
        for leaf in leaves:
            if leaf.trail == item.source:
                return leaf.opener()
        raise UnpackError(
            UnpackErrorCode.FILE_NOT_FOUND,
            {"entry": " → ".join(item.source), "path": item.origin},
        )

    @staticmethod
    def _relative(leaf: Leaf) -> Tuple[str, ...]:
        """Путь файла внутри каталога назначения, из санированных частей."""
        parts: List[str] = []
        # Первый элемент тропы — сам архив, внутрь которого мы уже вошли.
        for element in leaf.trail[1:]:
            parts.extend(safe_relative_parts(element))
        return tuple(parts)

    @contextmanager
    def _source(self, origin: str):
        """
        Источник с переводом отказов файловой системы в домен.

        Между осмотром и записью файл могли удалить или закрыть доступ. Без
        перевода пользователь видел бы «Неожиданная ошибка» там, где точный
        код «Файл не найден» уже есть.
        """
        try:
            with leaves_of(origin) as leaves:
                yield leaves
        except FileNotFoundError as exc:
            raise UnpackError(UnpackErrorCode.FILE_NOT_FOUND, {"path": origin}) from exc
        except PermissionError as exc:
            raise UnpackError(
                UnpackErrorCode.PERMISSION, {"path": origin, "error": str(exc)}
            ) from exc

    def _write_leaf(self, leaf: Leaf, destination: str, parts: Tuple[str, ...]) -> None:
        """Один файл из контейнера, атомарно и внутри каталога назначения."""
        root = os.path.realpath(destination)
        os.makedirs(root, exist_ok=True)
        # Проверка до makedirs подкаталогов: промежуточный симлинк наружу иначе
        # увёл бы и временный файл, и окончательный за пределы назначения.
        path = resolve_entry_path(root, leaf.display_path, list(parts))
        directory = os.path.dirname(path) or root
        os.makedirs(directory, exist_ok=True)
        resolve_entry_path(root, leaf.display_path, list(parts))

        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".efd-", suffix=".part")
        try:
            with os.fdopen(descriptor, "wb") as out_file, leaf.opener() as source:
                while True:
                    self._raise_if_cancelled()
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    out_file.write(chunk)
            # mkstemp создаёт файл с 0600, и os.replace переносит этот режим на
            # цель: без этой строки распакованный setup-full-*.run переставал
            # быть исполняемым и требовал chmod руками.
            apply_file_mode(temporary, path)
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
