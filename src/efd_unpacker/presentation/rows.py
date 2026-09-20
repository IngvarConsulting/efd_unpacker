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


from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
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
FAILED = "failed"


class Mark(QAbstractButton):
    """
    Знак состояния 16×16.

    Кнопка, а не голый виджет: от QAbstractButton достаются фокус, пробел и
    Enter, и имя для средств доступности. Мышью-то щёлкнуть можно и по
    виджету, а вот с клавиатуры строку было не отметить вовсе.

    Недоступные состояния гасятся: выключенная кнопка не берёт фокус и не
    срабатывает, так что «уже установлено» и отказ не переключить ни мышью,
    ни клавишей.
    """

    def __init__(self, state: str = PENDING) -> None:
        super().__init__()
        self._state = state
        self.setFixedSize(style.MARK_SIZE, style.MARK_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setEnabled(state in (PENDING, UNCHECKED))

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.setEnabled(state in (PENDING, UNCHECKED))
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
        elif self._state == FAILED:
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


class PlanRow(QWidget):
    """Одна строка плана."""

    toggled = pyqtSignal()
    open_requested = pyqtSignal()

    def __init__(self, title: str, detail: str, trailing: str, state: str) -> None:
        super().__init__()
        self._state = state

        self.mark = Mark(state)
        self.mark.setAccessibleName(title)
        self.mark.setToolTip(title)
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

        self.label_detail = QLabel(detail)
        self.label_detail.setStyleSheet(
            "font-family: %s; font-size: 11px; color: %s;" % (style.mono_stack(), style.MUTED)
        )
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

    def _title_color(self) -> str:
        # Приглушённый заголовок у всего, что не поедет: в макете так отличают
        # снятое и недоступное от отмеченного.
        return style.INK if self._state in (PENDING, RUNNING, DONE) else style.MUTED

    # --- обновление ----------------------------------------------------------

    def set_detail(self, text: str) -> None:
        self.label_detail.setText(text)

    def set_trailing(self, text: str) -> None:
        self.label_trailing.setText(text)

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(min(done, max(total, 1)))

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
