import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..fmt import fmt_temp, human_rate, to_unit
from ..history import load_range
from .theme import COLORS, FAINT, MUTED, SURFACE, TEXT
from . import theme
from .widgets import Card, PageHeader, RateAxis, set_text

RANGES = [
    ("15m", 15 * 60),
    ("1h", 3600),
    ("6h", 6 * 3600),
    ("24h", 86400),
    ("7d", 7 * 86400),
    ("30d", 30 * 86400),
]

# title, kind, [(column, label)]
PANELS = [
    ("Usage", "pct", [("cpu", "CPU"), ("gpu", "GPU"), ("mem", "RAM"), ("vram", "VRAM")]),
    ("Temperature", "temp", [("cpu_temp", "CPU"), ("gpu_temp", "GPU")]),
    ("Network", "rate", [("net_rx", "Down"), ("net_tx", "Up")]),
    ("Disk", "rate", [("disk_r", "Read"), ("disk_w", "Write")]),
]


class _LoadSignals(QObject):
    done = Signal(int, object)


class _Loader(QRunnable):
    def __init__(self, token, path, start, end):
        super().__init__()
        self.token, self.path, self.start, self.end = token, path, start, end
        self.signals = _LoadSignals()

    def run(self):
        try:
            result = load_range(self.path, self.start, self.end)
        except Exception as e:
            result = {"error": str(e)}
        self.signals.done.emit(self.token, result)


def _legend_chip(color, label):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    dot = QLabel()
    dot.setFixedSize(8, 8)
    dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
    text = QLabel(label)
    text.setObjectName("faint")
    lay.addWidget(dot)
    lay.addWidget(text)
    return w


class ChartPanel(Card):
    def __init__(self, title, kind, series, parent=None):
        super().__init__(title, parent)
        self.kind = kind
        self.series = series
        self.unit = "C"
        for col, label in series:
            self.header.addWidget(_legend_chip(COLORS[col], label))

        axes = {"bottom": pg.DateAxisItem()}
        if kind == "rate":
            axes["left"] = RateAxis(orientation="left")
        self.plot = pg.PlotWidget(axisItems=axes, background=SURFACE)
        pi = self.plot.getPlotItem()
        pi.showGrid(x=False, y=True, alpha=0.08)
        pi.hideButtons()
        pi.setMenuEnabled(False)
        pi.setMouseEnabled(x=True, y=False)
        pi.getAxis("left").setWidth(64 if kind == "rate" else 40)
        for name in ("left", "bottom"):
            ax = pi.getAxis(name)
            ax.setPen(pg.mkPen(FAINT))
            ax.setTextPen(pg.mkPen(MUTED))
            ax.setStyle(tickFont=theme.mono_font(8))
        self.curves = {}
        for col, _label in series:
            self.curves[col] = self.plot.plot([], [], pen=pg.mkPen(COLORS[col], width=1.6),
                                              connect="finite")
        self.plot.setMinimumHeight(170)
        self.body.addWidget(self.plot, 1)

        # hover readout
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(255, 255, 255, 50))
        self.readout = pg.TextItem(anchor=(0, 0), color=TEXT, fill=pg.mkBrush(28, 32, 40, 235))
        self.vline.hide()
        self.readout.hide()
        self.plot.addItem(self.vline, ignoreBounds=True)
        self.plot.addItem(self.readout, ignoreBounds=True)
        self.plot.scene().sigMouseMoved.connect(self._hover)
        self.x = np.empty(0)
        self.y = {}

    def _fmt(self, v):
        if v is None or not np.isfinite(v):
            return "–"
        if self.kind == "pct":
            return f"{v:.0f}%"
        if self.kind == "temp":
            return f"{v:.0f}°{self.unit}"
        return human_rate(v)

    def set_data(self, x, columns, unit, start, end):
        self.unit = unit
        self.x = x
        self.y = {}
        peak = 0.0
        for col, curve in self.curves.items():
            raw = columns.get(col, [])
            y = np.array([np.nan if v is None else v for v in raw], dtype=float)
            if self.kind == "temp":
                y = np.array([to_unit(v, unit) if np.isfinite(v) else np.nan for v in y], dtype=float)
            self.y[col] = y
            # a lone sample is invisible as a line, give short series dots
            sparse = np.count_nonzero(np.isfinite(y)) < 4
            curve.setData(x, y, symbol="o" if sparse else None, symbolSize=5,
                          symbolBrush=COLORS[col], symbolPen=None)
            if y.size and np.isfinite(y).any():
                peak = max(peak, float(np.nanmax(y)))

        if self.kind == "pct":
            top = 100
        elif self.kind == "temp":
            top = max(60.0, peak * 1.1)
        else:
            top = max(1024.0, peak * 1.15)
        self.plot.setYRange(0, top, padding=0)
        self.plot.setXRange(start, end, padding=0.01)

    def _hover(self, pos):
        vb = self.plot.getPlotItem().vb
        if not self.x.size or not vb.sceneBoundingRect().contains(pos):
            self.vline.hide()
            self.readout.hide()
            return
        x = vb.mapSceneToView(pos).x()
        i = int(np.clip(np.searchsorted(self.x, x), 0, self.x.size - 1))
        if i > 0 and abs(self.x[i - 1] - x) < abs(self.x[i] - x):
            i -= 1
        stamp = datetime.fromtimestamp(self.x[i]).strftime("%d %b %H:%M:%S")
        lines = [f"<span style='color:{MUTED}'>{stamp}</span>"]
        for col, label in self.series:
            y = self.y.get(col)
            v = y[i] if y is not None and i < y.size else None
            lines.append(f"<span style='color:{COLORS[col]}'>●</span> {label} <b>{self._fmt(v)}</b>")
        self.readout.setHtml("<div style='padding:4px'>" + "<br>".join(lines) + "</div>")

        (x0, x1), (_y0, y1) = vb.viewRange()
        self.readout.setAnchor((1, 0) if x > (x0 + x1) / 2 else (0, 0))
        self.readout.setPos(self.x[i], y1)
        self.vline.setPos(self.x[i])
        self.vline.show()
        self.readout.show()


class StatTile(QFrame):
    def __init__(self, title, color, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        t = QLabel(title.lower())
        t.setObjectName("cardTitle")
        self.value = QLabel("–")
        self.value.setFont(theme.mono_font(14, bold=True))
        self.value.setStyleSheet(f"color: {color};")
        self.sub = QLabel("")
        self.sub.setObjectName("faint")
        lay.addWidget(t)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value, sub):
        set_text(self.value, value)
        set_text(self.sub, sub)


class HistoryPage(QWidget):
    def __init__(self, store, settings, parent=None):
        super().__init__(parent)
        self.store = store          # UI connection, only used for the CSV export
        self.settings = settings
        self._token = 0
        self._loading = False
        self._again = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)

        self.note = QLabel("")
        self.note.setObjectName("mono")

        segbar = QFrame()
        segbar.setObjectName("segbar")
        seg_lay = QHBoxLayout(segbar)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(2)
        self.range_group = QButtonGroup(self)
        for i, (label, secs) in enumerate(RANGES):
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setProperty("seconds", secs)
            self.range_group.addButton(b, i)
            seg_lay.addWidget(b)
        self.range_group.button(1).setChecked(True)
        self.range_group.idClicked.connect(lambda _i: self.refresh())

        export = QPushButton("Export CSV")
        export.setToolTip("Save every sample in this range as a spreadsheet-friendly CSV")
        export.clicked.connect(self.export)

        head = PageHeader("history")
        head.add(self.note, 1)
        head.add(segbar)
        head.add(export)

        self.tiles = {
            "cpu": StatTile("CPU", COLORS["cpu"]),
            "gpu": StatTile("GPU", COLORS["gpu"]),
            "mem": StatTile("Memory", COLORS["mem"]),
            "cpu_temp": StatTile("CPU temp", COLORS["cpu_temp"]),
            "gpu_temp": StatTile("GPU temp", COLORS["gpu_temp"]),
            "net_rx": StatTile("Download", COLORS["net_rx"]),
        }
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        for t in self.tiles.values():
            tiles.addWidget(t, 1)

        self.panels = [ChartPanel(*spec) for spec in PANELS]
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, panel in enumerate(self.panels):
            grid.addWidget(panel, i // 2, i % 2)
            if i:
                panel.plot.setXLink(self.panels[0].plot)

        self.empty = QLabel("Nothing recorded in this range yet. Leave the app running and it fills in.")
        self.empty.setObjectName("muted")
        self.empty.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)
        lay.addWidget(head)
        lay.addLayout(tiles)
        lay.addWidget(self.empty)
        lay.addLayout(grid, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(15_000)
        self.timer.timeout.connect(self._auto_refresh)

    def _seconds(self):
        return self.range_group.checkedButton().property("seconds")

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def _auto_refresh(self):
        if self._seconds() <= 6 * 3600:
            self.refresh()

    def refresh(self):
        if self._loading:
            # one query at a time; a range clicked mid-load runs right after
            self._again = True
            return
        self._loading = True
        self._token += 1
        end = time.time()
        loader = _Loader(self._token, self.store.path, end - self._seconds(), end)
        loader.signals.done.connect(self._loaded)
        loader.setAutoDelete(False)
        self._loader = loader   # keep the Python side alive until it reports back
        self.pool.start(loader)

    def _loaded(self, token, r):
        self._loading = False
        if self._again:
            self._again = False
            self.refresh()
            return
        if token != self._token or not self.isVisible():
            return
        if "error" in r:
            set_text(self.note, f"Couldn't read history: {r['error']}")
            return

        unit = self.settings.temp_unit
        has_data = bool(r["count"])
        self.empty.setVisible(not has_data)
        x = np.asarray(r.get("ts", []), dtype=float)
        for panel in self.panels:
            panel.set_data(x, r.get("series", {}), unit, r["start"], r["end"])

        if not has_data:
            set_text(self.note, "")
            for t in self.tiles.values():
                t.set("–", "")
            return

        requested = r["end"] - self._seconds()
        if r["first"] > requested + 60:
            since = datetime.fromtimestamp(r["first"])
            fmt = "%H:%M" if since.date() == datetime.now().date() else "%d %b %H:%M"
            set_text(self.note, f"recording since {since.strftime(fmt)}")
        else:
            set_text(self.note, "")

        stats = r["stats"]

        def show(col, f):
            lo, avg, hi = stats.get(col, (None, None, None))
            if avg is None:
                self.tiles[col].set("–", "no data")
            else:
                self.tiles[col].set(f(avg), f"avg  ·  max {f(hi)}")

        pct = lambda v: f"{v:.0f}%"  # noqa: E731
        temp = lambda v: fmt_temp(v, unit)  # noqa: E731
        show("cpu", pct)
        show("gpu", pct)
        show("mem", pct)
        show("cpu_temp", temp)
        show("gpu_temp", temp)
        show("net_rx", human_rate)

    def export(self):
        end = time.time()
        start = end - self._seconds()
        default = f"rqt-{datetime.now():%Y%m%d-%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export history", default, "CSV (*.csv)")
        if not path:
            return
        try:
            n = self.store.export_csv(path, start, end)
        except OSError as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        QMessageBox.information(self, "Exported", f"Wrote {n:,} rows to\n{path}")
