"""
Строка списка: два яруса и знак состояния слева.

В макетах строка — не ячейка таблицы, а блок из двух ярусов: сверху
наименование и версия, снизу путь и объём. Знак слева несёт сразу два
смысла — отмечена ли строка и можно ли её вообще распаковать.

Знак рисуется, а не набирается символом шрифта: залитый квадрат с галочкой,
пустой квадрат, серый квадрат с прочерком и круг отказа должны выглядеть
одинаково на трёх системах, а начертание «◼» у гарнитур разное.
"""

from __future__ import annotations

import html
from typing import Optional, Sequence, Tuple

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import style

# Состояния знака. Пропуск и отказ намеренно разные: «уже установлено» —
# нормальный исход, а не проблема, и красным его красить нельзя.
PENDING = "pending"        # поедет, отмечено
UNCHECKED = "unchecked"    # снято пользователем
UNAVAILABLE = "unavailable"  # пропуск по делу: уже установлено, нет программы
RUNNING = "running"
DONE = "done"
FAILED = "failed"        # распаковка отказала: можно повторить
BROKEN = "broken"        # отказ ОСМОТРА: повторять нечего

#: Состояния, в которых знак можно переключить.
#:
#: Отказ распаковки здесь намеренно. Ничего не записано, а причина —
#: кончилось место, права на файлах от прошлой распаковки, вынутая флешка —
#: чинится снаружи программы, и после починки естественное действие
#: «повторить». Пока он не переключался, повторить было нечем: кнопка
#: «Распаковать» гасла, и единственным выходом оставалось бросить тот же файл
#: ещё раз.
#:
#: А вот отказ ОСМОТРА — состояние отдельное и непереключаемое. Его план
#: знает заранее, и исполнение такой элемент не трогает вовсе: оно повторит
#: ту же самую записанную ошибку, не открывая источник. Кнопка повтора у него
#: обещала бы то, чего не будет. Выглядят оба отказа одинаково — человеку это
#: одна и та же беда, — но повторить можно только тот, где было что делать.
#:
#: Готовая строка не переключается: работа сделана, и молча переделать её
#: было бы неожиданно — у неё для этого есть «Открыть папку». «Уже
#: установлено» и «нет программы» — тоже нет: желание тут ничего не меняет.
TOGGLEABLE = (PENDING, UNCHECKED, FAILED)


class Mark(QAbstractButton):
    """
    Знак состояния 16×16.

    Кнопка, а не голый виджет: от QAbstractButton достаются фокус, пробел и
    Enter, и имя для средств доступности. Мышью-то щёлкнуть можно и по
    виджету, а вот с клавиатуры строку было не отметить вовсе.

    Непереключаемые состояния гасятся: выключенная кнопка не берёт фокус и
    не срабатывает, так что готовую строку и «уже установлено» не тронуть ни
    мышью, ни клавишей. Что считается переключаемым — см. TOGGLEABLE.
    """

    def __init__(self, state: str = PENDING) -> None:
        super().__init__()
        self._state = state
        self.setFixedSize(style.MARK_SIZE, style.MARK_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setEnabled(state in TOGGLEABLE)

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.setEnabled(state in TOGGLEABLE)
            self.update()

    def state(self) -> str:
        return self._state

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(0.75, 0.75, style.MARK_SIZE - 1.5, style.MARK_SIZE - 1.5)

        if self._state == PENDING:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(style.ACCENT))
            painter.drawRoundedRect(box, 3, 3)
            self._draw_check(painter, QColor(style.SURFACE), 3.4)
        elif self._state == UNCHECKED:
            painter.setPen(QPen(QColor(style.LINE), 1.5))
            painter.setBrush(QColor(style.SURFACE))
            painter.drawRoundedRect(box, 3, 3)
        elif self._state == UNAVAILABLE:
            painter.setPen(QPen(QColor(style.LINE_SOFT), 1.5))
            painter.setBrush(QColor(style.SURFACE_MUTED))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QPen(QColor(style.DISABLED), 3.4, cap=Qt.RoundCap))
            painter.drawLine(4, style.MARK_SIZE // 2, style.MARK_SIZE - 4, style.MARK_SIZE // 2)
        elif self._state == RUNNING:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(style.ACCENT_TRACK), 2.2))
            painter.drawEllipse(box)
            painter.setPen(QPen(QColor(style.ACCENT), 2.2, cap=Qt.RoundCap))
            painter.drawArc(box, 90 * 16, -120 * 16)
        elif self._state == DONE:
            # Без рамки: в макете готовая строка отмечена одной галочкой.
            self._draw_check(painter, QColor(style.ACCENT), 2.6)
        elif self._state in (FAILED, BROKEN):
            painter.setPen(QPen(QColor(style.ALERT), 2.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(box)
            painter.setPen(QPen(QColor(style.ALERT), 2.4, cap=Qt.RoundCap))
            painter.drawLine(5, 5, style.MARK_SIZE - 5, style.MARK_SIZE - 5)
            painter.drawLine(style.MARK_SIZE - 5, 5, 5, style.MARK_SIZE - 5)

    def _draw_check(self, painter: QPainter, color: QColor, width: float) -> None:
        """Галочка по тем же точкам, что в макете: 5,13 → 9,17 → 19,7 из 24."""
        scale = style.MARK_SIZE / 24.0
        path = QPainterPath()
        path.moveTo(5 * scale, 13 * scale)
        path.lineTo(9 * scale, 17 * scale)
        path.lineTo(19 * scale, 7 * scale)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, width * scale, cap=Qt.RoundCap, join=Qt.RoundJoin))
        painter.drawPath(path)


def literal_tooltip(*lines: str) -> str:
    """
    Подсказка, которая показывает текст буквально.

    Qt решает сам, считать ли подсказку разметкой: у неё нет режима «только
    текст», а Qt.mightBeRichText() отвечает «да» на любой текст с угловой
    скобкой. Название конфигурации и наименование поставки приходят из чужих
    файлов, и «<b>» в них превращало подсказку в жирный шрифт, а «<img>» —
    в попытку нарисовать картинку. Ровно там, где обещано полное название.

    Поэтому решаем за Qt: экранируем и оборачиваем в <qt>. Разметкой подсказка
    будет всегда, но своей — и покажет ровно то, что в файле.
    """
    body = "<br>".join(html.escape(line) for line in lines if line)
    return "<qt>%s</qt>" % body if body else ""


def _font(mono: bool, size: int) -> QFont:
    """QFont из тех же гарнитур, что и таблица стилей, но с точным размером."""
    font = QFont()
    names = list(style.families(mono))
    if hasattr(font, "setFamilies"):
        font.setFamilies(names)
    font.setFamily(names[0])
    font.setPixelSize(size)
    return font


class DetailLabel(QLabel):
    """
    Нижний ярус строки: путь либо «В 1С появится: …».

    Отдельный виджет, потому что укорачивать текст умеет только тот, кто знает
    свою ширину, — и узнаёт он её в своём resizeEvent, а не в чужом: у строки
    он случается ДО того, как разметка раздаст ширину подписям.

    Ширину строки подпись не диктует: длинное название конфигурации раздвигало
    строку шире окна, и с правого края за обрез уезжали объём и «Открыть
    папку» — то есть ровно то, зачем в готовую строку и смотрят.
    """

    #: Сколько места оставляем названию, даже когда его нет вовсе. Иначе на
    #: неразмеченной ещё строке от него остаётся одно многоточие.
    MIN_ROOM = 60

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._appears: Optional[Tuple[str, Tuple[str, ...]]] = None
        self.setFont(_font(mono=True, size=style.DETAIL_SIZE))

    def set_plain(self, text: str) -> None:
        self._appears = None
        self.setFont(_font(mono=True, size=style.DETAIL_SIZE))
        self.setTextFormat(Qt.PlainText)
        self.setToolTip("")
        self.setText(text)

    def set_appears(self, caption: str, values: Sequence[str]) -> None:
        self._appears = (caption, tuple(values))
        # Шрифт ставится виджету, а не таблицей стилей: размер из таблицы в
        # font() не попадает, и мерить пришлось бы не тем, чем рисуем.
        self.setFont(_font(mono=False, size=style.APPEARS_SIZE))
        self.setTextFormat(Qt.RichText)
        # Целиком — в подсказке: в строку название влезает не всегда, а узнать
        # его полностью человек должен без распаковки заново.
        self.setToolTip(literal_tooltip(*values))
        self._draw()

    def resizeEvent(self, event) -> None:
        """Стало шире — название должно дорасти обратно, а не остаться куцым."""
        super().resizeEvent(event)
        self._draw()

    def _draw(self) -> None:
        """
        Укорачивает названия до своей ширины.

        Укорачиваем сами, а не полагаемся на Qt: не влезший текст он обрезает
        молча, по границе виджета и без многоточия, и понять по такой строке,
        что название продолжается, нельзя.

        Значения приходят из чужого файла и экранируются здесь, а не у
        вызывающего: забыть экранирование можно только один раз, а «<b>» в
        названии конфигурации не должно становиться разметкой.
        """
        if self._appears is None:
            return
        caption, values = self._appears
        metrics = QFontMetrics(self.font())
        room = max(self.width() - metrics.width(caption + " "), DetailLabel.MIN_ROOM)
        shown = "<br>".join(
            '<span style="color: %s;">%s</span>'
            % (style.INK, html.escape(metrics.elidedText(value, Qt.ElideRight, room)))
            for value in values
        )
        self.setText("%s %s" % (html.escape(caption), shown))


class PlanRow(QWidget):
    """Одна строка плана."""

    toggled = pyqtSignal()
    open_requested = pyqtSignal()

    def __init__(self, title: str, detail: str, trailing: str, state: str) -> None:
        super().__init__()
        self._state = state

        self.mark = Mark(state)
        self.mark.setAccessibleName(title)
        # Наименование приходит из поставки, то есть из чужого файла: в голой
        # подсказке Qt приняло бы его за разметку.
        self.mark.setToolTip(literal_tooltip(title))
        self.mark.clicked.connect(self._toggle)

        self.label_title = QLabel(title)
        self.label_title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: %s;" % self._title_color()
        )
        self.label_trailing = QLabel(trailing)
        self.label_trailing.setProperty("role", "mono")
        self.label_trailing.setStyleSheet(
            "font-family: %s; font-size: 11px; color: %s;" % (style.mono_stack(), style.MUTED)
        )
        self.label_trailing.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.label_detail = DetailLabel(detail)
        self.label_detail.setStyleSheet(self._detail_sheet())
        self.button_open = QPushButton("")
        self.button_open.setStyleSheet(style.link_sheet())
        self.button_open.setCursor(Qt.PointingHandCursor)
        self.button_open.clicked.connect(self.open_requested.emit)
        self.button_open.hide()

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setStyleSheet(
            "QProgressBar { border: 0; border-radius: 2px; background: %s; }"
            "QProgressBar::chunk { border-radius: 2px; background: %s; }"
            % (style.ACCENT_TRACK, style.ACCENT)
        )
        self.progress.hide()

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.label_title, 1)
        top.addWidget(self.button_open)
        top.addWidget(self.label_trailing)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(self.label_detail, 1)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(2)
        body.addLayout(top)
        body.addWidget(self.progress)
        body.addLayout(bottom)

        outer = QHBoxLayout()
        outer.setContentsMargins(0, 9, 0, 9)
        outer.setSpacing(11)
        outer.addWidget(self.mark, 0, Qt.AlignTop)
        outer.addLayout(body, 1)
        self.setLayout(outer)
        self.setStyleSheet("PlanRow { border-bottom: 1px solid %s; }" % style.LINE_FAINT)

    # --- состояние -----------------------------------------------------------

    def _toggle(self) -> None:
        self.set_state(UNCHECKED if self._state == PENDING else PENDING)
        self.toggled.emit()

    def set_state(self, state: str) -> None:
        self._state = state
        self.mark.set_state(state)
        self.label_title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: %s;" % self._title_color()
        )
        self.progress.setVisible(state == RUNNING)
        self.setStyleSheet(
            "PlanRow { border-bottom: 1px solid %s; background: %s; }"
            % (style.LINE_FAINT, style.ACCENT_WASH if state == RUNNING else style.SURFACE)
        )

    def state(self) -> str:
        return self._state

    def selected(self) -> bool:
        """Поедет ли строка. Недоступные не поедут при любом желании."""
        return self._state == PENDING

    @staticmethod
    def _detail_sheet() -> str:
        """
        Нижний ярус по умолчанию — путь.

        Гарнитуру и размер ставит сам DetailLabel через QFont: из таблицы
        стилей они не попадают в font(), а мерить текст приходится тем же
        шрифтом, каким его рисуют.
        """
        return "color: %s;" % style.MUTED

    def _title_color(self) -> str:
        # Приглушённый заголовок у всего, что не поедет: в макете так отличают
        # снятое и недоступное от отмеченного.
        return style.INK if self._state in (PENDING, RUNNING, DONE) else style.MUTED

    # --- обновление ----------------------------------------------------------

    def set_detail(self, text: str) -> None:
        self.label_detail.setStyleSheet(self._detail_sheet())
        self.label_detail.set_plain(text)

    def set_appears(self, caption: str, values: Sequence[str]) -> None:
        """
        Нижний ярус готовой строки: «В 1С появится: …».

        Подпись приглушена, значение — основным цветом, как в макете; ради
        двух цветов в одной строке берётся разметка.
        """
        if not values:
            return
        # Не моноширинным: это фраза и название продукта, а не путь.
        self.label_detail.setStyleSheet("color: %s;" % style.MUTED)
        self.label_detail.set_appears(caption, values)



    def set_trailing(self, text: str) -> None:
        self.label_trailing.setText(text)

    def set_progress(self, done: int, total: int) -> None:
        """
        Ход внутри строки — в долях, а не в байтах.

        Границы QProgressBar — 32-битные, и файл от двух гигабайт отвергается
        с OverflowError. У поставок это обычный размер: один только .cf
        «Комплексной автоматизации» — 1.4 ГБ.
        """
        self.progress.setMaximum(style.PROGRESS_STEPS)
        self.progress.setValue(style.progress_value(done, total))

    def offer_open(self, text: str) -> None:
        self.button_open.setText(text)
        self.button_open.show()

    def texts(self) -> tuple:
        """Тексты строки. Нужны тестам: рисование проверять нечем."""
        return (
            self.label_title.text(),
            self.label_detail.text(),
            self.label_trailing.text(),
        )
