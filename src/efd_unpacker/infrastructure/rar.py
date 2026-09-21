"""
Поиск внешней программы для .rar и проверка её на самом архиве.

Все двенадцать дистрибутивов платформы под Windows — это RAR5 со сжатыми
записями. Чистый Python их не читает: rarfile без внешнего unrar берёт только
несжатые. Поэтому распаковка делегируется сторонней программе.

Вызов отдельного процесса — не линковка, поэтому ни исходников unrar, ни
бинарников в поставке нет; заодно отпадает сборка libarchive под три системы.

Ключевое решение: пригодность проверяется НА ЭТОМ АРХИВЕ, а не по версии.
Набор форматов libarchive задаётся при сборке, и у Microsoft, Debian и Apple
он разный — утверждать, что bundled tar.exe умеет RAR, нельзя. К тому же
solid-архивы даются libarchive хуже, и проверка на конкретном файле ловит это
сама, без списка исключений.
"""

from __future__ import annotations

import locale
import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..domain.errors import UnpackError, UnpackErrorCode
from ..domain.supply import safe_relative_parts

#: Сколько ждём программу. Оглавление RAR5 читается за миллисекунды, поэтому
#: предел щедрый только по меркам заголовка: зависшая программа не должна
#: превращать осмотр каталога загрузок в бесконечное ожидание.
LIST_TIMEOUT = 20.0
EXTRACT_TIMEOUT = 1800.0

#: Дата в выводе libarchive зависит от локали, а LC_ALL=C ломает не-ASCII имена
#: (превращает их в восьмеричные escape-последовательности). Поэтому меняется
#: только LC_TIME: дата становится предсказуемой, имена остаются целыми.
_LISTING_DATE = re.compile(r"\s([A-Z][a-z]{2}\s+\d{1,2}\s+(?:\d{2}:\d{2}|\d{4}))\s")

LIBARCHIVE = "libarchive"
SEVENZIP = "sevenzip"
UNAR = "unar"

#: Как семейство называется человеку. Имя в PATH («7zz») ничего не говорит,
#: а «7-Zip» узнаётся с первого взгляда и совпадает с тем, что человек будет
#: искать в поисковике.
FAMILY_TITLES = {
    LIBARCHIVE: "libarchive", SEVENZIP: "7-Zip", UNAR: "The Unarchiver",
}


@dataclass(frozen=True)
class Tool:
    """Найденная программа: чем запускать и что она умеет."""

    path: str
    family: str
    version: str = ""
    #: Чем запустить сам path. Пусто для настоящей программы; в тестах сюда
    #: уезжает интерпретатор, чтобы подставная «программа» была переносимой.
    prefix: Tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def extractor(self) -> str:
        """
        Чем распаковывать. У большинства это сам path, у The Unarchiver —
        парный бинарник рядом: перечисляет lsar, распаковывает unar. Ставятся
        они одним пакетом и лежат в одном каталоге.
        """
        if self.family != UNAR:
            return self.path
        return _sibling(self.path, "unar")

    def command(self, arguments: Sequence[str]) -> List[str]:
        return list(self.prefix) + [self.path] + list(arguments)

    def extract_command(self, arguments: Sequence[str]) -> List[str]:
        return list(self.prefix) + [self.extractor] + list(arguments)


@dataclass(frozen=True)
class RarEntry:
    """Запись внутри .rar."""

    name: str
    size: int
    #: Символьная ссылка. На диске она не файл заявленного размера, поэтому
    #: проверять пригодность программы на ней нельзя.
    link: bool = False
    #: Номер записи в оглавлении. Нужен только The Unarchiver: выбрать одну
    #: запись он умеет по номеру, а не по имени. У прочих семейств остаётся
    #: -1 и не используется.
    index: int = -1


def _sibling(path: str, name: str) -> str:
    """Парный бинарник в том же каталоге, с тем же расширением."""
    suffix = ".exe" if path.lower().endswith(".exe") else ""
    return os.path.join(os.path.dirname(path), name + suffix)


def _environment() -> Dict[str, str]:
    """Окружение для запуска: предсказуемая дата, нетронутая кодировка."""
    env = dict(os.environ)
    env.pop("LC_ALL", None)  # иначе LC_TIME ниже не подействует
    env["LC_TIME"] = "C"
    return env


# --- поиск кандидатов --------------------------------------------------------

#: Имена в PATH по системам, от самого вероятного к самому редкому.
#:
#: unrar намеренно не включён: в Debian он несвободный, а свободный unrar-free
#: плохо тянет RAR5 — то есть именно наш случай.
#:
#: unar и UnRAR.exe отложены: у первого оглавление и распаковку делают разные
#: бинарники и нет выбора одной записи, у второго свой диалект аргументов.
#: Ни того, ни другого мне не на чем проверить, а разборщик вывода, который
#: никогда не видел настоящей программы, — это молчаливый дефект.
_NAMES = {
    "darwin": (
        ("bsdtar", LIBARCHIVE), ("7zz", SEVENZIP), ("7z", SEVENZIP), ("lsar", UNAR),
    ),
    # Под Windows The Unarchiver не ищем: он там редкость, а поиск стоит
    # запуска процесса на каждый кандидат.
    "win32": (("tar", LIBARCHIVE), ("7z", SEVENZIP), ("7za", SEVENZIP)),
}
_DEFAULT_NAMES = (
    ("bsdtar", LIBARCHIVE), ("7zz", SEVENZIP), ("7z", SEVENZIP), ("7za", SEVENZIP),
    ("lsar", UNAR),
)

#: Где Windows хранит путь установки. Перебирать каталоги нельзя: Program Files
#: бывает локализован, а пользовательская установка лежит вовсе не там.
_REGISTRY = ((r"SOFTWARE\7-Zip", "Path", "7z.exe", SEVENZIP),)

_cache: Dict[Tuple[str, ...], Tuple[Tool, ...]] = {}

#: Значение --rar-tool. Глобальное намеренно: это настройка запуска, как язык
#: интерфейса, и протаскивать её через осмотр, спуск по контейнерам и разбор
#: архива — четыре слоя, которым она не нужна, — значит замусорить их подписи.
_configured: Optional[str] = None


@dataclass(frozen=True)
class Probe:
    """
    Чем и на чём в последний раз читалось оглавление .rar.

    Пригодность программы проверяется на самом архиве, а не по версии, —
    и экрану настроек нечего сказать про неё, кроме результата этой проверки.
    Записываем факт, а не предположение: «проверена на вашем архиве» без
    такой записи было бы выдумкой.
    """

    tool: Tool
    archive: str
    entries: int


#: Последняя удачная проверка. Пишется из потока распаковки, читается из
#: потока окна: замена ссылки на неизменяемый объект целиком, без частично
#: заполненного состояния посередине.
_probe: Optional[Probe] = None


def last_probe() -> Optional[Probe]:
    """Результат последней удачной проверки на настоящем архиве, если он был."""
    return _probe


def configure(path: Optional[str]) -> None:
    """
    Запомнить программу, указанную --rar-tool, на весь запуск.

    Кеш сбрасывать не нужно: он ключуется выбранной программой, поэтому смена
    значения сама по себе даёт другой ключ.
    """
    global _configured
    _configured = path or None


def discover(extra: Optional[str] = None) -> Tuple[Tool, ...]:
    """
    Кандидаты, найденные один раз за запуск.

    Кешируется целиком: обход PATH и запуск каждой программы за версией стоят
    дороже, чем чтение оглавления, и повторять их на каждый файл незачем.
    `extra` — значение --rar-tool, оно идёт первым и поиск не отменяет:
    подставленная программа тоже проверяется на архиве.
    """
    chosen = extra or _configured
    key = (chosen or "",)
    if key not in _cache:
        _cache[key] = tuple(_candidates(chosen))
    return _cache[key]


def found() -> Optional[Tuple[Tool, ...]]:
    """
    Что уже нашли, без нового поиска. None — ещё не искали.

    Меню шестерёнки показывает рядом с пунктом количество найденного, а
    открывается оно в потоке окна: звать туда discover() значит ждать запуска
    каждого кандидата ради одной цифры. Не знаем — не пишем.
    """
    return _cache.get((_configured or "",))


def forget() -> None:
    """
    Сбросить всё, что узнали о программах: и кеш поиска, и запись о проверке.

    Нужен тестам, смене --rar-tool в одном процессе и кнопке «Искать заново».
    Запись о проверке уходит вместе с кешем намеренно: она говорит про
    программу из этого кеша, и пережить его — значит утверждать про
    программу, которой в списке больше нет.
    """
    global _probe
    _cache.clear()
    _probe = None


def reset() -> None:
    """Полный сброс: и кеш, и выбранная программа. Только для тестов."""
    global _configured
    _configured = None
    forget()


def known_families() -> Tuple[str, ...]:
    """
    Семейства программ, которые приложение ищет на этой системе.

    Экрану настроек нужен не только список найденного: «не найден» несёт
    смысл лишь рядом с именем того, кого искали. Порядок — тот же, что у
    поиска, по нему видно, кого позовут первым.
    """
    families: List[str] = []
    for _name, family in _NAMES.get(sys.platform, _DEFAULT_NAMES):
        if family not in families:
            families.append(family)
    return tuple(families)


def searched_names(family: str) -> Tuple[str, ...]:
    """Под какими именами семейство ищется в PATH. Показывается человеку."""
    return tuple(
        name for name, other in _NAMES.get(sys.platform, _DEFAULT_NAMES) if other == family
    )


def _candidates(extra: Optional[str]) -> List[Tool]:
    found: List[Tool] = []
    seen = set()

    def add(path: Optional[str], family: str) -> None:
        if not path:
            return
        # На macOS /usr/bin/tar — символьная ссылка на bsdtar: без разрешения
        # пути один и тот же бинарник проверялся бы дважды.
        real = os.path.realpath(path)
        if real in seen or not os.path.isfile(real):
            return
        if family == UNAR and not os.path.isfile(_sibling(path, "unar")):
            # Перечисляет lsar, распаковывает unar. Один без другого
            # бесполезен, и брать такую «программу» в кандидаты — значит
            # обещать распаковку, которой не будет.
            return
        seen.add(real)
        found.append(Tool(path=path, family=family, version=_version(path, family)))

    if extra:
        add(shutil.which(extra) or extra, _guess_family(extra))

    for name, family in _NAMES.get(sys.platform, _DEFAULT_NAMES):
        add(shutil.which(name), family)

    for path, family in _from_registry():
        add(path, family)

    return found


def _guess_family(path: str) -> str:
    """Семейство по имени файла: у каждого свой язык аргументов."""
    stem = os.path.basename(path).lower()
    for suffix in (".exe", ".bat", ".cmd"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    if stem in ("bsdtar", "tar"):
        return LIBARCHIVE
    return UNAR if stem in ("lsar", "unar") else SEVENZIP


def _from_registry() -> List[Tuple[str, str]]:
    """Пути установки 7-Zip и WinRAR из реестра. Вне Windows — пусто."""
    if sys.platform != "win32":
        return []
    try:
        import winreg  # noqa: PLC0415 - модуль существует только на Windows
    except ImportError:  # pragma: no cover - на Windows он всегда есть
        return []

    results = []
    for subkey, value_name, executable in ((k, v, e) for k, v, e, _f in _REGISTRY):
        family = next(f for k, v, _e, f in _REGISTRY if k == subkey and v == value_name)
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, subkey) as handle:
                    value = winreg.QueryValueEx(handle, value_name)[0]
            except OSError:
                continue
            if not isinstance(value, str) or not value:
                continue
            results.append((os.path.join(value, executable) if executable else value, family))
    return results


def _version(path: str, family: str, prefix: Sequence[str] = ()) -> str:
    """
    Версия программы — часть ключа, по которому запоминается пригодность.

    Пустая строка тоже годится: программа без внятного ответа о версии всё
    равно будет проверена на самом архиве.
    """
    # 7-Zip печатает баннер с версией, если запустить его без аргументов;
    # --version он не понимает вовсе.
    arguments = {LIBARCHIVE: ["--version"], UNAR: ["-v"]}.get(family, [])
    try:
        completed = subprocess.run(
            list(prefix) + [path] + arguments, capture_output=True,
            timeout=LIST_TIMEOUT, env=_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = _decode(completed.stdout or completed.stderr or b"").strip().splitlines()
    return lines[0].strip() if lines else ""


# --- оглавление --------------------------------------------------------------


def read_entries(
    archive: str, extra: Optional[str] = None
) -> Tuple[Tool, Tuple[RarEntry, ...]]:
    """
    Оглавление архива первой программой, которая смогла его прочитать.

    Возвращает и саму программу: размеры записей объявила именно она, и
    извлекать запись потом должна она же. Иначе лист, созданный по оглавлению
    одной программы, мог бы наполниться другой — с другим объявленным
    размером. Воспроизведено: лист заявлял 100 байт и отдавал 6.

    Чтение оглавления и есть проверка пригодности: отдельного пробного запуска
    нет, потому что результат нужен в любом случае. На настоящем
    setuptc64_8_3_27_2342.rar системный bsdtar отдаёт 44 записи за 8 мс.

    Здесь же единственная точка, где имена проверяются: дальше они уходят
    аргументами во внешнюю программу, и `../../` в имени распаковало бы файл
    за пределы назначения руками самой программы.
    """
    global _probe
    for tool in discover(extra):
        entries = list_entries(tool, archive)
        if entries is not None:
            checked = _checked(entries)
            _probe = Probe(tool=tool, archive=os.path.basename(archive), entries=len(checked))
            return tool, checked
    raise UnpackError(
        UnpackErrorCode.CONTAINER_UNSUPPORTED,
        {"entry": os.path.basename(archive), "kind": "rar", "hint": install_hint()},
    )


def _checked(entries: Sequence[RarEntry]) -> Tuple[RarEntry, ...]:
    """
    Проверяет имена, пришедшие от внешней программы.

    Имена — чужие данные, и уходят они аргументами в чужой же процесс:
    `../../escaped.txt` распаковался бы за пределы назначения руками самой
    программы, мимо всех наших проверок. Поэтому то же правило, что для
    записей zip и .efd.

    Одинаковые имена отклоняются: внешняя программа выбирает запись по имени,
    поэтому два листа с одним именем дали бы одно и то же содержимое, и хотя
    бы один перестал бы совпадать с заявленным размером. Для .efd этот случай
    уже отклоняется тем же кодом.
    """
    seen = set()
    for entry in entries:
        parts = tuple(safe_relative_parts(entry.name))
        if parts in seen:
            raise UnpackError(
                UnpackErrorCode.CORRUPTED_ARCHIVE,
                {"reason": "duplicate_entry", "entry": entry.name},
            )
        seen.add(parts)
    return tuple(entries)


def _produced(destination: str, entry: RarEntry) -> bool:
    """
    Появился ли обычный файл нужного размера внутри каталога назначения.

    Именно обычный и именно внутри: архив может нести символьную ссылку, и
    распакованная ссылка на файл хозяина открылась бы как содержимое архива.
    Тот же случай уже ловился для образов .dmg — здесь он вернулся другим
    путём.
    """
    produced = os.path.join(destination, *entry.name.split("/"))
    if os.path.islink(produced) or not os.path.isfile(produced):
        return False
    try:
        root = os.path.realpath(destination)
        if os.path.commonpath([root, os.path.realpath(produced)]) != root:
            return False
    except ValueError:  # pragma: no cover - разные тома на Windows
        return False
    return os.path.getsize(produced) == entry.size


def list_entries(tool: Tool, archive: str) -> Optional[Tuple[RarEntry, ...]]:
    """Оглавление этой программой, либо None, если она не справилась."""
    arguments = {
        LIBARCHIVE: ["-tvf", archive],
        UNAR: ["-j", archive],
    }.get(tool.family, ["l", "-slt", "-ba", "-sccUTF-8", archive])
    completed = _run(tool.command(arguments), LIST_TIMEOUT)
    if completed is None or completed.returncode != 0:
        return None
    output = _decode(completed.stdout)
    # Пустой кортеж и None — разные ответы: первый значит «архив пуст», второй
    # «программа не справилась». Сливать их значило бы объявить пустой архив
    # неподдерживаемым форматом.
    parse = {
        LIBARCHIVE: _parse_libarchive, UNAR: _parse_unar,
    }.get(tool.family, _parse_sevenzip)
    return parse(output)


def _parse_libarchive(output: str) -> Tuple[RarEntry, ...]:
    """
    Разбор `bsdtar -tvf`, привязанный к дате, а не к номерам колонок.

    По позициям разбирать нельзя: имя владельца и группы бывают с пробелами,
    и колонки съезжают. Дата при LC_TIME=C всегда «Mon DD HH:MM» или
    «Mon DD  YYYY», поэтому она и служит якорем: до неё последнее слово —
    размер, после неё — имя целиком, вместе с пробелами.

    Проверено на настоящем RAR5: 44 записи из 44, включая имена с пробелами
    и кириллицей.
    """
    entries = []
    for line in output.splitlines():
        match = _LISTING_DATE.search(line)
        if not match:
            continue
        head, name = line[: match.start()], line[match.end():]
        size = head.rsplit(None, 1)[-1] if head.split() else ""
        if not size.isdigit():
            continue
        # У символьной ссылки libarchive дописывает « -> цель».
        name, arrow, _target = name.partition(" -> ")
        if name and not name.endswith("/"):
            entries.append(RarEntry(name=name, size=int(size), link=bool(arrow)))
    return tuple(entries)


def _parse_sevenzip(output: str) -> Tuple[RarEntry, ...]:
    """
    Разбор `7z l -slt`: блоки «ключ = значение», разделённые пустой строкой.

    Формат выбран именно за это — он не зависит ни от локали, ни от ширины
    колонок. Каталоги отличаются атрибутом D и в список не попадают.
    """
    entries = []
    path = ""
    size = ""
    folder = False

    def flush() -> None:
        if path and not folder and size.isdigit():
            entries.append(RarEntry(name=path.replace("\\", "/"), size=int(size)))

    for line in output.splitlines():
        if not line.strip():
            flush()
            path, size, folder = "", "", False
            continue
        key, separator, value = line.partition(" = ")
        if not separator:
            continue
        key = key.strip()
        if key == "Path":
            path = value.strip()
        elif key == "Size":
            size = value.strip()
        elif key == "Attributes":
            folder = value.strip().upper().startswith("D")
    flush()
    return tuple(entries)


def _parse_unar(output: str) -> Optional[Tuple[RarEntry, ...]]:
    """
    Разбор `lsar -j`: оглавление в JSON.

    JSON, а не колонки `lsar -l`: у той таблицы ширина колонок пляшет от
    длины имён, а флаги и режим сжатия ещё и от формата архива. Здесь же
    ничего не зависит ни от локали, ни от вёрстки.

    Номер записи сохраняется: выбрать одну запись The Unarchiver умеет по
    номеру (`unar -i`), а не по имени — в отличие от прочих семейств.
    """
    try:
        data = json.loads(output)
        listing = data["lsarContents"]
    except (ValueError, KeyError, TypeError):
        # Не наш ответ: программа промолчала или выдала не то. Это «не
        # справилась», а не пустой архив, и None здесь именно об этом.
        return None

    entries = []
    for item in listing:
        if not isinstance(item, dict) or item.get("XADIsDirectory"):
            continue
        name = item.get("XADFileName")
        size = item.get("XADFileSize")
        index = item.get("XADIndex")
        if not isinstance(name, str) or not isinstance(size, int):
            continue
        entries.append(RarEntry(
            name=name.replace("\\", "/"),
            size=size,
            link=bool(item.get("XADIsLink")),
            index=index if isinstance(index, int) else -1,
        ))

    # Пустое оглавление считаем отказом, а не пустым архивом, — и только у
    # этого семейства. На обрезанном RAR5 lsar выходит с нулём и печатает
    # пустой список: отличить «пусто» от «не прочитал» он не даёт, а
    # lsarConfidence равен нулю и на битом файле, и на исправном.
    #
    # Промолчать тут значило бы объявить повреждённый архив пустым, то есть
    # соврать ровно в том случае, ради которого проверка и заведена: битая
    # загрузка. Прочие семейства обрезанный архив честно отвергают кодом
    # возврата, и для них пустой кортеж по-прежнему значит пустой архив.
    return tuple(entries) or None


# --- распаковка --------------------------------------------------------------


def extract(archive: str, destination: str, extra: Optional[str] = None) -> Tool:
    """
    Распаковывает архив первой программой, проверенной на нём же.

    Проверка — не формальность: программа, которая печатает оглавление, но
    спотыкается на распаковке, рабочей не считается. Проверяется извлечением
    самой маленькой записи во временный каталог, поэтому цена проверки — доли
    секунды даже для архива на 141 МБ.
    """
    failures = []
    for tool in discover(extra):
        entries = list_entries(tool, archive)
        if entries is None:
            continue
        entries = _checked(entries)
        if entries and not verify(tool, archive, entries):
            failures.append(tool.name)
            continue
        if _extract_with(tool, archive, destination) and _landed(destination, entries):
            return tool
        failures.append(tool.name)

    raise UnpackError(
        UnpackErrorCode.CONTAINER_UNSUPPORTED,
        {
            "entry": os.path.basename(archive),
            "kind": "rar",
            "hint": install_hint(),
            "tried": ", ".join(failures),
        },
    )


def _landed(destination: str, entries: Sequence[RarEntry]) -> bool:
    """
    Все ли записи легли внутрь назначения обычными файлами.

    Раскладывает файлы чужая программа, и полагаться на её собственные
    проверки нельзя: у bsdtar и 7-Zip они разные. Ссылки в счёт не идут — их
    мы и не просим распаковывать.
    """
    return all(_produced(destination, entry) for entry in entries if not entry.link)


def verify(tool: Tool, archive: str, entries: Sequence[RarEntry]) -> bool:
    """
    Умеет ли программа не только перечислять, но и извлекать из ЭТОГО архива.

    Берётся самая маленькая НЕПУСТАЯ запись, и не символьная ссылка: набор
    форматов libarchive задаётся при сборке, и оглавление RAR программа может
    прочитать, а данные — нет. Проверяется размер на диске, а не код возврата:
    подставная программа, которая молча ничего не создала, тоже не должна
    считаться рабочей.

    Почему не просто самая маленькая: ссылка на диске не файл заявленного
    размера, и на ней спотыкалась бы исправная программа; а запись нулевой
    длины делает проверку бессмысленной — пустой файл создаст кто угодно.
    """
    probes = [entry for entry in entries if entry.size > 0 and not entry.link]
    if not probes:
        # Проверять нечем: в архиве одни ссылки и пустые файлы. Отказывать
        # программе за это нельзя — проверка вхолостую, а не провал.
        return True
    smallest = min(probes, key=lambda entry: entry.size)
    probe = tempfile.mkdtemp(prefix="efd-rar-")
    try:
        return _extract_with(tool, archive, probe, only=smallest) and _produced(probe, smallest)
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def _extract_with(
    tool: Tool, archive: str, destination: str, only: Optional[RarEntry] = None
) -> bool:
    """
    Распаковывает архив целиком либо одну запись.

    Запись, а не её имя: The Unarchiver выбирает одну по НОМЕРУ, остальные —
    по имени, и передавать сюда только имя значило бы потерять номер по
    дороге.
    """
    if tool.family == LIBARCHIVE:
        arguments = ["-xf", archive, "-C", destination]
        if only is not None:
            arguments.append(only.name)
    elif tool.family == UNAR:
        # -D обязателен: по умолчанию unar кладёт содержимое в каталог,
        # названный по архиву, и распакованное оказалось бы этажом ниже, чем
        # его ждут. Видно это только на живой программе.
        arguments = ["-o", destination, "-f", "-q", "-D"]
        if only is not None:
            arguments += ["-i", archive, str(only.index)]
        else:
            arguments.append(archive)
    else:
        arguments = ["x", archive, "-o" + destination, "-y", "-bso0", "-bsp0"]
        if only is not None:
            arguments.append(only.name)
    completed = _run(tool.extract_command(arguments), EXTRACT_TIMEOUT)
    return completed is not None and completed.returncode == 0


def _run(command: Sequence[str], timeout: float):
    """
    Запуск с предельным временем. Любой отказ — это «программа не подошла».

    Молча пройти мимо нельзя только в одном случае: когда не подошла ни одна,
    и тогда отказ соберёт read_entries или extract.
    """
    try:
        return subprocess.run(
            list(command), capture_output=True,
            timeout=timeout, env=_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _decode(raw: bytes) -> str:
    """
    Вывод программы в текст.

    Байтами, а не text=True: subprocess декодировал бы кодировкой локали, а на
    Windows это cp1251 или cp866 — кириллица в именах записей превратилась бы
    в мусор. Сначала UTF-8 (7-Zip мы сами просим о нём через -sccUTF-8), затем
    локаль, и только потом замена непрошедших байтов: потерять одно имя лучше,
    чем потерять всё оглавление.
    """
    for encoding in ("utf-8", locale.getpreferredencoding(False)):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


# --- подсказка об установке --------------------------------------------------

#: Команду показываем, но не выполняем: winget и brew просят повышения прав и
#: задают свои вопросы, а человек вправе знать, что ставится в его систему,
#: до того как это произойдёт.
#: Вариантов может быть несколько — это РАВНОПРАВНЫЕ альтернативы, а не
#: последовательность: на Linux один пакет ставится apt, другой dnf, и нужен
#: ровно один из них, смотря какой менеджер пакетов в системе.
_HINTS = {
    "darwin": ("brew install sevenzip", "brew install unar"),
    "win32": ("winget install 7zip.7zip",),
    "linux": (
        "sudo apt install libarchive-tools", "sudo dnf install p7zip",
        "sudo apt install unar",
    ),
}

#: Чем варианты разделяются в одной строке. Не вертикальная черта: строку
#: показывают рядом с кнопкой «копировать», а «a | b», вставленное в оболочку,
#: становится конвейером — вторая команда запустится даже после успеха первой,
#: и её отказ человек примет за отказ установки.
HINT_SEPARATOR = "  либо  "


def install_hints() -> Tuple[str, ...]:
    """Команды установки по отдельности: каждая — самостоятельный вариант."""
    return _HINTS.get(sys.platform, _HINTS["linux"])


def install_hint() -> str:
    """
    Что набрать, чтобы появилась программа для .rar, — одной строкой.

    Для сообщения об отказе, где строка одна и кнопок нет. Окно показывает
    варианты по отдельности, каждый со своей кнопкой «копировать».
    """
    return HINT_SEPARATOR.join(install_hints())


def extract_entry(tool: Tool, archive: str, destination: str, entry: RarEntry) -> bool:
    """
    Извлекает одну запись той программой, которая её и перечислила.

    Именно ей, без перебора: размер записи объявила она, и проверять результат
    надо против её же числа. Перебор означал бы, что лист, созданный по
    оглавлению одной программы, наполняется другой — с другим размером.
    Резерв здесь не нужен: если перечислившая программа не справилась с
    распаковкой, лист честно отказывает, а перебор с проверкой всего архива
    делает extract.

    Результат проверяется, а не принимается по коду возврата: программа,
    которая вышла с нулём и ничего не создала, иначе считалась бы успешной,
    а поток падал бы голым FileNotFoundError.
    """
    return _extract_with(tool, archive, destination, entry) and _produced(destination, entry)
