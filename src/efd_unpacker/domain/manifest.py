"""
Чтение 1cv8.mft — манифеста шаблона конфигурации.

Ради одной строки: `Catalog`. Это то, что человек увидит в самой 1С при
создании базы, и самое понятное описание из всех, что у нас есть, — понятнее
и имени каталога, и версии.

Читается ПОСЛЕ распаковки, а не до. До неё манифест стоил бы гигабайтов
разжатия: у исследованных поставок он лежит не в начале потока, и добраться
до него значило бы развернуть от 0.44 до 2.93 ГБ (замеры в #49). После
распаковки он лежит на диске и читается бесплатно.

Всё здесь — украшение, а не условие успеха. Манифеста нет, он битый, его не
прочитать — строка просто остаётся прежней, распаковка уже состоялась.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: Имя файла по стандарту поставки #std731.
NAME = "1cv8.mft"

#: Сколько байт читаем. Настоящие манифесты — от 171 до 482 байт; предел
#: щедрый ровно настолько, чтобы случайный однофамилец на сотню мегабайт не
#: уехал в память целиком.
SIZE_LIMIT = 64 * 1024

#: Кодировки по порядку. Сначала UTF-8 со снятием BOM — такими оказались все
#: четыре манифеста, что удалось посмотреть живьём, — затем cp1251. Порядок
#: важен: cp1251 принимает почти любой байт и ошибки не даст никогда, поэтому
#: строгий UTF-8 обязан идти первым, иначе кириллица превратилась бы в мусор
#: молча.
ENCODINGS = ("utf-8-sig", "cp1251")

#: Разделитель в значении Catalog. В 1С это дерево: группа и элемент в ней.
CATALOG_SEPARATOR = "/"


@dataclass(frozen=True)
class Config:
    """
    Одна конфигурация из манифеста — одна строка в дереве 1С.

    Их бывает несколько: у «Комплексной автоматизации» две — сама
    конфигурация из .cf и демонстрационная база из .dt, и в 1С они встают
    двумя разными пунктами.
    """

    catalog: str
    source: str = ""
    destination: str = ""

    @property
    def title(self) -> str:
        """Значение Catalog в том виде, в каком его показывают человеку."""
        parts = [part.strip() for part in self.catalog.split(CATALOG_SEPARATOR)]
        return " → ".join(part for part in parts if part)


@dataclass(frozen=True)
class Manifest:
    """Содержимое 1cv8.mft. Пустой — это «ничего не узнали», а не отказ."""

    vendor: str = ""
    name: str = ""
    version: str = ""
    configs: Tuple[Config, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(self.configs)

    def delivered(self, directory: str) -> Tuple[Config, ...]:
        """
        Конфигурации, файл которых ДЕЙСТВИТЕЛЬНО лежит в каталоге.

        Проверка по диску, а не по плану: с `--only cf` демонстрационная база
        (Source=1cv8.dt) не пишется вовсе, и обещать её в 1С значило бы
        соврать — притом ровно там, где человек пойдёт её искать.

        Source пустой оставляем: раз манифест не сказал, из чего конфигурация
        берётся, проверять нечего, и умалчивать о ней хуже, чем показать.
        """
        return tuple(
            config for config in self.configs
            if not config.source or os.path.isfile(os.path.join(directory, config.source))
        )


def decode(raw: bytes) -> str:
    """Байты манифеста в текст. Порядок кодировок — см. ENCODINGS."""
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    # Последняя попытка с заменой: одна испорченная буква в названии лучше,
    # чем пустая строка вместо всего описания.
    return raw.decode("utf-8", "replace")


def parse(text: str) -> Manifest:
    """
    Разбирает ini-подобный текст манифеста.

    Своими руками, а не configparser: у манифеста ключи идут ДО первой секции
    (Vendor, Name, Version, AppVersion), а configparser на такой файл отвечает
    MissingSectionHeaderError и не отдаёт ничего. Ещё он по умолчанию
    подставляет значения по `%`, а в названиях конфигураций знак процента
    встретиться может.

    Секцией конфигурации считается любая, где есть Catalog, а не только
    [ConfigN]: имя секции нам ни для чего не нужно, а ключ — нужен.
    """
    head: Dict[str, str] = {}
    current: Optional[Dict[str, str]] = None
    sections: List[Dict[str, str]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = {}
            sections.append(current)
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        target = head if current is None else current
        target[key.strip().lower()] = value.strip()

    configs = tuple(
        Config(
            catalog=section["catalog"],
            source=section.get("source", ""),
            destination=section.get("destination", ""),
        )
        for section in sections
        if section.get("catalog")
    )
    return Manifest(
        vendor=head.get("vendor", ""),
        name=head.get("name", ""),
        version=head.get("version", ""),
        configs=configs,
    )


def read(directory: str) -> Manifest:
    """
    Манифест из каталога шаблона. Пустой, если прочитать не удалось.

    Исключений не поднимает ни на чём: распаковка к этому моменту уже
    состоялась, и уронить её из-за украшения — худшее, что может сделать
    чтение манифеста. Перехват намеренно широкий: под ним чтение чужого
    файла с диска, и набор его отказов открытый — от отсутствия прав до
    оборванной сетевой шары.
    """
    path = os.path.join(directory, NAME)
    try:
        if os.path.getsize(path) > SIZE_LIMIT:
            return Manifest()
        with open(path, "rb") as handle:
            raw = handle.read(SIZE_LIMIT)
    except Exception:  # noqa: BLE001 - украшение не имеет права ронять распаковку
        return Manifest()
    return parse(decode(raw))
