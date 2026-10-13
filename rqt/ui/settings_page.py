import logging
import os

from PySide6.QtCore import QProcess, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout,
                               QWidget)

from .. import APP_HTML, APP_NAME, APP_SLUG, __version__
from ..config import data_dir
from ..winapp import (FROZEN, IS_WINDOWS, autostart_enabled, build_exe_commands, create_shortcuts,
                      install_dir, installed_exe, set_autostart)
from .overlay import ITEMS
from .theme import logo_pixmap
from .widgets import Card, PageHeader

log = logging.getLogger(__name__)


def _form():
    f = QFormLayout()
    f.setHorizontalSpacing(18)
    f.setVerticalSpacing(10)
    f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return f


class SettingsPage(QWidget):
    changed = Signal()
    clear_history = Signal()
    reset_overlay = Signal()
    quit_requested = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self._loading = True
        self._build_steps = []
        self._proc = None

        # monitoring
        self.interval = QSpinBox()
        self.interval.setRange(250, 10000)
        self.interval.setSingleStep(250)
        self.interval.setSuffix(" ms")
        self.window = QSpinBox()
        self.window.setRange(30, 900)
        self.window.setSingleStep(30)
        self.window.setSuffix(" s")
        self.unit = QComboBox()
        self.unit.addItem("Celsius", "C")
        self.unit.addItem("Fahrenheit", "F")
        mon = Card("MONITORING")
        f = _form()
        f.addRow("Update every", self.interval)
        f.addRow("Chart length", self.window)
        f.addRow("Temperature unit", self.unit)
        mon.body.addLayout(f)

        # history
        self.hist_on = QCheckBox("Record history to disk")
        self.retention = QSpinBox()
        self.retention.setRange(1, 365)
        self.retention.setSuffix(" days")
        open_dir = QPushButton("Open data folder")
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))
        wipe = QPushButton("Clear history")
        wipe.setObjectName("danger")
        wipe.clicked.connect(self._confirm_clear)
        row = QHBoxLayout()
        row.addWidget(open_dir)
        row.addWidget(wipe)
        row.addStretch(1)
        hist = Card("HISTORY")
        f = _form()
        f.addRow(self.hist_on)
        f.addRow("Keep for", self.retention)
        hist.body.addLayout(f)
        hist.body.addLayout(row)

        # general
        self.tray_min = QCheckBox("Closing the window keeps it running in the tray")
        self.notify = QCheckBox("Show alert notifications")
        self.sound = QCheckBox("Beep on alerts")
        gen = Card("GENERAL")
        for w in (self.tray_min, self.notify, self.sound):
            gen.body.addWidget(w)

        # overlay
        self.ov_on = QCheckBox("Show overlay")
        self.ov_locked = QCheckBox("Lock it in place (clicks pass through)")
        self.ov_bars = QCheckBox("Bars and CPU sparkline")
        self.ov_corner = QComboBox()
        for c in ("top-left", "top-right", "bottom-left", "bottom-right"):
            self.ov_corner.addItem(c.replace("-", " ").capitalize(), c)
        self.ov_opacity = QSlider(Qt.Orientation.Horizontal)
        self.ov_opacity.setRange(10, 100)
        self.ov_font = QSpinBox()
        self.ov_font.setRange(7, 28)
        self.ov_font.setSuffix(" pt")
        self.ov_items = {}
        items = QGridLayout()
        items.setHorizontalSpacing(14)
        for i, (key, label) in enumerate(ITEMS.items()):
            cb = QCheckBox(label)
            self.ov_items[key] = cb
            items.addWidget(cb, i // 2, i % 2)
        reset = QPushButton("Snap back to corner")
        reset.clicked.connect(self.reset_overlay.emit)
        tip = QLabel("Unlock it to drag it anywhere. Shows over windowed and borderless apps, "
                     "not exclusive-fullscreen games.")
        tip.setObjectName("faint")
        tip.setWordWrap(True)
        ov = Card("OVERLAY")
        ov.header.addWidget(self.ov_on)
        f = _form()
        f.addRow(self.ov_locked)
        f.addRow(self.ov_bars)
        f.addRow("Corner", self.ov_corner)
        f.addRow("Background", self.ov_opacity)
        f.addRow("Text size", self.ov_font)
        ov.body.addLayout(f)
        shows = QLabel("Show")
        shows.setObjectName("muted")
        ov.body.addWidget(shows)
        ov.body.addLayout(items)
        ov.body.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        ov.body.addWidget(tip)

        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(mon)
        left.addWidget(hist)
        left.addWidget(gen)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(ov)

        if IS_WINDOWS:
            right.addWidget(self._windows_card())
        left.addStretch(1)
        right.addStretch(1)

        cols = QHBoxLayout()
        cols.setSpacing(12)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)

        head = PageHeader("settings")
        head.add_stretch()
        version = head.add(QLabel(f"{APP_NAME} v{__version__}"))
        version.setTextFormat(Qt.TextFormat.PlainText)
        version.setObjectName("mono")

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)
        lay.addWidget(head)
        lay.addLayout(cols)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.load(settings)
        for w in (self.interval, self.window, self.retention, self.ov_font):
            w.valueChanged.connect(self._commit)
        for w in (self.unit, self.ov_corner):
            w.currentIndexChanged.connect(self._commit)
        for w in (self.hist_on, self.tray_min, self.notify, self.sound,
                  self.ov_on, self.ov_locked, self.ov_bars, *self.ov_items.values()):
            w.toggled.connect(self._commit)
        self.ov_opacity.valueChanged.connect(self._commit)

    # -- Windows -------------------------------------------------------------

    def _windows_card(self):
        card = Card("WINDOWS")
        self.autostart = QCheckBox("Start with Windows (in the tray)")
        self.autostart.setChecked(autostart_enabled())
        self.autostart.toggled.connect(self._toggle_autostart)

        info = QLabel(f"Install it as a normal app: it gets its own {APP_SLUG}.exe, so Task Manager lists it as "
                      f"“{APP_HTML}”, plus Start menu and desktop shortcuts. "
                      "Takes a minute or two and needs an internet connection the first time.")
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setObjectName("muted")
        info.setWordWrap(True)
        self.install_btn = QPushButton("Reinstall app" if installed_exe() else "Install as app")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self._install)
        self.install_status = QLabel("Installed" if installed_exe() else "")
        self.install_status.setObjectName("faint")
        self.install_status.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(self.install_btn)
        row.addWidget(self.install_status, 1)
        card.body.addWidget(self.autostart)
        card.body.addSpacing(6)
        if FROZEN:
            # we *are* the installed app, rebuilding from here can't work
            done = QLabel("Running as the installed app.")
            done.setObjectName("muted")
            card.body.addWidget(done)
        else:
            card.body.addWidget(info)
            card.body.addLayout(row)
        return card

    def _toggle_autostart(self, on):
        try:
            set_autostart(on)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't change the startup setting:\n{e}")

    def _install(self):
        if self._proc is not None:
            return
        icon = os.path.join(os.path.dirname(install_dir()), f"{APP_SLUG}.ico")
        os.makedirs(os.path.dirname(icon), exist_ok=True)
        if not logo_pixmap(256).save(icon, "ICO"):
            icon = None
        self._build_steps = build_exe_commands(__version__, icon)
        self.install_btn.setEnabled(False)
        self._next_step()

    def _next_step(self):
        if not self._build_steps:
            self._finish_install()
            return
        label, argv = self._build_steps.pop(0)
        self.install_status.setText(label + "…")
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._build_output)
        self._proc.finished.connect(self._step_done)
        self._proc.start(argv[0], argv[1:])

    def _build_output(self):
        text = bytes(self._proc.readAllStandardOutput()).decode(errors="replace").strip()
        if text:
            log.info("build: %s", text)
            last = text.splitlines()[-1].strip()
            # PyInstaller lines look like "1234 INFO: Building ..."
            if "INFO:" in last:
                last = last.split("INFO:", 1)[1].strip()
            self.install_status.setText(last[:120])

    def _step_done(self, code, _status):
        self._proc = None
        if code != 0:
            self._build_steps = []
            self.install_btn.setEnabled(True)
            self.install_status.setText(f"Failed (exit code {code}). The details are in {APP_SLUG}.log in the data folder.")
            return
        self._next_step()

    def _finish_install(self):
        self.install_btn.setEnabled(True)
        exe = installed_exe()
        if not exe:
            self.install_status.setText(f"Build finished but {APP_SLUG}.exe wasn't found.")
            return
        create_shortcuts(exe)
        if autostart_enabled():
            set_autostart(True)   # point it at the new exe
        self.install_btn.setText("Reinstall app")
        self.install_status.setText("Installed. Use the desktop / Start menu shortcut from now on.")
        answer = QMessageBox.question(
            self, f"{APP_NAME} installed",
            f"{APP_SLUG}.exe is ready, with shortcuts on the desktop and in the Start menu.\n\n"
            "Switch to it now? This window closes and the installed app opens.")
        if answer == QMessageBox.StandardButton.Yes:
            QProcess.startDetached(exe, [])
            self.quit_requested.emit()

    # -- settings ------------------------------------------------------------

    def load(self, s):
        self._loading = True
        self.s = s
        self.interval.setValue(s.interval_ms)
        self.window.setValue(s.graph_window)
        self.unit.setCurrentIndex(max(0, self.unit.findData(s.temp_unit)))
        self.hist_on.setChecked(s.history_enabled)
        self.retention.setValue(s.retention_days)
        self.tray_min.setChecked(s.minimize_to_tray)
        self.notify.setChecked(s.tray_notifications)
        self.sound.setChecked(s.alert_sound)
        o = s.overlay
        self.ov_on.setChecked(o.enabled)
        self.ov_locked.setChecked(o.locked)
        self.ov_bars.setChecked(o.show_bars)
        self.ov_corner.setCurrentIndex(max(0, self.ov_corner.findData(o.corner)))
        self.ov_opacity.setValue(int(o.opacity * 100))
        self.ov_font.setValue(o.font_size)
        for key, cb in self.ov_items.items():
            cb.setChecked(key in o.items)
        self._loading = False

    def _commit(self, *_):
        if self._loading:
            return
        s = self.s
        s.interval_ms = self.interval.value()
        s.graph_window = self.window.value()
        s.temp_unit = self.unit.currentData()
        s.history_enabled = self.hist_on.isChecked()
        s.retention_days = self.retention.value()
        s.minimize_to_tray = self.tray_min.isChecked()
        s.tray_notifications = self.notify.isChecked()
        s.alert_sound = self.sound.isChecked()
        o = s.overlay
        o.enabled = self.ov_on.isChecked()
        o.locked = self.ov_locked.isChecked()
        o.show_bars = self.ov_bars.isChecked()
        corner = self.ov_corner.currentData()
        if corner != o.corner:
            o.corner = corner
            o.pos = None   # picking a corner overrides a dragged position
        o.opacity = self.ov_opacity.value() / 100
        o.font_size = self.ov_font.value()
        # keep the order from ITEMS rather than click order
        o.items = [k for k in ITEMS if self.ov_items[k].isChecked()]
        self.changed.emit()

    def _confirm_clear(self):
        answer = QMessageBox.question(self, "Clear history",
                                      "Delete all recorded history and alert events?")
        if answer == QMessageBox.StandardButton.Yes:
            self.clear_history.emit()
