"""
Осмотр файлов без распаковки.

Мост между спуском по контейнерам и построением плана: `walk` отдаёт листья,
`read_catalog` читает оглавление .efd по началу потока, наружу уходит
`Inspected` — ровно то, что принимает `build_plan`.

Ничего не пишет на диск. Это не оптимизация, а смысл команды: пятнадцать
дистрибутивов общим весом 19 ГБ осматриваются за доли секунды, и решение
«тратить ли 10 ГБ» принимается до того, как потрачен первый байт.
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, List, Optional, Sequence

from ..domain.errors import UnpackError, UnpackErrorCode
from ..domain.plan import FoundFile, FoundSupply, Inspected
from ..domain.supply import read_catalog
from ..infrastructure.containers import MAX_DEPTH, Leaf, dmg_supported, open_dmg, walk

#: Образ .dmg узнаётся по расширению, а не по содержимому — в отличие от всех
#: остальных видов. Заглянуть внутрь без монтирования нельзя, сигнатуры в начале
#: файла у него нет (служебные данные лежат в хвосте), поэтому detect_kind вернул
#: бы None и образ уехал бы в план как одиночный непонятный файл.
DMG_SUFFIX = ".dmg"
EFD_SUFFIX = ".efd"

#: Вызывается перед осмотром каждого файла. Нужен, чтобы показать прогресс,
#: не давая слою осмотра знать, куда и как его печатать.
ProgressCallback = Callable[[str], None]


def inspect_all(
    paths: Sequence[str],
    max_depth: int = MAX_DEPTH,
    on_start: Optional[ProgressCallback] = None,
) -> List[Inspected]:
    """
    Осматривает файлы в том порядке, в каком их передали.

    Порядок сохраняется намеренно: вывод команды должен быть воспроизводимым,
    а перестановка строк относительно аргументов выглядела бы как разный ответ
    на один и тот же запрос.
    """
    results = []
    for path in paths:
        if on_start is not None:
            on_start(path)
        results.append(inspect(path, max_depth))
    return results


def inspect(path: str, max_depth: int = MAX_DEPTH) -> Inspected:
    """
    Осматривает один файл. Отказ возвращается, а не бросается.

    Один битый файл не должен обрывать осмотр остальных: причина уезжает в
    `Inspected.failure` и становится отдельной строкой плана.
    """
    try:
        return _inspect(path, max_depth)
    except UnpackError as exc:
        return Inspected(path=path, failure=exc)
    except OSError as exc:
        return Inspected(path=path, failure=_os_failure(path, exc))
    except Exception as exc:  # noqa: BLE001 - намеренно широко, см. ниже
        # Перехват намеренно не перечисляет типы. Обещание команды — «один
        # битый файл не обрывает осмотр остальных», и держать его списком
        # исключений не выходит: набор открытый. Так UnicodeDecodeError из
        # разбора имени записи уносил весь прогон, оставляя пользователя без
        # строк по всем прочим файлам. Конкретные отказы по-прежнему получают
        # свой код выше; сюда попадает только неожиданное — и попадает
        # отдельной строкой плана, а не падением.
        return Inspected(
            path=path,
            failure=UnpackError(UnpackErrorCode.UNEXPECTED, {"path": path, "error": str(exc)}),
        )


def _inspect(path: str, max_depth: int) -> Inspected:
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
            # Потоки образа действительны только пока он смонтирован, поэтому
            # оглавления читаются здесь, внутри контекста, а не после выхода.
            return _from_leaves(path, leaves)
    return _from_leaves(path, walk(path, max_depth))


def _from_leaves(path: str, leaves: Iterable[Leaf]) -> Inspected:
    """
    Разделяет листья на поставки и прочие файлы.

    Несколько .efd в одном архиве в дикой природе не встречались, но решение
    принято явно: каждый становится своей строкой плана. Молча брать первый
    значило бы потерять остальные, а отказывать — ломать осмотр из-за случая,
    который сам по себе безвреден.
    """
    supplies: List[FoundSupply] = []
    files: List[FoundFile] = []

    for leaf in leaves:
        if leaf.name.lower().endswith(EFD_SUFFIX):
            with leaf.opener() as handle:
                catalog = read_catalog(handle)
            supplies.append(FoundSupply(trail=leaf.trail, catalog=catalog))
        else:
            files.append(FoundFile(trail=leaf.trail, size=leaf.size))

    return Inspected(path=path, supplies=tuple(supplies), files=tuple(files))


def _os_failure(path: str, exc: OSError) -> UnpackError:
    """Отказ файловой системы в доменных терминах."""
    if isinstance(exc, FileNotFoundError):
        return UnpackError(UnpackErrorCode.FILE_NOT_FOUND, {"path": path})
    if isinstance(exc, PermissionError):
        return UnpackError(UnpackErrorCode.PERMISSION, {"path": path, "error": str(exc)})
    return UnpackError(UnpackErrorCode.UNEXPECTED, {"path": path, "error": str(exc)})
