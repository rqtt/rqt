import platform
import sys
import time

import psutil
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ..fmt import fmt_duration, fmt_pct, fmt_temp, human_bytes, human_rate, to_unit
from ..sensors import cpu_name
from .theme import COLORS
from .widgets import AreaChart, Banner, CoreStrip, MetricTile, PageHeader, ignored_width, set_text

LHM_URL = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases"


def _rate_label(v):
    return human_rate(v).replace(".0 ", " ")


class DashboardPage(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._boot = psutil.boot_time()
        self._physical = psutil.cpu_count(logical=False)
        w = settings.graph_window

        cpu_chart = AreaChart(w)
        cpu_chart.add_series("peak", COLORS["cpu_peak"], fill=False, width=1.1, dashed=True)
        cpu_chart.add_series("cpu", COLORS["cpu"])
        self.cores = CoreStrip()
        self.cpu = MetricTile("CPU", COLORS["cpu"], cpu_chart, extra=self.cores)

        gpu_chart = AreaChart(w)
        gpu_chart.add_series("vram", COLORS["vram"], fill=False, width=1.1, dashed=True)
        gpu_chart.add_series("gpu", COLORS["gpu"])
        self.gpu = MetricTile("GPU", COLORS["gpu"], gpu_chart)

        mem_chart = AreaChart(w)
        mem_chart.add_series("swap", COLORS["swap"], fill=False, width=1.1, dashed=True)
        mem_chart.add_series("mem", COLORS["mem"])
        self.mem = MetricTile("Memory", COLORS["mem"], mem_chart)

        temp_chart = AreaChart(w, y_max=None, floor=100, fmt=lambda v: f"{v:.0f}°")
        temp_chart.add_series("gpu_temp", COLORS["gpu_temp"], fill=False, width=2)
        temp_chart.add_series("cpu_temp", COLORS["cpu_temp"], fill=True, width=2)
        self.temp = MetricTile("Temperature", COLORS["cpu_temp"], temp_chart)

        net_chart = AreaChart(w, y_max=None, floor=128 * 1024, fmt=_rate_label)
        net_chart.add_series("tx", COLORS["net_tx"])
        net_chart.add_series("rx", COLORS["net_rx"])
        self.net = MetricTile("Network", COLORS["net_rx"], net_chart)

        disk_chart = AreaChart(w, y_max=None, floor=2 * 1024 * 1024, fmt=_rate_label)
        disk_chart.add_series("w", COLORS["disk_w"])
        disk_chart.add_series("r", COLORS["disk_r"])
        self.disk = MetricTile("Disk", COLORS["disk_r"], disk_chart)

        self.tiles = [self.cpu, self.gpu, self.mem, self.temp, self.net, self.disk]

        head = PageHeader("dashboard")
        self.sysline = head.add(ignored_width(QLabel()), 1)
        self.sysline.setObjectName("mono")
        self.sysline.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.banner = Banner("CPU temperature isn't available yet. On Windows it needs LibreHardwareMonitor "
                             "running in the background as administrator.",
                             "Get LibreHardwareMonitor", LHM_URL)
        self.banner.hide()
        self.banner.dismissed.connect(self._hide_hint)

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, tile in enumerate(self.tiles):
            grid.addWidget(tile, i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        for r in range(2):
            grid.setRowStretch(r, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)
        lay.addWidget(head)
        lay.addWidget(self.banner)
        lay.addLayout(grid, 1)

        self._cpu_name = cpu_name()
        self._sys_tick = 0

    def apply_settings(self, settings):
        self.settings = settings
        for tile in self.tiles:
            tile.chart.set_window(settings.graph_window)
        # already-plotted temperatures are in the old unit
        self.temp.chart.clear_data()

    def _hide_hint(self):
        self.settings.hide_temp_hint = True

    def on_snapshot(self, s):
        unit = self.settings.temp_unit
        g = s.gpu
        t = s.mono

        # CPU
        busiest = max(s.per_core) if s.per_core else None
        freq = f"{s.cpu_freq / 1000:.2f} GHz" if s.cpu_freq else ""
        self.cpu.set(fmt_pct(s.cpu), f"Busiest core {fmt_pct(busiest)}", freq)
        self.cpu.chart.push(t, {"cpu": s.cpu, "peak": busiest})
        self.cores.set_values(s.per_core)

        # GPU
        if g:
            bits = []
            if g.temp is not None:
                bits.append(fmt_temp(g.temp, unit))
            if g.power:
                bits.append(f"{g.power:.0f} W")
            if g.mem_total:
                bits.append(f"VRAM {human_bytes(g.mem_used)} / {human_bytes(g.mem_total)}")
            self.gpu.set(fmt_pct(g.util), "  ·  ".join(bits) or g.name, _short_gpu(g.name))
            self.gpu.chart.push(t, {"gpu": g.util, "vram": g.mem_pct})
        else:
            self.gpu.set("–", "No supported GPU detected")
            self.gpu.chart.push(t, {})

        # Memory
        self.mem.set(fmt_pct(s.mem_pct), f"Swap {fmt_pct(s.swap_pct)}",
                     f"{human_bytes(s.mem_used)} / {human_bytes(s.mem_total)}")
        self.mem.chart.push(t, {"mem": s.mem_pct, "swap": s.swap_pct})

        # Temperature: lead with the CPU, fall back to the GPU when there's no CPU sensor
        gpu_temp = g.temp if g else None
        lead = s.cpu_temp if s.cpu_temp is not None else gpu_temp
        parts = []
        if s.cpu_temp is not None:
            parts.append(f"CPU {fmt_temp(s.cpu_temp, unit)}")
        if gpu_temp is not None:
            parts.append(f"GPU {fmt_temp(gpu_temp, unit)}")
        hottest = max(s.temps.values()) if s.temps else None
        side = f"hottest sensor {fmt_temp(hottest, unit)}" if hottest is not None else ""
        self.temp.set(fmt_temp(lead, unit), "  ·  ".join(parts) or "No sensors found", side)
        self.temp.chart.push(t, {"cpu_temp": to_unit(s.cpu_temp, unit), "gpu_temp": to_unit(gpu_temp, unit)})

        show_hint = (s.cpu_temp is None and sys.platform == "win32"
                     and not self.settings.hide_temp_hint)
        if show_hint != self.banner.isVisible():
            self.banner.setVisible(show_hint)

        # Network / disk
        self.net.set(f"↓ {human_rate(s.net_rx)}", f"↑ {human_rate(s.net_tx)}", "down / up")
        self.net.chart.push(t, {"rx": s.net_rx, "tx": s.net_tx})
        free = f"{s.root_free_pct:.0f}% free on system drive" if s.root_free_pct is not None else ""
        self.disk.set(human_rate(s.disk_read + s.disk_write),
                      f"Read {human_rate(s.disk_read)}  ·  Write {human_rate(s.disk_write)}", free)
        self.disk.chart.push(t, {"r": s.disk_read, "w": s.disk_write})

        # the header line barely changes, no need to rebuild it every tick
        self._sys_tick -= 1
        if self._sys_tick <= 0:
            self._sys_tick = 30
            set_text(self.sysline,
                     f"{self._cpu_name}  ·  {self._physical}c/{len(s.per_core)}t  ·  "
                     f"{human_bytes(s.mem_total, 0)}  ·  {platform.system()} {platform.release()}  ·  "
                     f"up {fmt_duration(time.time() - self._boot)}")


def _short_gpu(name):
    for junk in ("NVIDIA ", "GeForce ", "AMD ", "Radeon(TM) ", "(TM)", "(R)"):
        name = name.replace(junk, "")
    return name.strip()
