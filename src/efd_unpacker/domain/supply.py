"""
Разбор оглавления .efd: описание поставки, список записей, группировка в шаблоны.

Оглавление лежит в начале потока, а данные файлов — следом. Это позволяет
узнать состав поставки, прочитав мегабайты вместо гигабайтов: у самого
большого из исследованных дистрибутивов (2.96 ГБ) оглавление заняло первые
три килобайта.

Разбор (`parse_catalog`) не знает про сжатие и про файловую систему: на вход
уже распакованный поток, на выход значения — это тестируется голыми байтами.
Чтение (`read_catalog`) добавляет к нему ограниченное разжатие.
"""

from __future__ import annotations

import datetime as dt
import ntpath
import posixpath
import re
import zlib
import io
from dataclasses import dataclass
from struct import unpack
from typing import BinaryIO, Dict, List, Optional, Sequence, Tuple

from .errors import UnpackError, UnpackErrorCode

# Единственная версия заголовка, встречавшаяся в исследованных файлах поставки.
SUPPORTED_HEADER = 1

# FILETIME — число интервалов по 100 нс от 1 января 1601 года.
FILETIME_EPOCH = dt.datetime(1601, 1, 1)

# Корень шаблона отмечен файлом-манифестом: стандарт «Требования к установке и
# обновлению прикладных решений» (its.1c.ru/db/v8std#content:731:hdoc) требует
# класть 1cv8.mft в каталог версии. Имя манифеста видно в списке записей, то есть
# корень определяется бесплатно, ещё до чтения самих данных.
#
# Считать корень по фиксированной глубине <разработчик>/<конфигурация>/<версия>
# нельзя: у tests/data/1cv8.efd каталогов всего два, и шаблон бы потерялся.
MANIFEST_NAME = "1cv8.mft"

# Сколько байт распакованного потока готовы прочитать ради оглавления.
# Мера щедрая: у самой большой исследованной поставки (83 записи, 2.96 ГБ
# данных) оглавление уложилось в 3 КБ. Предел здесь заодно и защита —
# архивная бомба не опасна тому, кто останавливается на восьми мегабайтах.
CATALOG_PREFIX_LIMIT = 8 * 1024 * 1024

# Порция, которую zlib отдаёт за один вызов: удерживает пиковую память.
CATALOG_CHUNK = 1024 * 1024

# Каталог версии записан с подчёркиваниями вместо точек — тоже требование
# стандарта. Обратное преобразование делаем только для того, что на версию похоже.
_VERSION_DIR = re.compile(r"^\d+(?:_\d+)*$")


@dataclass(frozen=True)
class SupplyInfo:
    """Описание комплекта поставки на одном языке."""

    lang: str
    name: str
    provider: str
    description_path: str


@dataclass(frozen=True)
class Entry:
    """Одна запись внутри .efd."""

    path: str
    parts: Tuple[str, ...]
    modified_at: Optional[dt.datetime]
    size: int


@dataclass(frozen=True)
class Template:
    """
    Шаблон конфигурации — то, что 1С покажет в диалоге создания базы.

    Один .efd может нести несколько шаблонов разных продуктов и версий:
    в demo.zip платформы 8.3.27 их два — демонстрационная конфигурация 1.0.41.3
    и демонстрационное мобильное приложение 1.0.27.
    """

    root: Tuple[str, ...]
    version: str
    entries: Tuple[Entry, ...]

    @property
    def relative_path(self) -> str:
        """Путь внутри каталога шаблонов, без разделителя в начале."""
        return "/".join(self.root)

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.entries)


@dataclass(frozen=True)
class Catalog:
    """Полное оглавление .efd."""

    header: int
    supply_info: Tuple[SupplyInfo, ...]
    entries: Tuple[Entry, ...]
    templates: Tuple[Template, ...]

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.entries)

    def describe(self, lang: str = "ru") -> Optional[SupplyInfo]:
        """
        Описание на нужном языке.

        В реальных поставках десять языков, и у части из них наименование
        пустое — у demo.zip пусто украинское. Поэтому откат идёт на английское,
        затем на первое непустое, и только потом наружу уходит None.
        """
        by_lang = {info.lang: info for info in self.supply_info}
        for candidate in (lang, "en"):
            info = by_lang.get(candidate)
            if info is not None and info.name:
                return info
        for info in self.supply_info:
            if info.name:
                return info
        return self.supply_info[0] if self.supply_info else None


class _StrictReader:
    """
    Чтение с проверкой длины.

    Короткое чтение здесь означает обрезанное оглавление, а не конец данных:
    молча получить нули и разобрать мусор — тот самый молчаливый успех,
    от которого проект уходил в #7.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def read(self, size: int) -> bytes:
        data = self._stream.read(size)
        if len(data) < size:
            raise UnpackError(
                UnpackErrorCode.CORRUPTED_ARCHIVE,
                {"reason": "truncated_header", "expected": size, "actual": len(data)},
            )
        return data

    def uint32(self) -> int:
        return unpack("I", self.read(4))[0]

    def int64(self) -> int:
        # Именно знаковое: в поставках 1С встречаются даты раньше 1601 года,
        # и беззнаковое чтение превращало их в 1.8e19 — причина #3 и #5.
        return unpack("q", self.read(8))[0]

    def wide_string(self, errors: str = "strict") -> str:
        length = self.uint32()
        return self.read(length * 2).decode("utf-16", errors)


def parse_catalog(stream: BinaryIO) -> Catalog:
    """
    Разбирает оглавление из уже распакованного потока.

    Поток остаётся на первом байте данных первой записи, поэтому вызывающий
    код может продолжить чтение, не перематывая.
    """
    reader = _StrictReader(stream)

    header = reader.uint32()
    if header != SUPPORTED_HEADER:
        # Раньше здесь стоял assert: под -O он исчезал вовсе, а при срабатывании
        # давал пользователю «Неожиданная ошибка: » без текста.
        raise UnpackError(
            UnpackErrorCode.CORRUPTED_ARCHIVE,
            {"reason": "unsupported_header", "header": header},
        )

    supply_info: List[SupplyInfo] = []
    for _ in range(reader.uint32()):
        reader.uint32()  # назначение поля неизвестно
        # Для показа человеку: испорченный символ в наименовании не повод
        # отказывать в осмотре целого архива.
        supply_info.append(
            SupplyInfo(
                lang=reader.wide_string("replace"),
                name=reader.wide_string("replace"),
                provider=reader.wide_string("replace"),
                description_path=reader.wide_string("replace"),
            )
        )

    entries: List[Entry] = []
    for _ in range(reader.uint32()):
        reader.uint32()  # назначение поля неизвестно
        # Имя записи решает, куда ляжет файл, поэтому здесь строгий режим.
        path = reader.wide_string()
        modified_at = filetime_to_datetime(reader.int64())
        reader.uint32()  # назначение поля неизвестно
        size = reader.uint32()
        entries.append(
            Entry(
                path=path,
                parts=tuple(safe_relative_parts(path)),
                modified_at=modified_at,
                size=size,
            )
        )

    return Catalog(
        header=header,
        supply_info=tuple(supply_info),
        entries=tuple(entries),
        templates=group_templates(entries),
    )


def group_templates(entries: Sequence[Entry]) -> Tuple[Template, ...]:
    """
    Делит записи на шаблоны по каталогам, в которых лежит манифест.

    Корни берутся из УЖЕ санированных частей, а не из сырых имён: ровно на этом
    был пойман дефект в #7, где ключи конфликтов строились из сырых имён и
    `a.txt` против `./a.txt` молча перетирали друг друга.

    Если манифеста нет ни одного, корнем становится общий каталог всех записей:
    поставка без манифеста стандарту не следует, но показать её всё равно надо.
    """
    roots = {
        entry.parts[:-1]
        for entry in entries
        if len(entry.parts) > 1 and entry.parts[-1].lower() == MANIFEST_NAME
    }
    if not roots and entries:
        roots = {_common_directory(entries)}
    roots.discard(())

    grouped: Dict[Tuple[str, ...], List[Entry]] = {root: [] for root in roots}
    for entry in entries:
        root = _longest_root(roots, entry.parts)
        if root is not None:
            grouped[root].append(entry)

    return tuple(
        Template(root=root, version=version_of(root), entries=tuple(items))
        for root, items in grouped.items()
        if items
    )


def _longest_root(
    roots: "set[Tuple[str, ...]]", parts: Tuple[str, ...]
) -> Optional[Tuple[str, ...]]:
    """Самый глубокий корень, внутри которого лежит запись."""
    matching = [root for root in roots if parts[: len(root)] == root and len(parts) > len(root)]
    return max(matching, key=len) if matching else None


def _common_directory(entries: Sequence[Entry]) -> Tuple[str, ...]:
    """Общий каталог всех записей — запасной корень для поставок без манифеста."""
    directories = [entry.parts[:-1] for entry in entries]
    common = directories[0]
    for directory in directories[1:]:
        while directory[: len(common)] != common:
            common = common[:-1]
    return common


def version_of(root: Tuple[str, ...]) -> str:
    """
    Версия шаблона из имени последнего каталога.

    Пусто, если каталог на версию не похож: выдумывать номер хуже, чем
    честно его не знать.
    """
    return version_from_dir(root[-1]) if root and _VERSION_DIR.match(root[-1]) else ""


def version_from_dir(directory: str) -> str:
    """`2_0_110_66` → `2.0.110.66`. Всё, что на версию не похоже, остаётся как есть."""
    return directory.replace("_", ".") if _VERSION_DIR.match(directory) else directory


def filetime_to_datetime(filetime: int) -> Optional[dt.datetime]:
    """
    FILETIME в datetime. None, если дата непредставима.

    Отрицательные значения — не порча архива: в поставках 1С их десятки.
    В БГУ 2.0.110.66 таких записей 10 из 83, в «Бухгалтерии предприятия КОРП»
    3.0.206.19 — 21 из 26. Осмысленной метки времени тут нет, поэтому отдаём
    None: файл получит текущее время, как и для всех прочих дат вне диапазона.
    """
    if filetime <= 0:
        return None
    try:
        return FILETIME_EPOCH + dt.timedelta(microseconds=filetime // 10)
    except (OverflowError, ValueError):
        return None


def safe_relative_parts(src_path: str) -> List[str]:
    """
    Разбирает имя записи архива в безопасный относительный путь.

    Имена в .efd записаны в windows-стиле, но прямой слэш тоже встречается,
    поэтому режем по обоим разделителям. Любая попытка выйти за пределы
    каталога распаковки отвергается, а не исправляется молча: у нас нет
    механизма частичного отчёта, и молчаливый пропуск записи снова дал бы
    пользователю «успешную» распаковку.
    """
    if (
        ntpath.splitdrive(src_path)[0]
        or ntpath.isabs(src_path)
        or posixpath.isabs(src_path)
    ):
        raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path})

    parts: List[str] = []
    for component in src_path.replace("\\", "/").split("/"):
        if component in ("", "."):
            continue
        if component == "..":
            raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path})
        parts.append(component)

    if not parts:
        raise UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": src_path})

    return parts


def read_catalog(handle: BinaryIO, limit: int = CATALOG_PREFIX_LIMIT) -> Catalog:
    """
    Читает оглавление .efd, разжимая не больше `limit` байт.

    Именно это делает осмотр дешёвым: пятнадцать дистрибутивов общим весом
    19 ГБ разбираются за доли секунды, и на диск не попадает ни байта.
    """
    prefix, stream_ended = _inflate_prefix(handle, limit)
    try:
        return parse_catalog(io.BytesIO(prefix))
    except UnpackError as exc:
        truncated = (exc.details or {}).get("reason") == "truncated_header"
        if truncated and not stream_ended:
            # Данных не хватило не потому, что архив обрезан, а потому что мы
            # сами остановились. Путать эти два случая нельзя: первый — порча
            # файла, второй — наш предел.
            raise UnpackError(
                UnpackErrorCode.CORRUPTED_ARCHIVE,
                {"reason": "catalog_too_large", "limit": limit},
            ) from exc
        raise


def _inflate_prefix(handle: BinaryIO, limit: int) -> Tuple[bytes, bool]:
    """Разжимает начало потока. Возвращает данные и признак «поток кончился»."""
    decompressor = zlib.decompressobj(-15)
    out = bytearray()

    while len(out) < limit:
        chunk = handle.read(CATALOG_CHUNK)
        if not chunk:
            return bytes(out), True
        data = decompressor.decompress(chunk, limit - len(out))
        while data:
            out += data
            tail = decompressor.unconsumed_tail
            if not tail or len(out) >= limit:
                break
            data = decompressor.decompress(tail, limit - len(out))
        if decompressor.eof:
            return bytes(out), True

    return bytes(out), False
