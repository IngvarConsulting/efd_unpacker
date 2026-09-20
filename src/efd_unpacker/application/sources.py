"""
Открытие исходного файла: один способ на осмотр и на запись.

Раньше осмотр монтировал .dmg через open_dmg, а исполнитель плана звал walk,
который образ распознать не умеет намеренно. План получался исполнимым на
вид — «записать 30 файлов», — а распаковка не записывала ни одного. Общая
точка входа не даёт двум половинам разойтись снова.

Контекстный менеджер, а не генератор: у смонтированного образа есть время
жизни, и потоки его файлов действительны только пока он подключён.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Tuple

from ..domain.errors import UnpackError, UnpackErrorCode
from ..infrastructure.containers import MAX_DEPTH, Leaf, dmg_supported, open_dmg, walk

#: Образ .dmg узнаётся по расширению, а не по содержимому — в отличие от всех
#: остальных видов. Заглянуть внутрь без монтирования нельзя, сигнатуры в начале
#: файла у него нет (служебные данные лежат в хвосте), поэтому detect_kind вернул
#: бы None и образ уехал бы в план как одиночный непонятный файл.
DMG_SUFFIX = ".dmg"


@contextmanager
def leaves_of(path: str, max_depth: int = MAX_DEPTH) -> Iterator[Tuple[Leaf, ...]]:
    """Файлы внутри источника, действительные на время работы с ними."""
    if path.lower().endswith(DMG_SUFFIX):
        if not dmg_supported():
            # Честный отказ вместо осмотра образа как обычного файла: под Linux
            # и Windows .dmg не смонтировать, и выдавать его за «ничего не
            # нашли» значило бы соврать о содержимом.
            raise UnpackError(
                UnpackErrorCode.CONTAINER_UNSUPPORTED,
                {"entry": os.path.basename(path), "kind": "dmg"},
            )
        with open_dmg(path) as leaves:
            yield leaves
        return

    yield tuple(walk(path, max_depth))
