import time

import psutil
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..fmt import fmt_temp, human_bytes
from .widgets import Card, PageHeader, SensorTree

DRIVES_EVERY = 15  # seconds


class SensorsPage(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._drives = []
        self._drives_at = 0.0

        head = PageHeader("sensors")
        sub = head.add(QLabel("every reading this machine exposes"))
        sub.setObjectName("mono")
        head.add_stretch()

        self.tree = SensorTree()
        card = Card()
        card.body.setContentsMargins(6, 6, 6, 6)
        card.body.addWidget(self.tree)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)
        lay.addWidget(head)
        lay.addWidget(card, 1)

    def on_snapshot(self, s):
        unit = self.settings.temp_unit

        cpu = [("Load", f"{s.cpu:.0f}%")]
        if s.cpu_freq:
            cpu.append(("Clock", f"{s.cpu_freq:.0f} MHz"))
        if s.cpu_temp is not None:
            cpu.append(("Temperature", fmt_temp(s.cpu_temp, unit)))
        for i, v in enumerate(s.per_core):
            cpu.append((f"Thread {i}", f"{v:.0f}%"))
        self.tree.set_group("CPU", cpu)

        temps = [(k, fmt_temp(v, unit)) for k, v in sorted(s.temps.items())]
        if not temps:
            temps = [("No temperature sensors found", "")]
        self.tree.set_group("Temperatures", temps)

        fans = [(k, f"{v:.0f} RPM" if v > 100 else f"{v:.0f}%") for k, v in sorted(s.fans.items())]
        self.tree.set_group("Fans", fans)

        gpu_rows = []
        for i, g in enumerate(s.gpus):
            pre = f"GPU {i} · " if len(s.gpus) > 1 else ""
            gpu_rows.append((pre + "Name", g.name))
            if g.util is not None:
                gpu_rows.append((pre + "Load", f"{g.util:.0f}%"))
            if g.temp is not None:
                gpu_rows.append((pre + "Temperature", fmt_temp(g.temp, unit)))
            if g.clock:
                gpu_rows.append((pre + "Core clock", f"{g.clock} MHz"))
            if g.mem_total:
                gpu_rows.append((pre + "VRAM", f"{human_bytes(g.mem_used)} / {human_bytes(g.mem_total)}"))
            if g.power is not None:
                gpu_rows.append((pre + "Power", f"{g.power:.1f} W"))
            if g.fan is not None:
                gpu_rows.append((pre + "Fan", f"{g.fan:.0f}%"))
        self.tree.set_group("GPU", gpu_rows)

        mem = [("Used", f"{human_bytes(s.mem_used)} / {human_bytes(s.mem_total)}"),
               ("Swap / page file", f"{s.swap_pct:.0f}%")]
        self.tree.set_group("Memory", mem)

        if time.monotonic() - self._drives_at > DRIVES_EVERY:
            self._drives_at = time.monotonic()
            self._drives = _drives()
        self.tree.set_group("Drives", self._drives)


def _drives():
    rows = []
    try:
        parts = psutil.disk_partitions(all=False)
    except Exception:
        return rows
    for part in parts:
        # empty card readers and DVD drives can hang or throw, skip them
        if "cdrom" in part.opts or part.fstype == "":
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (OSError, PermissionError):
            continue
        rows.append((part.mountpoint, f"{human_bytes(u.free)} free of {human_bytes(u.total)}"))
    return rows
