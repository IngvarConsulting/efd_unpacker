"""
Загрузчик Qt-переводов из .ts файлов.

Умеет множественные формы. В русском их три — «1 файл», «2 файла»,
«5 файлов», — и обойти это подписью с двоеточием («файлов: 1») можно ровно до
тех пор, пока счётчик один. В 2.0 они и в окне, и в отчёте, и в CLI.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Callable, Dict, Tuple

from ..runtime import resource_path


def _russian_form(n: int) -> int:
    """
    Какую из трёх русских форм брать: «файл», «файла», «файлов».

    Правило то же, что у Qt, и проверяется оно на 1, 2, 5, 11, 21 и 112:
    одиннадцать и сто двенадцать — те самые числа, на которых наивное
    «последняя цифра» ошибается.
    """
    if n % 10 == 1 and n % 100 != 11:
        return 0
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return 1
    return 2


def _two_forms(n: int) -> int:
    """Языки с единственным и множественным: английский и прочие."""
    return 0 if n == 1 else 1


#: Правило выбора формы по языку. Ключ — код языка без региона.
PLURAL_RULES: Dict[str, Callable[[int], int]] = {"ru": _russian_form}

#: Сколько форм ждёт правило. Сторожевой тест сверяет с этим числом, чтобы
#: запись с одной формой вместо трёх не доехала до пользователя.
PLURAL_FORMS: Dict[str, int] = {"ru": 3}

DEFAULT_FORMS = 2

#: Что Qt подставляет числом внутри формы.
COUNT_PLACEHOLDER = "%n"


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
        self._numerus: Dict[Tuple[str, str], Tuple[str, ...]] = {}
        self.load()

    def base_language(self) -> str:
        """Код языка без региона: «ru_RU» — это тот же «ru»."""
        return self.lang.split("_")[0]

    def catalog_path(self) -> str:
        """
        Файл каталога: сперва по полному коду, затем по языку без региона.

        Без отката «ru_RU» брал бы русские формы, но английские слова: правило
        множественного числа регион отсекает, а имя файла — нет. Половинчатое
        поведение хуже любого из двух целых.
        """
        for name in (self.lang, self.base_language()):
            path = os.path.join(self.translations_dir, "%s.ts" % name)
            if os.path.isfile(path):
                return path
        return os.path.join(self.translations_dir, "%s.ts" % self.lang)

    def load(self) -> None:
        ts_path = self.catalog_path()
        self._translations.clear()
        self._numerus.clear()
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
                if translation_elem is not None and msg.get("numerus") == "yes":
                    forms = tuple(
                        form.text or "" for form in translation_elem.findall("numerusform")
                    )
                    if forms:
                        self._numerus[(context_name, source)] = forms
                        continue
                translation = translation_elem.text if translation_elem is not None else ""
                self._translations[(context_name, source)] = translation

    def translate(self, context: str, source: str) -> str:
        translation = self._translations.get((context, source))
        return translation if translation else source

    def translate_n(self, context: str, source: str, n: int) -> str:
        """
        Перевод с числом: «1 файл», «2 файла», «5 файлов».

        Без перевода отдаёт исходную строку — она английская и годится как
        откат, пусть и не склоняется. Пустая форма считается отсутствующей:
        каталог с пропуском обязан вести себя как каталог без записи, а не
        показывать пустое место вместо слова.
        """
        forms = self._numerus.get((context, source))
        chosen = source
        if forms:
            index = self.plural_form(n)
            if index < len(forms) and forms[index]:
                chosen = forms[index]
        return chosen.replace(COUNT_PLACEHOLDER, str(n))

    def plural_form(self, n: int) -> int:
        """Номер формы для этого языка и числа."""
        return PLURAL_RULES.get(self.base_language(), _two_forms)(n)

    def forms_expected(self) -> int:
        """Сколько форм должно быть у записи numerus в этом каталоге."""
        return PLURAL_FORMS.get(self.base_language(), DEFAULT_FORMS)


def create_translator(lang: str) -> Translator:
    """Фабрика для удобства."""
    return Translator(lang=lang)
