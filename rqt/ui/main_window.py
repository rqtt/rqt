import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout,
                               QWidget)

from .. import APP_NAME
from ..alerts import AlertEngine
from ..config import data_dir, save_settings
from ..fmt import fmt_pct, fmt_temp, to_unit
from ..history import HistoryStore
from ..winapp import style_title_bar
from ..worker import MonitorThread
from .alerts_page import AlertsPage
from .bench_page import BenchPage
from .dashboard import DashboardPage
from .history_page import HistoryPage
from .overlay import Overlay
from .processes import ProcessesPage
from .sensors_page import SensorsPage
from .settings_page import SettingsPage
from .theme import STRIP, app_icon, logo_pixmap, tab_icon

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._quitting = False
        self._last_snap = None
        self._told_about_tray = False
        self._styled_title = False
        self.db_path = data_dir() / "history.db"

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1360, 860)
        self.setMinimumSize(1000, 660)

        # the UI keeps its own connection for alert events, bench results and CSV export
        self.store = HistoryStore(self.db_path)
        self.alerts = AlertEngine(settings.alerts, settings.temp_unit)

        self.dashboard = DashboardPage(settings)
        self.processes = ProcessesPage()
        self.sensors = SensorsPage(settings)
        self.history = HistoryPage(self.store, settings)
        self.alerts_page = AlertsPage(settings, self.store)
        self.bench = BenchPage(self.store, settings)
        self.settings_page = SettingsPage(settings)

        pages = [
            ("dashboard", self.dashboard),
            ("processes", self.processes),
            ("sensors", self.sensors),
            ("history", self.history),
            ("alerts", self.alerts_page),
            ("benchmark", self.bench),
            ("settings", self.settings_page),
        ]
        self.stack = QStackedWidget()
        self.tabs = QButtonGroup(self)
        self.tabs.setExclusive(True)
        strip = self._tab_strip(pages)
        self.tabs.idToggled.connect(lambda i, on: on and self._switch_page(i))

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(strip)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # Windows Terminal-ish keyboard: Ctrl+1..7 jump to a tab, Ctrl+Tab cycles
        for i in range(len(pages)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.select_tab(i))
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self.select_tab(self.stack.currentIndex() + 1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self,
                  activated=lambda: self.select_tab(self.stack.currentIndex() - 1))

        self.overlay = Overlay(settings.overlay, settings.temp_unit)
        self.overlay.moved.connect(self._overlay_moved)
        self._build_tray()

        self.alerts_page.rules_changed.connect(self._rules_changed)
        self.settings_page.changed.connect(self._settings_changed)
        self.settings_page.clear_history.connect(self._clear_history)
        self.settings_page.reset_overlay.connect(self._reset_overlay)
        self.settings_page.quit_requested.connect(self.quit)

        # writing settings on every slider tick is pointless, batch it
        self._save_timer = QTimer(self, singleShot=True, interval=800)
        self._save_timer.timeout.connect(lambda: save_settings(self.settings))
        self.dashboard.banner.dismissed.connect(self._save_timer.start)

        self.monitor = MonitorThread(self.db_path, settings.interval_ms,
                                     settings.history_enabled, settings.retention_days)
        self.monitor.snapshot.connect(self._on_snapshot)
        self.monitor.processes.connect(self.processes.on_processes)
        self.monitor.failed.connect(lambda msg: QMessageBox.critical(self, APP_NAME, msg))
        self.monitor.start()

        self.select_tab(0)

    def _tab_strip(self, pages):
        strip = QWidget()
        strip.setObjectName("strip")
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(strip)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(2)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(44))
        logo.setScaledContents(True)
        logo.setFixedSize(22, 22)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        brand.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(logo)
        row.addSpacing(6)
        row.addWidget(brand)
        row.addSpacing(18)

        for i, (name, page) in enumerate(pages):
            b = QPushButton(name)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setIcon(tab_icon(name))
            b.setIconSize(QSize(16, 16))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(f"{name.capitalize()}  (Ctrl+{i + 1})")
            self.tabs.addButton(b, i)
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignBottom)
            self.stack.addWidget(page)
        row.addStretch(1)
        strip.setFixedHeight(46)
        return strip

    def select_tab(self, index):
        index %= self.stack.count()
        self.tabs.button(index).setChecked(True)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._styled_title:
            self._styled_title = True
            style_title_bar(self.winId(), STRIP)

    # -- tray

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu(self)
        menu.addAction(f"Open {APP_NAME}", self.show_normal)
        self.overlay_action = QAction("Overlay", menu, checkable=True)
        self.overlay_action.setChecked(self.settings.overlay.enabled)
        self.overlay_action.toggled.connect(self._toggle_overlay)
        menu.addAction(self.overlay_action)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    def _tray_clicked(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_normal()

    def show_normal(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized)
                            | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        if self._last_snap:
            self._paint_current(self._last_snap)

    def _toggle_overlay(self, on):
        if on == self.settings.overlay.enabled:
            return
        self.settings.overlay.enabled = on
        self.overlay.apply(self.settings.overlay, self.settings.temp_unit)
        self.settings_page.load(self.settings)
        self._save_timer.start()

    # -- data

    def _on_snapshot(self, s):
        self._last_snap = s

        # Only the tab you're looking at gets repainted, and nothing at all
        # while the window is hidden or minimised. The dashboard charts still
        # need their history though, so they get fed quietly in the background.
        on_screen = self.isVisible() and not self.isMinimized()
        if on_screen:
            self._paint_current(s)
        if not (on_screen and self.stack.currentWidget() is self.dashboard):
            self._feed_dashboard_charts(s)

        if self.settings.overlay.enabled:
            self.overlay.update_from(s)

        for msg in self.alerts.check(s):
            self.store.log_event("alert", msg, s.ts)
            self.alerts_page.add_event(s.ts, "alert", msg)
            if self.settings.tray_notifications:
                self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.MessageIcon.Warning, 8000)
            if self.settings.alert_sound:
                QApplication.beep()

        # the Windows tray tooltip is plain native text, so no HTML here
        unit = self.settings.temp_unit
        tip = f"{APP_NAME}\ncpu {fmt_pct(s.cpu)}"
        if s.cpu_temp is not None:
            tip += f"  {fmt_temp(s.cpu_temp, unit)}"
        tip += f"\nram {fmt_pct(s.mem_pct)}"
        if s.gpu:
            tip += f"\ngpu {fmt_pct(s.gpu.util)}  {fmt_temp(s.gpu.temp, unit)}"
        self.tray.setToolTip(tip)

    def _paint_current(self, s):
        page = self.stack.currentWidget()
        if page is self.dashboard:
            self.dashboard.on_snapshot(s)
        elif page is self.sensors:
            self.sensors.on_snapshot(s)
        elif page is self.bench:
            self.bench.on_snapshot(s)

    def _feed_dashboard_charts(self, s):
        # keeps the rolling charts continuous without touching any labels
        g = s.gpu
        unit = self.settings.temp_unit
        d = self.dashboard
        busiest = max(s.per_core) if s.per_core else None
        d.cpu.chart.push(s.mono, {"cpu": s.cpu, "peak": busiest})
        d.gpu.chart.push(s.mono, {"gpu": g.util if g else None, "vram": g.mem_pct if g else None})
        d.mem.chart.push(s.mono, {"mem": s.mem_pct, "swap": s.swap_pct})
        d.temp.chart.push(s.mono, {"cpu_temp": to_unit(s.cpu_temp, unit),
                                   "gpu_temp": to_unit(g.temp, unit) if g else None})
        d.net.chart.push(s.mono, {"rx": s.net_rx, "tx": s.net_tx})
        d.disk.chart.push(s.mono, {"r": s.disk_read, "w": s.disk_write})

    def _switch_page(self, index):
        self.stack.setCurrentIndex(index)
        self.monitor.want_processes = self.stack.currentWidget() is self.processes
        if self._last_snap:
            self._paint_current(self._last_snap)

    def _rules_changed(self, rules):
        self.settings.alerts = rules
        self.alerts.set_rules(rules)
        self._save_timer.start()

    def _settings_changed(self):
        s = self.settings
        self.monitor.interval = s.interval_ms / 1000
        self.monitor.history_enabled = s.history_enabled
        self.monitor.retention_days = s.retention_days
        self.alerts.temp_unit = s.temp_unit
        self.dashboard.apply_settings(s)
        self.overlay.apply(s.overlay, s.temp_unit)
        self.overlay_action.blockSignals(True)
        self.overlay_action.setChecked(s.overlay.enabled)
        self.overlay_action.blockSignals(False)
        self._save_timer.start()

    def _overlay_moved(self, x, y):
        self.settings.overlay.pos = [x, y]
        self._save_timer.start()

    def _reset_overlay(self):
        self.settings.overlay.pos = None
        self.overlay.apply(self.settings.overlay, self.settings.temp_unit)
        self._save_timer.start()

    def _clear_history(self):
        self.store.clear()
        self.alerts_page.log.clear()
        if self.history.isVisible():
            self.history.refresh()

    def save_screenshot(self, path):
        """Used by --screenshot, handy for the README."""
        ok = self.grab().save(str(path))
        log.info("screenshot %s -> %s", "saved" if ok else "FAILED", path)
        return ok

    # -- shutdown

    def closeEvent(self, e):
        if (self.settings.minimize_to_tray and not self._quitting
                and QSystemTrayIcon.isSystemTrayAvailable()):
            e.ignore()
            self.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self.tray.showMessage(APP_NAME, "Still running in the tray. Right-click the icon to quit.",
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
            return
        self._shutdown()
        e.accept()
        QApplication.quit()

    def quit(self):
        self._quitting = True
        self.close()

    def _shutdown(self):
        save_settings(self.settings)
        self.bench.shutdown()
        self.monitor.stop()
        self.overlay.close()
        self.tray.hide()
        self.store.close()
