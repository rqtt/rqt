"""
The always-on-top overlay. Frameless, translucent and (when locked) click-
through, so it can sit over a game or a render without stealing input.

Works over borderless/windowed apps. Exclusive fullscreen games draw straight
to the display and nothing can overlay them without hooking DirectX, which is
well out of scope here.
"""
from collections import deque

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from ..fmt import fmt_pct, fmt_temp, human_bytes, human_rate
from . import theme
from .theme import COLORS, load_color

ITEMS = {
    "cpu": "CPU",
    "cpu_temp": "CPU temp",
    "cpu_freq": "CPU clock",
    "gpu": "GPU",
    "gpu_temp": "GPU temp",
    "gpu_power": "GPU power",
    "vram": "VRAM",
    "ram": "RAM",
    "net": "Network",
    "disk": "Disk",
}

MARGIN = 16
PAD = 10
BAR_W = 46


def overlay_lines(s, items, unit):
    """[(label, text, fraction_or_None, colour)]"""
    g = s.gpu
    out = []
    for key in items:
        if key == "cpu":
            out.append(("CPU", fmt_pct(s.cpu), s.cpu / 100, load_color(s.cpu)))
        elif key == "cpu_temp" and s.cpu_temp is not None:
            out.append(("CPU", fmt_temp(s.cpu_temp, unit), s.cpu_temp / 100, QColor(COLORS["cpu_temp"])))
        elif key == "cpu_freq" and s.cpu_freq:
            out.append(("CLK", f"{s.cpu_freq / 1000:.2f} GHz", None, QColor(COLORS["cpu"])))
        elif key == "gpu" and g and g.util is not None:
            out.append(("GPU", fmt_pct(g.util), g.util / 100, load_color(g.util)))
        elif key == "gpu_temp" and g and g.temp is not None:
            out.append(("GPU", fmt_temp(g.temp, unit), g.temp / 100, QColor(COLORS["gpu_temp"])))
        elif key == "gpu_power" and g and g.power is not None:
            out.append(("PWR", f"{g.power:.0f} W", None, QColor(COLORS["gpu"])))
        elif key == "vram" and g and g.mem_used is not None:
            out.append(("VRAM", human_bytes(g.mem_used), (g.mem_pct or 0) / 100, QColor(COLORS["vram"])))
        elif key == "ram":
            out.append(("RAM", human_bytes(s.mem_used), s.mem_pct / 100, QColor(COLORS["mem"])))
        elif key == "net":
            out.append(("NET", f"↓{human_rate(s.net_rx)} ↑{human_rate(s.net_tx)}", None,
                        QColor(COLORS["net_rx"])))
        elif key == "disk":
            out.append(("DSK", human_rate(s.disk_read + s.disk_write), None, QColor(COLORS["disk_r"])))
    return out


class Overlay(QWidget):
    moved = Signal(int, int)

    def __init__(self, cfg, temp_unit="C"):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.cfg = cfg
        self.temp_unit = temp_unit
        self._lines = []
        self._cpu_hist = deque(maxlen=60)
        self._drag_from = None
        self.apply(cfg, temp_unit)

    def apply(self, cfg, temp_unit):
        was_visible = self.isVisible()
        self.cfg = cfg
        self.temp_unit = temp_unit
        self.font_ = theme.mono_font(cfg.font_size, bold=True)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, cfg.locked)
        self.setCursor(Qt.CursorShape.ArrowCursor if cfg.locked else Qt.CursorShape.SizeAllCursor)
        self._resize()
        self._place()
        # changing window flags hides the window, put it back
        if cfg.enabled:
            self.show()
        elif was_visible:
            self.hide()

    def update_from(self, snap):
        self._cpu_hist.append(snap.cpu)
        self._lines = overlay_lines(snap, self.cfg.items, self.temp_unit)
        self._resize()
        self.update()

    # -- geometry

    def _resize(self):
        fm = QFontMetrics(self.font_)
        lh = fm.height() + 4
        label_w = fm.horizontalAdvance("VRAM ")
        texts = [t for _, t, _, _ in self._lines] or ["100%"]
        value_w = max(fm.horizontalAdvance(t) for t in texts) + 8
        bar = BAR_W + 6 if self.cfg.show_bars else 0
        rows = max(1, len(self._lines))
        spark = 22 if self.cfg.show_bars else 0
        w = PAD * 2 + label_w + value_w + bar
        h = PAD * 2 + rows * lh + spark
        if (w, h) != (self.width(), self.height()):
            self.resize(int(w), int(h))
            if self.cfg.pos is None:
                self._place()

    def _place(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if self.cfg.pos:
            x, y = self.cfg.pos
            # monitor might have been unplugged since
            if any(sc.availableGeometry().contains(QPoint(x, y)) for sc in QGuiApplication.screens()):
                self.move(x, y)
                return
        corner = self.cfg.corner
        x = screen.left() + MARGIN if "left" in corner else screen.right() - self.width() - MARGIN
        y = screen.top() + MARGIN if "top" in corner else screen.bottom() - self.height() - MARGIN
        self.move(x, y)

    # -- painting

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(12, 12, 12)
        bg.setAlphaF(self.cfg.opacity)
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)

        if not self.cfg.locked:
            p.setPen(QColor(79, 163, 255, 180))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        p.setFont(self.font_)
        fm = QFontMetrics(self.font_)
        lh = fm.height() + 4
        label_w = fm.horizontalAdvance("VRAM ")
        value_x = PAD + label_w
        bar_x = self.width() - PAD - BAR_W

        y = PAD
        for label, text, frac, colour in self._lines:
            baseline = y + fm.ascent() + 2
            p.setPen(QColor(150, 158, 172))
            p.drawText(PAD, baseline, label)
            p.setPen(colour)
            p.drawText(value_x, baseline, text)
            if self.cfg.show_bars and frac is not None:
                by = y + lh / 2 - 2
                p.fillRect(QRectF(bar_x, by, BAR_W, 4), QColor(255, 255, 255, 30))
                p.fillRect(QRectF(bar_x, by, BAR_W * max(0.0, min(1.0, frac)), 4), colour)
            y += lh

        if self.cfg.show_bars and len(self._cpu_hist) > 1:
            self._sparkline(p, QRectF(PAD, y + 2, self.width() - PAD * 2, 16))
        p.end()

    def _sparkline(self, p, r):
        vals = list(self._cpu_hist)
        step = r.width() / (self._cpu_hist.maxlen - 1)
        x0 = r.right() - step * (len(vals) - 1)
        col = QColor(COLORS["cpu"])
        col.setAlpha(150)
        for i, v in enumerate(vals):
            h = max(1.0, r.height() * v / 100)
            p.fillRect(QRectF(x0 + i * step, r.bottom() - h, max(1.0, step - 1), h), col)

    # -- dragging (only when unlocked)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_from is not None:
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _e):
        if self._drag_from is not None:
            self._drag_from = None
            self.moved.emit(self.x(), self.y())
