from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..fmt import human_rate
from . import theme
from .theme import ACCENT, FAINT, MUTED, SURFACE_3, load_color


def set_text(label, text):
    # setText always invalidates the layout, even for identical text. Ten
    # labels doing that every second adds up, so skip the no-ops.
    if label.text() != text:
        label.setText(text)


def ignored_width(label):
    """Let the layout decide the width so changing text never triggers a relayout."""
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


class PageHeader(QWidget):
    """
    Terminal-prompt style page title, e.g. "❯ processes". Extra widgets go on
    the right via add().
    """

    def __init__(self, name, parent=None):
        super().__init__(parent)
        title = QLabel(f"<span style='color:{ACCENT}'>\u276f</span>&nbsp;{name}")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setFont(theme.mono_font(15, bold=True))
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(10)
        self.row.addWidget(title)
        self.row.addSpacing(8)

    def add(self, widget, stretch=0):
        self.row.addWidget(widget, stretch)
        return widget

    def add_stretch(self):
        self.row.addStretch(1)


class Card(QFrame):
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(8)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            self.title = QLabel(title.lower())
            self.title.setObjectName("cardTitle")
            self.header.addWidget(self.title)
        self.header.addStretch(1)
        self.body.addLayout(self.header)


class Banner(QFrame):
    """A one-line notice with an optional link and a dismiss button."""
    dismissed = Signal()

    def __init__(self, text, link_text=None, url=None, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setStyleSheet("color: #f3d8a6;")
        lay.addWidget(msg, 1)
        if link_text and url:
            link = QPushButton(link_text)
            link.setObjectName("link")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            lay.addWidget(link)
        close = QPushButton("Dismiss")
        close.setObjectName("link")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self._dismiss)
        lay.addWidget(close)

    def _dismiss(self):
        self.hide()
        self.dismissed.emit()


class AreaChart(QWidget):
    """
    A small rolling chart painted by hand. pyqtgraph is great for the zoomable
    history plots, but six of its full PlotWidgets refreshing every second was
    the main reason the dashboard felt heavy. This draws the same thing with a
    couple of QPainterPaths.
    """

    def __init__(self, window=120, y_max=100.0, floor=1.0, fmt=None, parent=None):
        super().__init__(parent)
        self.window = window
        self.y_max = y_max          # None = autoscale
        self.floor = floor
        self.fmt = fmt or (lambda v: f"{v:.0f}%")
        self._series = []
        self._top = y_max or floor
        self._now = 0.0
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._small = theme.mono_font(7.5)

    def add_series(self, key, color, fill=True, width=1.8, dashed=False):
        self._series.append({"key": key, "color": QColor(color), "fill": fill,
                             "width": width, "dashed": dashed, "pts": deque()})

    def set_window(self, seconds):
        self.window = seconds
        self.update()

    def clear_data(self):
        for s in self._series:
            s["pts"].clear()
        self._top = self.y_max or self.floor
        self.update()

    def push(self, now, values):
        self._now = now
        cutoff = now - self.window - 2
        peak = 0.0
        for s in self._series:
            v = values.get(s["key"])
            pts = s["pts"]
            pts.append((now, v))
            while pts and pts[0][0] < cutoff:
                pts.popleft()
            for _, val in pts:
                if val is not None and val > peak:
                    peak = val

        if self.y_max is None:
            # grow straight away, shrink gently so the scale doesn't twitch
            target = max(peak * 1.25, self.floor)
            self._top = target if target > self._top else self._top * 0.95 + target * 0.05
        if self.isVisible():
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 6, 0, -2)
        top = self.y_max or self._top or 1.0

        # two faint guides with the scale written on the right
        p.setFont(self._small)
        for frac in (0.5, 1.0):
            y = r.bottom() - r.height() * frac
            p.setPen(QPen(QColor(255, 255, 255, 16), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(r.left(), y - 14, r.width() - 2, 13),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                       self.fmt(top * frac))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))

        def x_of(t):
            return r.right() - (self._now - t) / self.window * r.width()

        def y_of(v):
            return r.bottom() - min(max(v, 0.0), top) / top * r.height()

        for s in self._series:
            # split into runs so a missing reading leaves a gap instead of a dive to zero
            runs, run = [], []
            for t, v in s["pts"]:
                if v is None:
                    if run:
                        runs.append(run)
                    run = []
                else:
                    run.append(QPointF(x_of(t), y_of(v)))
            if run:
                runs.append(run)

            colour = s["color"]
            for run in runs:
                if len(run) < 2:
                    continue
                line = QPainterPath(run[0])
                for pt in run[1:]:
                    line.lineTo(pt)
                if s["fill"]:
                    area = QPainterPath(line)
                    area.lineTo(run[-1].x(), r.bottom())
                    area.lineTo(run[0].x(), r.bottom())
                    area.closeSubpath()
                    grad = QLinearGradient(0, r.top(), 0, r.bottom())
                    c1, c2 = QColor(colour), QColor(colour)
                    c1.setAlpha(80)
                    c2.setAlpha(4)
                    grad.setColorAt(0, c1)
                    grad.setColorAt(1, c2)
                    p.fillPath(area, QBrush(grad))
                pen = QPen(colour, s["width"])
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                if s["dashed"]:
                    pen.setStyle(Qt.PenStyle.DashLine)
                p.strokePath(line, pen)
        p.end()


class CoreStrip(QWidget):
    """One thin bar per logical core."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vals = []
        self.setFixedHeight(22)

    def set_values(self, vals):
        self._vals = list(vals)
        if self.isVisible():
            self.update()

    def paintEvent(self, _event):
        n = len(self._vals)
        if not n:
            return
        p = QPainter(self)
        w, h = self.width(), self.height()
        gap = 3 if n <= 24 else 1
        bw = max(1.0, (w - gap * (n - 1)) / n)
        track = QColor(SURFACE_3)
        for i, v in enumerate(self._vals):
            x = i * (bw + gap)
            p.fillRect(QRectF(x, 0, bw, h), track)
            bh = h * max(0.0, min(100.0, v)) / 100
            p.fillRect(QRectF(x, h - bh, bw, bh), load_color(v))
        p.end()


class MetricTile(QFrame):
    """Card with a title, a big number, a detail line and a live chart."""

    def __init__(self, title, color, chart, extra=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.chart = chart

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.title = QLabel(title.lower())
        self.title.setObjectName("cardTitle")
        self.side = ignored_width(QLabel(""))
        self.side.setObjectName("mono")
        self.side.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(dot)
        head.addWidget(self.title)
        head.addWidget(self.side, 1)

        self.value = ignored_width(QLabel("–"))
        self.value.setObjectName("bigValue")
        self.detail = ignored_width(QLabel(""))
        self.detail.setObjectName("muted")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(4)
        lay.addLayout(head)
        lay.addSpacing(2)
        lay.addWidget(self.value)
        lay.addWidget(self.detail)
        if extra is not None:
            lay.addSpacing(4)
            lay.addWidget(extra)
        lay.addSpacing(4)
        lay.addWidget(chart, 1)

    def set(self, value, detail="", side=""):
        set_text(self.value, value)
        set_text(self.detail, detail)
        set_text(self.side, side)


class RateAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [human_rate(v * scale).replace(".0 ", " ") for v in values]


class SensorTree(QTreeWidget):
    """Grouped key/value list that updates in place instead of rebuilding."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Sensor", "Value"])
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setIndentation(16)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.header().resizeSection(1, 160)
        self._groups = {}
        self._items = {}
        self._bold = QFont(self.font())
        self._bold.setBold(True)
        self._mono = theme.mono_font(9.5)

    def set_group(self, group, rows):
        parent = self._groups.get(group)
        if parent is None:
            parent = QTreeWidgetItem(self, [group, ""])
            parent.setFirstColumnSpanned(True)
            parent.setFont(0, self._bold)
            parent.setForeground(0, QColor(MUTED))
            parent.setExpanded(True)
            self._groups[group] = parent

        seen = set()
        for name, text in rows:
            key = (group, name)
            seen.add(key)
            item = self._items.get(key)
            if item is None:
                item = QTreeWidgetItem(parent, [name, text])
                item.setFont(1, self._mono)
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._items[key] = item
            elif item.text(1) != text:
                item.setText(1, text)

        for key in [k for k in self._items if k[0] == group and k not in seen]:
            parent.removeChild(self._items.pop(key))
        parent.setHidden(parent.childCount() == 0)
