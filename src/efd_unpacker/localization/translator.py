"""
Загрузчик Qt-переводов из .ts файлов.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Dict, Tuple

from ..runtime import resource_path


class Translator:
    """Простая реализация каталога переводов."""

    # Значения атрибута type, при которых <translation> — черновик, а не перевод.
    # obsolete приходит из файлов Qt < 5.10, vanished — из более новых;
    # lrelease такие записи в .qm не кладёт, а здесь .ts читается напрямую.
    DRAFT_TYPES = frozenset({"unfinished", "obsolete", "vanished"})

    def __init__(self, lang: str = "en", translations_dir: str | None = None) -> None:
        self.lang = lang
        self.translations_dir = translations_dir or resource_path("translations")
        self._translations: Dict[Tuple[str, str], str] = {}
        self.load()

    def load(self) -> None:
        ts_path = os.path.join(self.translations_dir, f"{self.lang}.ts")
        self._translations.clear()
        if not os.path.isfile(ts_path):
            return
        try:
            root = ET.parse(ts_path).getroot()
        except Exception:
            # Каталог грузится до создания QApplication, показать ошибку негде,
            # а исключение здесь означает, что окно не появится вообще — молча
            # на сборках Windows и macOS, обе без консоли. Английский интерфейс
            # это рабочий откат, мёртвый процесс — нет.
            #
            # Перехват намеренно широкий. Под try стоит один сторонний вызов,
            # а набор его исключений открытый: обрезанный файл и битая сущность
            # дают ParseError, объявленная кодировка encoding="NOPE" —
            # LookupError, отказ чтения — OSError. Перечислять типы здесь
            # значит однажды пропустить ещё один и вернуть молчаливое падение
            # на старте. Гарантия «битый каталог не мешает запуску» проверяется
            # тестом по набору испорченных файлов, а не этим списком.
            return
        for ctx in root.findall("context"):
            name_elem = ctx.find("name")
            context_name = name_elem.text if name_elem is not None else ""
            for msg in ctx.findall("message"):
                source_elem = msg.find("source")
                translation_elem = msg.find("translation")
                if translation_elem is not None and translation_elem.get("type") in self.DRAFT_TYPES:
                    continue  # черновик показывать пользователю нельзя, откатываемся на source
                source = source_elem.text if source_elem is not None else ""
                translation = translation_elem.text if translation_elem is not None else ""
                self._translations[(context_name, source)] = translation

    def translate(self, context: str, source: str) -> str:
        translation = self._translations.get((context, source))
        return translation if translation else source


def create_translator(lang: str) -> Translator:
    """Фабрика для удобства."""
    return Translator(lang=lang)
