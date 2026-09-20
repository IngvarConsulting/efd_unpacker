"""
Палитра, гарнитуры и размеры из макетов.

Значения перенесены из макетов буквально, а не подобраны на глаз: окно должно
совпадать с тем, что согласовали, а не быть похожим.

Про гарнитуру. В макетах IBM Plex Sans и IBM Plex Mono, но в систему они не
входят ни на одной из трёх платформ. Подкладывать их в поставку — отдельное
решение (лицензия OFL это позволяет, но растёт размер сборки), поэтому здесь
запасной ряд той же природы: гротеск без засечек и моноширинный. Пропорции,
цвета и иерархия от этого не меняются, меняется рисунок букв.
"""

from __future__ import annotations

import sys

# --- палитра -----------------------------------------------------------------

INK = "#0F1417"          # основной текст
MUTED = "#5E6A72"        # пояснения, единицы, пути
LINE = "#C7CED3"         # границы блоков
LINE_SOFT = "#E3E8EA"    # неактивные рамки
LINE_FAINT = "#EEF1F2"   # разделители строк списка
ACCENT = "#1F6F5C"       # отмеченное, готовое, главная кнопка
ACCENT_DARK = "#155244"  # наведение
ACCENT_WASH = "#F7FAF9"  # подсветка текущей строки
ACCENT_TRACK = "#DCE5E2" # дорожка полоски внутри строки
SURFACE = "#FFFFFF"
SURFACE_MUTED = "#F5F7F8"
DISABLED = "#A8B2B8"
ALERT = "#8C3A32"        # отказ

# --- размеры -----------------------------------------------------------------

WINDOW_WIDTH = 760
WINDOW_HEIGHT = 540
HEADER_HEIGHT = 46
SIDE_PADDING = 20
MARK_SIZE = 16
PROGRESS_HEIGHT = 4


def _families() -> tuple:
    """Гарнитуры под систему: гротеск для текста, моноширинный для чисел."""
    if sys.platform == "darwin":
        return ("Helvetica Neue", "Menlo")
    if sys.platform.startswith("win"):
        return ("Segoe UI", "Consolas")
    return ("DejaVu Sans", "DejaVu Sans Mono")


SANS, MONO = _families()

_stacks: dict = {}


def _stack(preferred: str, fallback: str) -> str:
    """
    Ряд гарнитур с проверкой наличия.

    Перечислять отсутствующую гарнитуру нельзя просто так: Qt на каждый такой
    ряд строит таблицу синонимов и пишет предупреждение в поток ошибок —
    замерено 58 мс на запуск. Проверяем один раз и больше о ней не упоминаем.

    Обобщённых имён вроде sans-serif здесь нет намеренно: в таблицах стилей Qt
    понимает их как имена семейств, и они дают ровно то же предупреждение, что
    и любая отсутствующая гарнитура.
    """
    if preferred not in _stacks:
        try:
            from PyQt5.QtGui import QFontDatabase

            available = preferred in QFontDatabase().families()
        except Exception:  # pragma: no cover - до создания QApplication
            available = False
        _stacks[preferred] = (
            "'%s', '%s'" % (preferred, fallback) if available else "'%s'" % fallback
        )
    return _stacks[preferred]


def sans_stack() -> str:
    return _stack("IBM Plex Sans", SANS)


def mono_stack() -> str:
    return _stack("IBM Plex Mono", MONO)


def window_sheet() -> str:
    """Общий лист окна: фон, гарнитура, цвет текста."""
    return """
        QWidget { background: %(surface)s; color: %(ink)s; font-family: %(sans)s; font-size: 13px; }
        QLabel[role="title"] { font-size: 14px; font-weight: 600; }
        QLabel[role="mono"] { font-family: %(mono)s; font-size: 12px; color: %(muted)s; }
        QLabel[role="mono-accent"] { font-family: %(mono)s; font-size: 12px; color: %(accent)s; }
        QLabel[role="muted"] { font-size: 12px; color: %(muted)s; }
        QLabel[role="path"] { font-family: %(mono)s; font-size: 12px; color: %(ink)s; }
    """ % {
        "surface": SURFACE, "ink": INK, "muted": MUTED, "accent": ACCENT,
        "sans": sans_stack(), "mono": mono_stack(),
    }


def primary_button_sheet() -> str:
    """Главная кнопка: залитая акцентом, с объёмом прямо в подписи."""
    return """
        QPushButton {
            padding: 10px 18px; border: 0; border-radius: 7px;
            background: %(accent)s; color: %(surface)s;
            font-size: 13px; font-weight: 600;
        }
        QPushButton:hover { background: %(dark)s; }
        QPushButton:disabled { background: %(line)s; color: %(surface)s; }
    """ % {"accent": ACCENT, "dark": ACCENT_DARK, "surface": SURFACE, "line": LINE}


def secondary_button_sheet() -> str:
    return """
        QPushButton {
            padding: 9px 18px; border: 1px solid %(line)s; border-radius: 7px;
            background: %(surface)s; color: %(ink)s; font-size: 13px; font-weight: 500;
        }
        QPushButton:hover { border-color: %(muted)s; }
        QPushButton:disabled { color: %(disabled)s; border-color: %(soft)s; }
    """ % {"line": LINE, "surface": SURFACE, "ink": INK, "muted": MUTED,
           "disabled": DISABLED, "soft": LINE_SOFT}


def link_sheet() -> str:
    """Ссылка-кнопка: без рамки, акцентом, как в макетах."""
    return """
        QPushButton {
            border: 0; background: transparent; color: %(accent)s;
            font-size: 12px; font-weight: 500; padding: 0;
        }
        QPushButton:hover { color: %(dark)s; }
        QPushButton:disabled { color: %(disabled)s; }
    """ % {"accent": ACCENT, "dark": ACCENT_DARK, "disabled": DISABLED}


def drop_zone_sheet(active: bool = False) -> str:
    """Зона приёма файлов: пунктир, как в макете пустого окна."""
    return """
        QFrame {
            border: 1.5px dashed %(border)s; border-radius: 12px; background: %(fill)s;
        }
    """ % {"border": ACCENT if active else LINE,
           "fill": ACCENT_WASH if active else SURFACE}


#: Единицы объёма по-русски. В CLI остаётся короткая латинская форма — она
#: часть машинного вывода и показана в примерах документации.
SIZE_UNITS = ("Б", "КБ", "МБ", "ГБ", "ТБ")


def human_size(size: int) -> str:
    """
    Объём для окна: «2.3 ГБ», «26 МБ», «135 МБ».

    Дробная часть только там, где различает значения: «2.3 ГБ» против «2 ГБ»
    полезно, «135.0 МБ» — шум.
    """
    value = float(size)
    for unit in SIZE_UNITS:
        if value < 1024 or unit == SIZE_UNITS[-1]:
            if unit == SIZE_UNITS[0] or value >= 10:
                return "%d %s" % (round(value), unit)
            return "%.1f %s" % (value, unit)
        value /= 1024
    return "%d %s" % (round(value), SIZE_UNITS[-1])  # pragma: no cover
