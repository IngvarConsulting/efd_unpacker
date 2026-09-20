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
MENU_WASH = "#F1F7F5"    # шестерёнка с открытым меню
CODE_FILL = "#F2F5F6"    # подложка команды установки

# Полоса Ingvar Consulting на экране «О программе». Цвета не из общей палитры:
# это чужой фирменный блок, и логотип нарисован белым по тёмно-синему.
BRAND_BACK = "#1B2A44"
BRAND_TEXT = "#D7DEE8"
BRAND_LINK = "#7FB0FF"

# --- размеры -----------------------------------------------------------------

WINDOW_WIDTH = 760
WINDOW_HEIGHT = 540
HEADER_HEIGHT = 46
SIDE_PADDING = 20
MARK_SIZE = 16
PROGRESS_HEIGHT = 4

#: Размеры нижнего яруса строки: путь моноширинным, фраза про 1С — обычным.
#: Пикселями и целыми: QFont.setPixelSize дробных не принимает, а мерить
#: приходится тем же шрифтом, каким рисуем.
DETAIL_SIZE = 11
APPEARS_SIZE = 12

#: На сколько долей делится полоса хода.
#:
#: Байтами её границы задавать НЕЛЬЗЯ: QProgressBar хранит их 32-битным целым,
#: и всё, что от двух гигабайт, отвергается с OverflowError. Пачка на 11 ГБ —
#: ровно то, ради чего окно и делалось, — падала на нажатии «Распаковать», не
#: записав ни байта. Тысячи долей хватает: полоса шириной в 760 точек тоньше
#: одной доли всё равно не нарисует.
PROGRESS_STEPS = 1000


def progress_value(done: int, total: int) -> int:
    """Доля сделанного в шагах полосы. Ноль при неизвестном объёме."""
    if total <= 0:
        return 0
    return min(PROGRESS_STEPS, max(0, done * PROGRESS_STEPS // total))


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


def families(mono: bool = False) -> tuple:
    """
    Гарнитуры по предпочтению — для QFont, а не для таблицы стилей.

    Нужны там, где текст не только рисуется, но и МЕРЯЕТСЯ: размер из
    таблицы стилей в QWidget.font() не попадает, и QFontMetrics по нему
    считает шириной гарнитуры по умолчанию. Строка «В 1С появится…»
    укорачивалась по таким меркам до трети настоящей длины.
    """
    preferred, fallback = ("IBM Plex Mono", MONO) if mono else ("IBM Plex Sans", SANS)
    available = _stack(preferred, fallback).startswith("'%s'" % preferred)
    return (preferred, fallback) if available else (fallback,)


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
        QLabel[role="section"] {
            font-size: 11px; font-weight: 600; color: %(muted)s;
        }
        QLabel[role="note"] { font-size: 12px; color: %(muted)s; }
        QLabel[role="screen-title"] { font-size: 14px; font-weight: 600; }
    """ % {
        "surface": SURFACE, "ink": INK, "muted": MUTED, "accent": ACCENT,
        "sans": sans_stack(), "mono": mono_stack(),
    }


#: Разрядка заголовков разделов, в процентах. Задаётся шрифтом, а не листом
#: стилей: letter-spacing в таблицах стилей Qt не поддержан — правило молча
#: отбрасывается, а в макете это единственное отличие такого заголовка от
#: обычной подписи.
SECTION_SPACING = 106


def code_sheet() -> str:
    """Команда установки: моноширинная, в рамке, чтобы её было видно как код."""
    return """
        QLabel {
            font-family: %(mono)s; font-size: 11.5px; color: %(ink)s;
            background: %(fill)s; border: 1px solid %(soft)s; border-radius: 5px;
            padding: 4px 8px;
        }
    """ % {"mono": mono_stack(), "ink": INK, "fill": CODE_FILL, "soft": LINE_SOFT}


def small_button_sheet() -> str:
    """Кнопка рядом со строкой: та же форма, что у обычной, но в один ярус."""
    return """
        QPushButton {
            padding: 4px 10px; border: 1px solid %(line)s; border-radius: 5px;
            background: %(surface)s; color: %(ink)s; font-size: 11.5px;
        }
        QPushButton:hover { border-color: %(muted)s; }
    """ % {"line": LINE, "surface": SURFACE, "ink": INK, "muted": MUTED}


def menu_sheet() -> str:
    """Меню шестерёнки: карточка со скруглением и отступами, как в макете."""
    return """
        QMenu {
            background: %(surface)s; border: 1px solid %(line)s;
            border-radius: 9px; padding: 5px;
        }
        QMenu::item {
            padding: 9px 10px; border-radius: 6px; color: %(ink)s; font-size: 13px;
        }
        QMenu::item:selected { background: %(wash)s; }
        QMenu::separator { height: 1px; background: %(faint)s; margin: 5px 8px; }
    """ % {"surface": SURFACE, "line": LINE, "ink": INK,
           "wash": MENU_WASH, "faint": LINE_FAINT}


def gear_sheet(open_: bool = False) -> str:
    """Шестерёнка. С открытым меню — в акценте, как в макете."""
    return """
        QPushButton {
            padding: 4px 7px; border: 1px solid %(border)s; border-radius: 6px;
            background: %(fill)s; color: %(color)s; font-size: 13px;
        }
        QPushButton:hover { border-color: %(muted)s; }
    """ % {"border": ACCENT if open_ else LINE,
           "fill": MENU_WASH if open_ else SURFACE,
           "color": ACCENT if open_ else INK,
           "muted": ACCENT_DARK if open_ else MUTED}


def radio_sheet() -> str:
    """
    Переключатель варианта пути: кольцо акцентом, подпись моноширинная.

    Кружок рисуется правилами рамки, а не картинкой и не родным стилем: в
    макете это кольцо толщиной в три пикселя с белой серединой, и у родных
    переключателей трёх систем оно выглядит по-разному. Размер задаётся
    содержимым, рамка прибавляется сверху — отсюда 8+3+3 и 12+1+1 на одни и
    те же 14 пикселей снаружи.
    """
    return """
        QRadioButton { font-family: %(mono)s; font-size: 12px; color: %(ink)s; spacing: 10px; }
        QRadioButton::indicator {
            width: 12px; height: 12px; border-radius: 7px;
            border: 1px solid %(line)s; background: %(surface)s;
        }
        QRadioButton::indicator:checked {
            width: 8px; height: 8px; border: 3px solid %(accent)s;
        }
        QRadioButton:disabled { color: %(disabled)s; }
        QRadioButton[role="action"] {
            font-family: %(sans)s; font-size: 12.5px; font-weight: 500; color: %(accent)s;
        }
    """ % {"mono": mono_stack(), "sans": sans_stack(), "ink": INK, "accent": ACCENT,
           "line": LINE, "surface": SURFACE, "disabled": DISABLED}


def brand_sheet() -> str:
    """Полоса Ingvar Consulting: тёмная карточка со скруглением."""
    return """
        QFrame#brand { background: %(back)s; border-radius: 10px; }
        QFrame#brand QLabel { background: transparent; color: %(text)s; font-size: 12.5px; }
    """ % {"back": BRAND_BACK, "text": BRAND_TEXT}


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


def band_sheet(name: str, top: str = "", bottom: str = "") -> str:
    """
    Полоса с разделительной чертой сверху или снизу.

    Правило именное, а не на весь QFrame: QLabel — наследник QFrame, и
    безымянное правило рисовало рамку вокруг каждой подписи внутри полосы.
    Лечить это «border: 0» у каждой подписи значит чинить не там: следующая
    добавленная подпись снова окажется в рамке, и заметить это можно только
    глазами.
    """
    lines = ["border: 0;"]
    if top:
        lines.append("border-top: 1px solid %s;" % top)
    if bottom:
        lines.append("border-bottom: 1px solid %s;" % bottom)
    return "QFrame#%s { %s }" % (name, " ".join(lines))


def drop_zone_sheet(active: bool = False) -> str:
    """Зона приёма файлов: пунктир, как в макете пустого окна."""
    return """
        QFrame#zone {
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
