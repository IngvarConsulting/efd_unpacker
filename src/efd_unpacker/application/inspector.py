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

from typing import Callable, Iterable, List, Optional, Sequence

from ..domain.errors import UnpackError, UnpackErrorCode
from ..domain.plan import FoundFile, FoundSupply, Inspected, is_windows_installer
from ..domain.supply import read_catalog
from ..infrastructure.containers import MAX_DEPTH, Leaf
from ..infrastructure.msi import version_from_stream
from .sources import leaves_of

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
    # Внутри контекста: потоки смонтированного образа действительны только пока
    # он подключён, поэтому оглавления читаются здесь, а не после выхода.
    with leaves_of(path, max_depth) as leaves:
        return _from_leaves(path, leaves)


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
    version = ""
    # Смотрим ПЕРВЫЙ установщик, а не первый удачно прочитанный. Признак
    # отдельный от версии намеренно: по «пустой версии» цикл пошёл бы читать
    # следующий msi, а комплектацию classify берёт всё равно из первого — и
    # план собрался бы из компоненты одного установщика и версии другого.
    examined = False

    for leaf in leaves:
        if leaf.name.lower().endswith(EFD_SUFFIX):
            with leaf.opener() as handle:
                catalog = read_catalog(handle)
            supplies.append(FoundSupply(trail=leaf.trail, catalog=catalog))
        else:
            if not examined and is_windows_installer(leaf.name):
                examined = True
                version = _platform_version(leaf)
            files.append(FoundFile(trail=leaf.trail, size=leaf.size))

    return Inspected(
        path=path, supplies=tuple(supplies), files=tuple(files), platform_version=version,
    )


def _platform_version(leaf: Leaf) -> str:
    """
    Версия платформы из msi установщика Windows.

    Единственное место, где она записана: в именах записей её нет ни у одного
    из десяти проверенных архивов, а имя самого архива опознание не смотрит
    принципиально — windows64_* это сервер, а не 64-битный клиент.

    Стоит это одного открытия листа: у .rar опенер извлекает запись во
    временный каталог, то есть сотые доли секунды и несколько мегабайт,
    которые тут же убираются за собой. Для прочих контейнеров лист читается
    потоком и не стоит ничего.

    Отказ здесь ничего не ломает: вид, комплектация и разрядность опознаны по
    имени msi, без версии каталог просто окажется без номера.
    """
    try:
        with leaf.opener() as handle:
            return version_from_stream(handle)
    except Exception:  # noqa: BLE001 - украшение не имеет права ронять осмотр
        return ""


def _os_failure(path: str, exc: OSError) -> UnpackError:
    """Отказ файловой системы в доменных терминах."""
    if isinstance(exc, FileNotFoundError):
        return UnpackError(UnpackErrorCode.FILE_NOT_FOUND, {"path": path})
    if isinstance(exc, PermissionError):
        return UnpackError(UnpackErrorCode.PERMISSION, {"path": path, "error": str(exc)})
    return UnpackError(UnpackErrorCode.UNEXPECTED, {"path": path, "error": str(exc)})
