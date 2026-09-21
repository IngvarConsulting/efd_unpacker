"""
Опознание вида дистрибутива и построение плана распаковки.

План — неизменяемое значение, которое одинаково рисуют окно, `--dry-run`
и `--json`. Построение — чистая функция от находок и настроек: файловая
система трогается только через внедряемую проверку «уже установлено»,
поэтому вся маршрутизация тестируется без диска.

Вид определяется содержимым, а не именем. Оснований несколько:

- на одной странице релиза платформы 8.3.27 имена следуют четырём
  несовместимым соглашениям, а demo.zip вовсе не содержит версии;
- сайт называет demo.zip «Демонстрационной информационной базой», то есть
  не поставкой, — а внутри настоящая поставка со своим путём в tmplts.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, List, Optional, Sequence, Set, Tuple

from .errors import UnpackError, UnpackErrorCode
from .supply import Catalog, Entry, Template, safe_relative_parts


class ItemKind(Enum):
    """Что мы нашли."""

    SUPPLY = "supply"        # поставка конфигурации: .efd → каталог шаблонов
    PLATFORM = "platform"    # установщик или пакеты платформы 1С
    PACKAGES = "packages"    # набор пакетов .deb/.rpm не от платформы (СУБД и прочее)
    CONTENT = "content"      # .cf/.dt/.epf без .efd — библиотека или выгрузка
    OTHER = "other"          # опознать не удалось


class Action(Enum):
    WRITE = "write"
    SKIP = "skip"
    FAIL = "fail"


class SkipReason(Enum):
    """
    Почему элемент не будет распакован.

    Пропуск известен ДО запуска и попадает в план. Отказ во время исполнения —
    это уже UnpackError, и путать их нельзя: «уже установлено» нормальный
    исход, а не проблема.
    """

    ALREADY_INSTALLED = "already_installed"
    FILTERED_OUT = "filtered_out"
    CONTAINER_UNSUPPORTED = "container_unsupported"
    RAR_TOOL_MISSING = "rar_tool_missing"
    NOTHING_FOUND = "nothing_found"
    NO_TEMPLATES = "no_templates"


@dataclass(frozen=True)
class FoundFile:
    """Файл, найденный внутри контейнеров."""

    trail: Tuple[str, ...]
    size: int

    @property
    def name(self) -> str:
        return self.trail[-1]


@dataclass(frozen=True)
class FoundSupply:
    """Оглавление .efd вместе с путём до него."""

    trail: Tuple[str, ...]
    catalog: Catalog


@dataclass(frozen=True)
class Inspected:
    """Результат осмотра одного исходного файла."""

    path: str
    supplies: Tuple[FoundSupply, ...] = ()
    files: Tuple[FoundFile, ...] = ()
    failure: Optional[UnpackError] = None
    #: Версия платформы, прочитанная из содержимого. Нужна установщику
    #: Windows: в именах его записей версии нет, а в msi — есть.
    platform_version: str = ""

    @property
    def name(self) -> str:
        return posixpath.basename(self.path.replace("\\", "/"))


@dataclass(frozen=True)
class PlannedItem:
    """Одна строка плана: что, куда и будет ли распаковано."""

    kind: ItemKind
    title: str
    version: str
    source: Tuple[str, ...]
    #: Путь исходного файла на диске. План остаётся значением — ни потоков, ни
    #: дескрипторов в нём нет, — но исполнителю нужно чем-то открыть источник
    #: заново, а имя из `source` для этого не годится: там только basename.
    origin: str
    destination: str
    bytes_total: int
    action: Action
    reason: Optional[SkipReason] = None
    failure: Optional[UnpackError] = None
    template: Optional[Template] = None
    files: Tuple[FoundFile, ...] = ()
    # Сколько файлов будет записано. Отдельным числом, а не длиной template.entries:
    # под фильтром часть записей отсеивается, и длина показала бы больше, чем план
    # собирается писать.
    file_count: int = 0

    @property
    def source_path(self) -> str:
        return " → ".join(self.source)


@dataclass(frozen=True)
class Plan:
    items: Tuple[PlannedItem, ...] = ()

    @property
    def to_write(self) -> Tuple[PlannedItem, ...]:
        return tuple(item for item in self.items if item.action is Action.WRITE)

    @property
    def failed(self) -> Tuple[PlannedItem, ...]:
        """Отказы осмотра. Не то же самое, что пропуски: требуют решения."""
        return tuple(item for item in self.items if item.action is Action.FAIL)

    @property
    def bytes_to_write(self) -> int:
        return sum(item.bytes_total for item in self.to_write)


@dataclass(frozen=True)
class PlanSettings:
    """
    Настройки построения плана.

    `is_installed` внедряется, чтобы домен не ходил в файловую систему:
    вся маршрутизация проверяется без диска.
    """

    templates_root: str
    distributions_root: str
    only_configuration: bool = False
    is_installed: Callable[[str], bool] = lambda _destination: False


# --- опознание ---------------------------------------------------------------

# Установщик платформы под Linux: setup-full-8.3.27.2342-x86_64.run,
# setup-thin-8.5.1.1529-x86_64.run. Комплектация читается из имени, а не
# зашита в правило: пока требовалось «setup-full-», тонкий клиент целиком
# уезжал в «прочее» — полгигабайта без опознания.
_PLATFORM_RUN = re.compile(
    r"^setup-(?P<component>[a-z][a-z-]*)-(?P<version>[\d.]+)-(?P<arch>[\w-]+)\.run$", re.I
)
# Установщик платформы под macOS: 1cv8-client-8.5.1.1529.pkg
_PLATFORM_PKG = re.compile(r"^1cv8-(?P<component>[\w.]+?)-(?P<version>[\d.]+)\.pkg$", re.I)
# Пакеты платформы. Правил два, по одному на формат: у deb назначение
# отделено подчёркиванием (thin-client_8.5.1-1529_amd64.deb), у rpm — дефисом
# перед версией (thin-client-8.5.1-1529.x86_64.rpm). Общая регулярка эту
# разницу не берёт: ленивая отрезала от «thin-client» только «thin», и
# тонкий клиент оказывался назначением «thin».
_PLATFORM_DEB = re.compile(
    r"^1c-enterprise-(?P<version>[\d.]+)-(?P<role>[a-z\d-]+)_[\d.]+-\w+_[\w-]+\.deb$", re.I
)
_PLATFORM_RPM = re.compile(
    r"^1c-enterprise-(?P<version>[\d.]+)-(?P<role>[a-z\d-]+)-[\d.]+-\w+\.[\w-]+\.rpm$", re.I
)
# Установщик платформы под Windows. Имя msi — единственное место в архиве,
# где записана комплектация: «1CEnterprise 8 Thin client (x86-64).msi»,
# «1CEnterprise 8 Server (x86-64).msi», «1CEnterprise 8.msi». Имя самого
# архива обманывает — windows64_* это СЕРВЕР, а не 64-битный клиент.
#
# Версии здесь нет вовсе: в именах записей её не бывает ни у одного из десяти
# проверенных архивов. Её читает слой осмотра из содержимого msi.
_WINDOWS_MSI = re.compile(
    r"^1CEnterprise 8(?: (?P<component>[\w ]+?))?(?: \((?P<arch>[\w-]+)\))?\.msi$", re.I
)

#: Система, под которую собран дистрибутив. Задаёт её правило, по которому
#: архив опознан: .run и пакеты — Linux, .pkg — macOS, msi — Windows.
LINUX, WINDOWS, MACOS = "linux", "windows", "macos"

#: Как система называется для человека.
SYSTEM_TITLES = {LINUX: "Linux", WINDOWS: "Windows", MACOS: "macOS"}

#: Как называется комплектация: слаг для каталога и имя для человека.
#:
#: Таблица общая для всех систем намеренно. Одну и ту же комплектацию три
#: системы пишут по-разному — «Thin client» в имени msi, «thin» в имени .run,
#: «thin-client» в имени пакета, — и без приведения к одному виду один выпуск
#: разошёлся бы по трём каталогам. Пустая комплектация — полный комплект: у
#: msi между «8» и расширением нет ничего.
PLATFORM_COMPONENTS = {
    "": ("full", ""),
    "full": ("full", ""),
    "thin": ("thin-client", "тонкий клиент"),
    "thin-client": ("thin-client", "тонкий клиент"),
    "client": ("client", "клиент"),
    "server": ("server", "сервер"),
    "ws": ("ws", "модуль расширения веб-сервера"),
    "crs": ("crs", "сервер хранилища"),
    "common": ("common", "общие файлы"),
}

#: Назначения пакетов по старшинству. Серверный набор состоит из четырёх
#: пакетов — common, server, ws, crs, — и назвать набор по первому попавшемуся
#: значило бы назвать его «общим»: common лежит в КАЖДОМ наборе и потому не
#: различает ничего.
PACKAGE_ROLES = ("server", "thin-client", "client", "ws", "crs", "common")

# Вложенный установщик клиентов. Имени установщика мало: windows64_,
# windows64_with_clients_ и windows64_with_all_clients_ дают ОДНО И ТО ЖЕ имя
# msi и легли бы в один каталог, затирая друг друга. То же и под Linux:
# server64_ и server64_with_all_clients_ содержат один и тот же
# setup-full-*.run, байт в байт. Отличает их ровно этот файл.
_CLIENTS_DISTR = re.compile(
    r"^(?P<bundle>[\w-]+)-clients-distr[_-][\d.]+(?:-[\w-]+)?\.(?:exe|run)$", re.I
)

#: Как называется комплект вложенных клиентов.
CLIENT_BUNDLES = {
    "all": ("all-clients", "со всеми клиентами"),
    "win-mac": ("win-mac-clients", "с клиентами Windows и macOS"),
}

#: Разные написания одной архитектуры. deb зовёт её amd64 и arm64, rpm —
#: x86_64 и aarch64, имя msi — «x86-64». Железо одно, и разные написания
#: развели бы один выпуск по разным каталогам.
ARCH_ALIASES = {"amd64": "x86_64", "arm64": "aarch64"}

_PACKAGE = re.compile(r"\.(deb|rpm)$", re.I)
_CONTENT = re.compile(r"\.(?:cf|cfu|cfe|dt|epf|erf)$", re.I)
_ARCH = re.compile(r"(x86_64|amd64|aarch64|arm64|e2k|i386|noarch)", re.I)
_ARCH_EXACT = re.compile(r"^(?:x86_64|amd64|aarch64|arm64|e2k|i386|noarch)$", re.I)
_VERSION = re.compile(r"^\d+\.\d+(?:[.\-][\w.]+)*$")


@dataclass(frozen=True)
class Classification:
    """Что опознано по содержимому."""

    kind: ItemKind
    title: str
    version: str = ""
    component: str = ""
    arch: str = ""
    system: str = ""


def classify(files: Sequence[FoundFile]) -> Classification:
    """
    Вид, наименование, версия, компонента и архитектура по содержимому.

    Порядок правил — от самого определённого к самому общему; выведен из
    разбора настоящих дистрибутивов с releases.1c.ru.
    """
    for found in files:
        match = _PLATFORM_RUN.match(found.name)
        if match:
            return _platform_installer(
                files, LINUX,
                match.group("component"), match.group("version"), match.group("arch"),
            )

    for found in files:
        match = _PLATFORM_PKG.match(found.name)
        if match:
            slug, russian = platform_component(match.group("component"))
            return Classification(
                ItemKind.PLATFORM, _platform_title(MACOS, russian),
                match.group("version"), slug, architecture_of(files), MACOS,
            )

    for found in files:
        match = _WINDOWS_MSI.match(found.name)
        if match:
            # Версия остаётся пустой — в именах записей её нет. Её подставляет
            # слой осмотра, прочитав содержимое msi; без неё опознание всё
            # равно верное, просто каталог окажется без номера.
            return _platform_installer(
                files, WINDOWS, match.group("component") or "", "", match.group("arch") or "",
            )

    platform = _platform_packages(files)
    if platform is not None:
        return platform

    packages = [found for found in files if _PACKAGE.search(found.name)]
    if packages:
        return Classification(
            ItemKind.PACKAGES, _product_of(packages) or "Набор пакетов",
            _version_of(packages), "packages-%s" % _formats_of(packages),
            architecture_of(files),
        )

    if any(_CONTENT.search(found.name) for found in files):
        return Classification(ItemKind.CONTENT, "Файлы конфигураций и выгрузок")

    return Classification(ItemKind.OTHER, "")


def is_windows_installer(name: str) -> bool:
    """Тот самый msi, из которого слой осмотра достаёт версию платформы."""
    return bool(_WINDOWS_MSI.match(name))


def platform_component(component: str) -> Tuple[str, str]:
    """
    Слаг каталога и русское имя комплектации.

    Незнакомую отдаём как есть: правило «не знаю — значит прочее» здесь не
    годится, опознание уже состоялось, и потерять его из-за незнакомого слова
    было бы хуже, чем показать это слово человеку.
    """
    key = component.strip().lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    return PLATFORM_COMPONENTS.get(key, (key, key))


def _platform_title(system: str, *parts: str) -> str:
    """«Платформа 1С:Предприятия для Windows» и уточнения через запятую."""
    head = "Платформа 1С:Предприятия"
    if system:
        head = "%s для %s" % (head, SYSTEM_TITLES.get(system, system))
    named = [part for part in parts if part]
    return head + (", " + ", ".join(named) if named else "")


def _platform_installer(
    files: Sequence[FoundFile], system: str, component: str, version: str, arch: str,
) -> Classification:
    """
    Опознание установщика платформы: комплектация, вложенные клиенты, разрядность.

    Одна функция на Windows и Linux намеренно. Различаются у них только имена
    файлов, откуда берутся эти три вещи; само правило — то же самое, и
    вложенные клиенты, выведенные на Windows в #63, ровно так же разводят по
    каталогам server64_ и server64_with_all_clients_ под Linux.
    """
    slug, russian = platform_component(component)
    bundle_slug, bundle_russian = _bundled_clients(files)
    if bundle_slug:
        slug = "%s-%s" % (slug, bundle_slug)
    return Classification(
        ItemKind.PLATFORM, _platform_title(system, russian, bundle_russian),
        version, slug, normalize_arch(arch), system,
    )


def _bundled_clients(files: Sequence[FoundFile]) -> Tuple[str, str]:
    """Комплект вложенных клиентов, если он есть. Иначе две пустые строки."""
    for found in files:
        match = _CLIENTS_DISTR.match(found.name)
        if match:
            bundle = match.group("bundle").lower()
            return CLIENT_BUNDLES.get(bundle, ("%s-clients" % bundle, bundle))
    return "", ""


def _platform_packages(files: Sequence[FoundFile]) -> Optional[Classification]:
    """
    Набор пакетов платформы: назначение, формат и версия по именам внутри.

    Формат в имени каталога — не украшение. Один выпуск приходит и в deb, и в
    rpm, и после приведения amd64 к x86_64 различать их стало бы нечем: два
    набора легли бы в один каталог и перемешались. У эльбруса пара deb/rpm
    сталкивалась и без всякого приведения — её архитектуру оба формата и так
    называли одинаково.
    """
    matched: List[FoundFile] = []
    roles = set()
    version = ""
    for found in files:
        for pattern in (_PLATFORM_DEB, _PLATFORM_RPM):
            match = pattern.match(found.name)
            if match is None:
                continue
            roles.add(match.group("role").lower())
            matched.append(found)
            version = version or match.group("version")
            break
    if not roles:
        return None

    slug, russian = platform_component(_package_role(roles))
    formats = _formats_of(matched)
    return Classification(
        ItemKind.PLATFORM, _platform_title(LINUX, russian, "пакеты %s" % formats),
        version, "%s-%s" % (slug, formats), architecture_of(matched), LINUX,
    )


def _package_role(roles: Set[str]) -> str:
    """
    Назначение набора — старшее из встреченных.

    Языковые пакеты (server-nls рядом с server) отдельно не разбираются, и
    это решение, а не упущение: во всех четырнадцати проверенных архивах
    языковой пакет лежит рядом со своим основным, и старшинство находит
    основной само. А там, где языковой пакет пришёл БЕЗ основного, отрезать
    «-nls» было бы прямо вредно: набор получил бы имя каталога настоящего
    набора и лёг бы поверх него.

    Незнакомый набор называем всеми назначениями сразу: угадывать старшее
    среди незнакомых нечем, а два разных набора обязаны разойтись по разным
    каталогам — ровно об этом вся задача.
    """
    for role in PACKAGE_ROLES:
        if role in roles:
            return role
    return "-".join(sorted(roles))


def _formats_of(packages: Sequence[FoundFile]) -> str:
    """Форматы пакетов в наборе, через дефис: «deb», «rpm», «deb-rpm»."""
    found = set()
    for package in packages:
        match = _PACKAGE.search(package.name)
        if match:
            found.add(match.group(1).lower())
    return "-".join(sorted(found))


def normalize_arch(arch: str) -> str:
    """
    Архитектура в одном написании.

    Дефис в «x86-64» из имени msi — то же подчёркивание, что у .run и .deb;
    остальные написания разводит таблица.
    """
    arch = arch.strip().lower().replace("-", "_")
    return ARCH_ALIASES.get(arch, arch)


def architecture_of(files: Sequence[FoundFile]) -> str:
    """Архитектура из имён внутри, в одном написании. Пусто, если не выводится."""
    for found in files:
        match = _ARCH.search(found.name)
        if match:
            return normalize_arch(match.group(1))
    return ""


def _product_of(packages: Sequence[FoundFile]) -> str:
    """Имя продукта по самому частому началу имён пакетов."""
    stems = [package.name.split("_")[0].split("-")[0].lower() for package in packages]
    return max(set(stems), key=stems.count) if stems else ""


def _version_of(packages: Sequence[FoundFile]) -> str:
    """
    Версия по соглашению имён пакета. У deb и rpm они разные.

    deb: <имя>_<версия>_<архитектура>.deb
    rpm: <имя>-<версия>-<выпуск>.<архитектура>.rpm — подчёркиваний нет вовсе,
         поэтому разбор по deb-правилу давал пустую версию, и разные выпуски
         сходились в один каталог «unknown».

    Общая регулярка тут не годится: на postgresql-18_18.4-1.1C_amd64.deb она
    захватывала «18.4-1.1C_amd64.deb» целиком.
    """
    for package in packages:
        name = package.name
        version = _rpm_version(name) if name.lower().endswith(".rpm") else _deb_version(name)
        if version:
            return version
    return ""


def _deb_version(name: str) -> str:
    parts = name.rsplit(".", 1)[0].split("_")
    return parts[1] if len(parts) >= 2 and _VERSION.match(parts[1]) else ""


def _rpm_version(name: str) -> str:
    """Версия и выпуск из <имя>-<версия>-<выпуск>.<архитектура>.rpm."""
    stem = name[: -len(".rpm")]
    head, _, tail = stem.rpartition(".")
    if head and _ARCH_EXACT.match(tail):
        stem = head
    fields = stem.split("-")
    if len(fields) >= 3 and fields[-2][:1].isdigit():
        return "-".join(fields[-2:])
    return ""


# --- построение плана ---------------------------------------------------------


def build_plan(inspected: Sequence[Inspected], settings: PlanSettings) -> Plan:
    """Собирает план из результатов осмотра. Чистая функция."""
    items: List[PlannedItem] = []
    for result in inspected:
        items.extend(_items_for(result, settings))
    return Plan(items=tuple(items))


def _items_for(result: Inspected, settings: PlanSettings) -> List[PlannedItem]:
    if result.failure is not None:
        return [_failed_item(result)]
    if result.supplies:
        items: List[PlannedItem] = []
        for found in result.supplies:
            if not found.catalog.templates:
                # Оглавление прочитано, но устанавливать нечего. Пропустить
                # строку значило бы потерять исходный файл из плана целиком.
                items.append(
                    PlannedItem(
                        kind=ItemKind.SUPPLY, title=result.name, version="",
                        source=found.trail, origin=result.path, destination="",
                        bytes_total=0, action=Action.SKIP,
                        reason=SkipReason.NO_TEMPLATES,
                    )
                )
                continue
            items.extend(
                _supply_item(result, found, template, settings)
                for template in found.catalog.templates
            )
        return items
    if result.files:
        return [_distribution_item(result, settings)]
    return [
        PlannedItem(
            kind=ItemKind.OTHER, title=result.name, version="", source=(result.name,),
            origin=result.path, destination="", bytes_total=0, action=Action.SKIP,
            reason=SkipReason.NOTHING_FOUND,
        )
    ]


def _failed_item(result: Inspected) -> PlannedItem:
    """
    Отказ осмотра — тоже строка плана: молча терять файл нельзя.

    Но пропуск и отказ здесь различаются. «Формат не поддержан» — ожидаемый
    исход, о нём достаточно сообщить. Повреждённый архив, слишком глубокая
    вложенность или попытка выйти за каталог распаковки — это отказ, который
    требует решения, и выдавать его за рядовой пропуск нельзя: план выглядел
    бы исполнимым, а причина терялась.
    """
    failure = result.failure
    code = failure.code if failure is not None else None
    details = (failure.details or {}) if failure is not None else {}

    if code is UnpackErrorCode.CONTAINER_UNSUPPORTED:
        reason = (
            SkipReason.RAR_TOOL_MISSING
            if details.get("kind") == "rar"
            else SkipReason.CONTAINER_UNSUPPORTED
        )
        return PlannedItem(
            kind=ItemKind.OTHER, title=result.name, version="", source=(result.name,),
            origin=result.path, destination="", bytes_total=0, action=Action.SKIP,
            reason=reason, failure=failure,
        )

    return PlannedItem(
        kind=ItemKind.OTHER, title=result.name, version="", source=(result.name,),
        origin=result.path, destination="", bytes_total=0, action=Action.FAIL,
        failure=failure,
    )


def _supply_item(
    result: Inspected, found: FoundSupply, template: Template, settings: PlanSettings
) -> PlannedItem:
    info = found.catalog.describe()
    entries = template.entries
    if settings.only_configuration:
        kept = tuple(entry for entry in entries if keeps_configuration(entry.path))
    else:
        kept = entries

    destination = _join(settings.templates_root, template.root)
    action, reason = Action.WRITE, None
    if settings.is_installed(destination):
        action, reason = Action.SKIP, SkipReason.ALREADY_INSTALLED
    elif not kept or _filter_took_everything(entries, kept):
        action, reason = Action.SKIP, SkipReason.FILTERED_OUT

    return PlannedItem(
        kind=ItemKind.SUPPLY,
        title=(info.name if info and info.name else template.relative_path),
        version=template.version,
        source=found.trail,
        origin=result.path,
        destination=destination,
        bytes_total=sum(entry.size for entry in kept),
        action=action,
        reason=reason,
        template=template,
        file_count=len(kept),
    )


def _filter_took_everything(entries: Sequence[Entry], kept: Sequence[Entry]) -> bool:
    """
    Унёс ли фильтр ВСЕ файлы, ради которых шаблон существует.

    Шаблон, у которого единственная конфигурация лежит в .dt, при «без
    демобаз» записывался каталогом с манифестом и ReadMe — и отчитывался как
    успешный. В 1С такой шаблон виден пунктом, который ничего не создаёт, и
    человек узнаёт об этом уже там, без единого намёка на причину. Настоящий
    случай: Platform8Demo/1_0_41_3 из demo.zip платформы 8.3.27.

    Условие с двух сторон: фильтр ЧТО-ТО унёс, и не осталось НИЧЕГО, кроме
    сопровождения. Обе половины нужны.

    «Что-то унёс» — чтобы правило не судило о шаблоне, к которому фильтр не
    прикасался. Поставка из одного манифеста и описания бесполезна и так, но
    это не наша новость и не повод её терять.

    «Ничего, кроме сопровождения» — а не «ни одной знакомой конфигурации».
    Разница видна на шаблоне из `payload.bin`, `1cv8.dt` и манифеста:
    демобазу фильтр унёс, но `payload.bin` уцелел — и, быть может, он-то и
    есть то, ради чего шаблон нужен. Молча выбросить его нельзя.

    Отдельной проверки «включён ли фильтр» здесь нет: без него kept и есть
    entries, и унести что-то он не мог по определению.
    """
    return len(kept) != len(entries) and all(is_auxiliary(entry.path) for entry in kept)


def _identifies_its_contents(found: Classification) -> bool:
    """
    Говорит ли каталог назначения о том, что в нём лежит.

    Только опознанный вид с прочитанной версией: по ним адрес складывается
    из свойств самого дистрибутива. Всё прочее берёт имя из входного файла
    или подставляет «unknown» — такой каталог не опознаёт ничего, и
    «он уже есть» не значит «это то же самое».
    """
    return found.kind in (ItemKind.PLATFORM, ItemKind.PACKAGES) and bool(found.version)


def _distribution_item(result: Inspected, settings: PlanSettings) -> PlannedItem:
    found = classify(result.files)
    if not found.version and result.platform_version:
        # Опознание идёт по именам записей и версии у Windows-установщика не
        # находит — её принёс слой осмотра, прочитав содержимое msi.
        found = replace(found, version=result.platform_version)
    stem = _stem(result.name)

    if found.kind is ItemKind.PLATFORM:
        parts = ("platform", found.version or "unknown", _component(found))
    elif found.kind is ItemKind.PACKAGES:
        parts = (found.title.lower(), found.version or "unknown", _component(found))
    elif found.kind is ItemKind.CONTENT:
        parts = ("content", stem)
    else:
        parts = ("other", stem)

    destination = _join(settings.distributions_root, parts)

    # Та же мерка, что у шаблонов: каталог есть — значит уже распаковано.
    # Но только там, где адрес ОПОЗНАЁТ содержимое.
    #
    # У шаблона он опознаёт всегда: «1c/<продукт>/<версия>». У дистрибутива —
    # лишь когда известны вид и версия. «content/<имя файла>» и
    # «other/<имя файла>» берутся из имени входного файла, и два разных
    # архива с одинаковым именем из разных папок дали бы один адрес: второй
    # молча пропустился бы, хотя внутри у него другое. То же и с
    # «platform/unknown/…»: версия не прочиталась, и каталог не говорит ни о
    # чём.
    #
    # ВНИМАНИЕ. Оборванная распаковка тоже оставляет каталог, и такой
    # дистрибутив будет считаться распакованным. Отменить пропуск из окна
    # нельзя: знак у пропущенной строки не переключается (см. TOGGLEABLE в
    # presentation/rows.py), и вернуть строку в работу можно только удалив
    # каталог руками. Это разобрано отдельно, здесь не решается.
    action, reason = Action.WRITE, None
    if _identifies_its_contents(found) and settings.is_installed(destination):
        action, reason = Action.SKIP, SkipReason.ALREADY_INSTALLED

    return PlannedItem(
        kind=found.kind,
        title=found.title or result.name,
        version=found.version,
        source=(result.name,),
        origin=result.path,
        destination=destination,
        bytes_total=sum(entry.size for entry in result.files),
        action=action,
        reason=reason,
        files=result.files,
        file_count=len(result.files),
    )


#: Что отбрасывает `--only cf`. Выгрузка .dt — это демонстрационная база
#: данных: она весит примерно столько же, сколько сама конфигурация, и нужна
#: далеко не всегда. Правило «выбросить .dt», а не «оставить .cf»: в шаблоне
#: лежат ещё манифест, ReadMe и ресурсы, и без них 1С покажет неполный шаблон.
DATA_SUFFIXES = (".dt",)

#: Что само по себе базу не делает: манифест и документация. Нужно, чтобы
#: отличить «фильтр унёс всё» от «остался файл, про который мы ничего не
#: знаем»: во втором случае шаблон обязан записаться, каким бы незнакомым
#: этот файл ни был.
AUXILIARY_SUFFIXES = (".mft", ".txt", ".htm", ".html", ".pdf", ".doc", ".docx", ".rtf")


def is_auxiliary(path: str) -> bool:
    """Сопровождение: манифест, ReadMe, документация. Базу из этого не сделать."""
    return path.lower().endswith(AUXILIARY_SUFFIXES)


def keeps_configuration(path: str) -> bool:
    """
    Остаётся ли запись при `--only cf`.

    Одно правило на план и на исполнение. Когда их было два, план обещал
    2.1 МБ, а записывалось 376 КБ: план выбрасывал .dt, а исполнитель оставлял
    только .cf и манифест.
    """
    return not path.lower().endswith(DATA_SUFFIXES)


def holds_data(template: Template) -> bool:
    """
    Есть ли в шаблоне то, что «без демобаз» оставит внутри архива.

    Вопрос к содержимому, а не к настройке: над шаблоном из одной
    конфигурации фильтр не отнимает ничего, и распаковка выходит полной,
    сколько бы флажков ни стояло.
    """
    return any(not keeps_configuration(entry.path) for entry in template.entries)


def _component(found: Classification) -> str:
    """
    Имя каталога компоненты: «macos-client», «linux-server-deb-x86_64».

    Система идёт первой, и она обязательна для платформы: комплектации у всех
    систем называются одинаково — «полный», «тонкий клиент», «сервер», — и
    полный установщик Linux с полным установщиком Windows одной версии
    совпадали по всем трём признакам разом.

    Чужому набору пакетов система не нужна и не ставится: он назван продуктом
    и форматом, и двух систем под одним таким именем не бывает.
    """
    parts = [part for part in (found.system, found.component, found.arch) if part]
    return "-".join(parts) or "installer"


def _join(root: str, parts: Sequence[str]) -> str:
    """
    Склеивает путь назначения из санированных частей.

    Части выводятся из имён внутри архива, то есть из чужих данных: без
    санирования `../../etc` в имени уехал бы прямо в путь.
    """
    safe: List[str] = []
    for part in parts:
        safe.extend(safe_relative_parts(part))
    return posixpath.join(root.replace("\\", "/"), *safe)


def _stem(name: str) -> str:
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name.rsplit(".", 1)[0] if "." in name else name
