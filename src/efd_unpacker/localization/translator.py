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
        tree = ET.parse(ts_path)
        root = tree.getroot()
        for ctx in root.findall("context"):
            name_elem = ctx.find("name")
            context_name = name_elem.text if name_elem is not None else ""
            for msg in ctx.findall("message"):
                source_elem = msg.find("source")
                translation_elem = msg.find("translation")
                source = source_elem.text if source_elem is not None else ""
                translation = translation_elem.text if translation_elem is not None else ""
                self._translations[(context_name, source)] = translation

    def translate(self, context: str, source: str) -> str:
        return self._translations.get((context, source), source)


def create_translator(lang: str) -> Translator:
    """Фабрика для удобства."""
    return Translator(lang=lang)
