"""
Look and feel. Loosely modelled on Windows Terminal: tabs in a strip that
blends into the title bar, a near-black canvas, Cascadia for anything that's
a number, and Segoe UI for the rest.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath,
                           QPalette, QPen, QPixmap)

STRIP = "#1f1f1f"       # tab strip + title bar
STRIP_HOVER = "#2a2a2a"
BG = "#0c0c0c"          # content canvas, same as the active tab
SURFACE = "#161616"     # cards
SURFACE_2 = "#1d1d1d"
SURFACE_3 = "#292929"
BORDER = "#262626"
TEXT = "#e8e8e8"
MUTED = "#9a9a9a"
FAINT = "#5f5f5f"
ACCENT = "#4cc2ff"
DANGER = "#ff5f6d"
OK = "#5fd068"
WARN = "#f2c94c"

COLORS = {
    "cpu": "#4cc2ff",
    "cpu_peak": "#a6e1ff",
    "gpu": "#6ccb5f",
    "vram": "#b7e4b0",
    "mem": "#c792ea",
    "swap": "#e4c9f5",
    "cpu_temp": "#ff9b54",
    "gpu_temp": "#f9e27d",
    "net_rx": "#56d6c2",
    "net_tx": "#ff6b8b",
    "disk_r": "#8aa4ff",
    "disk_w": "#e0a96d",
}

# filled in by apply_theme() once a QApplication exists
MONO = "monospace"
UI = ""

MONO_CANDIDATES = ("Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas",
                   "SF Mono", "Menlo", "DejaVu Sans Mono", "Liberation Mono")
UI_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Cantarell", "Noto Sans")


def _pick(candidates, fallback):
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


def mono_font(point_size=10.0, bold=False):
    f = QFont(MONO)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSizeF(point_size)
    f.setBold(bold)
    return f


def stylesheet():
    # Kept small on purpose: colours come from the palette, and a broad
    # "QWidget { ... }" rule makes Qt restyle every single widget.
    return f"""
QWidget#strip {{ background: {STRIP}; }}
QLabel#brand {{ font-family: "{MONO}"; font-size: 12pt; font-weight: 600; }}
QPushButton#tab {{
    background: transparent;
    border: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 16px 9px 12px;
    color: {MUTED};
    text-align: left;
}}
QPushButton#tab:hover {{ background: {STRIP_HOVER}; color: {TEXT}; }}
QPushButton#tab:checked {{ background: {BG}; color: {TEXT}; }}

QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#banner {{
    background: #241f12;
    border: 1px solid #4a3d16;
    border-radius: 8px;
}}
QLabel#cardTitle {{ color: {MUTED}; font-family: "{MONO}"; font-size: 9pt; }}
QLabel#bigValue {{ font-family: "{MONO}"; font-size: 21pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#faint {{ color: {FAINT}; font-size: 9pt; }}
QLabel#mono {{ font-family: "{MONO}"; color: {MUTED}; }}

QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:disabled {{ color: {FAINT}; }}
QPushButton#primary {{ background: {ACCENT}; color: #00121c; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #7fd4ff; }}
QPushButton#danger {{ color: {DANGER}; }}
QPushButton#link {{ background: transparent; border: none; color: {ACCENT}; padding: 2px 6px; }}
QFrame#segbar {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 7px; }}
QPushButton#seg {{
    background: transparent; border: none; border-radius: 5px;
    padding: 4px 11px; color: {MUTED}; font-family: "{MONO}";
}}
QPushButton#seg:hover {{ color: {TEXT}; }}
QPushButton#seg:checked {{ background: {SURFACE_3}; color: {TEXT}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-bottom: 1px solid #3a3a3a;
    border-radius: 6px;
    padding: 5px 8px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-bottom: 2px solid {ACCENT}; }}

QTableView, QTreeWidget, QTableWidget, QListWidget {{
    background: {SURFACE};
    alternate-background-color: #191919;
    border: none;
    selection-background-color: #10354a;
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {SURFACE};
    color: {FAINT};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-family: "{MONO}";
}}
QProgressBar {{ background: {SURFACE_3}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ border-radius: 2px; background: {ACCENT}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SURFACE_3}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
"""


def apply_theme(app):
    global MONO, UI
    MONO = _pick(MONO_CANDIDATES, "monospace")
    UI = _pick(UI_CANDIDATES, app.font().family())

    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: SURFACE_2,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: SURFACE_2,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: "#10354a",
        QPalette.ColorRole.HighlightedText: TEXT,
        QPalette.ColorRole.ToolTipBase: SURFACE_3,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: FAINT,
        QPalette.ColorRole.Link: ACCENT,
        QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Dark: BG,
    }
    for role, colour in roles.items():
        pal.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(FAINT))
    app.setPalette(pal)

    font = QFont(UI)
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet())


def draw_logo(p, size):
    """
    The r<q>t mark: a q between two chevrons on a dark tile. Same geometry as
    assets/icon.svg, on a 64-unit grid.
    """
    s = size / 64
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    tile = QLinearGradient(0, 0, 0, size)
    tile.setColorAt(0, QColor("#2b2f36"))
    tile.setColorAt(1, QColor("#121417"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(tile))
    p.drawRoundedRect(QRectF(0, 0, size, size), 14 * s, 14 * s)

    def pen(colour, width):
        pn = QPen(QColor(colour), width * s)
        pn.setCapStyle(Qt.PenCapStyle.RoundCap)
        pn.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pn

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(pen(ACCENT, 5))
    for pts in (((21, 21), (11, 32), (21, 43)), ((43, 21), (53, 32), (43, 43))):
        path = QPainterPath(QPointF(pts[0][0] * s, pts[0][1] * s))
        for x, y in pts[1:]:
            path.lineTo(QPointF(x * s, y * s))
        p.drawPath(path)

    p.setPen(pen("#f2f2f2", 4.5))
    p.drawEllipse(QPointF(30.5 * s, 30 * s), 6.5 * s, 6.5 * s)
    p.drawLine(QPointF(37 * s, 23.5 * s), QPointF(37 * s, 46 * s))


def logo_pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_logo(p, size)
    p.end()
    return pm


def app_icon():
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(s))
    return icon


def _glyph(kind, colour):
    """Little line icons for the tabs, drawn at 2x so they stay crisp."""
    pm = QPixmap(40, 40)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(colour), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.scale(20 / 24, 20 / 24)

    if kind == "dashboard":
        for x, y, w, h in ((4, 4, 7, 9), (13, 4, 7, 5), (13, 11, 7, 9), (4, 15, 7, 5)):
            p.drawRoundedRect(QRectF(x, y, w, h), 1.8, 1.8)
    elif kind == "processes":
        for y in (6, 12, 18):
            p.drawPoint(QPointF(5, y))
            p.drawLine(QPointF(9, y), QPointF(20, y))
    elif kind == "sensors":
        p.drawRoundedRect(QRectF(9.5, 3.5, 5, 12), 2.5, 2.5)
        p.drawEllipse(QPointF(12, 17.5), 3.6, 3.6)
        p.drawLine(QPointF(12, 8), QPointF(12, 15))
    elif kind == "history":
        p.drawEllipse(QPointF(12, 12), 8, 8)
        p.drawLine(QPointF(12, 7.5), QPointF(12, 12))
        p.drawLine(QPointF(12, 12), QPointF(15.5, 14))
    elif kind == "alerts":
        bell = QPainterPath(QPointF(6, 16.5))
        bell.cubicTo(7.3, 14.8, 7.3, 13.5, 7.3, 10.8)
        bell.cubicTo(7.3, 7.6, 9.4, 5.5, 12, 5.5)
        bell.cubicTo(14.6, 5.5, 16.7, 7.6, 16.7, 10.8)
        bell.cubicTo(16.7, 13.5, 16.7, 14.8, 18, 16.5)
        bell.closeSubpath()
        p.drawPath(bell)
        p.drawLine(QPointF(10.5, 19.5), QPointF(13.5, 19.5))
    elif kind == "benchmark":
        p.drawArc(QRectF(4, 5, 16, 16), -30 * 16, 240 * 16)
        p.drawLine(QPointF(12, 13), QPointF(15.5, 9))
    elif kind == "settings":
        for y, knob in ((6, 15), (12, 8), (18, 13)):
            p.drawLine(QPointF(4, y), QPointF(20, y))
            p.setBrush(QColor(STRIP))
            p.drawEllipse(QPointF(knob, y), 2.2, 2.2)
            p.setBrush(Qt.BrushStyle.NoBrush)
    p.end()
    return pm


def tab_icon(kind):
    icon = QIcon()
    icon.addPixmap(_glyph(kind, MUTED), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_glyph(kind, ACCENT), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(_glyph(kind, TEXT), QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(_glyph(kind, ACCENT), QIcon.Mode.Active, QIcon.State.On)
    return icon


def load_color(pct):
    """green -> amber -> red as load goes up"""
    if pct is None:
        return QColor(MUTED)
    if pct < 60:
        return QColor(OK)
    if pct < 85:
        return QColor(WARN)
    return QColor(DANGER)
