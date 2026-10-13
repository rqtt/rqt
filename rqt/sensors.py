"""
Everything that reads live numbers off the machine. Deliberately Qt-free so
it can be poked at from a plain Python shell:

    >>> from rqt.sensors import Sampler
    >>> s = Sampler(); import time; time.sleep(1); s.sample()
"""
import logging
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field

import psutil

from .gpu import detect_gpu_backends
from .lhm import LibreHardwareMonitor

log = logging.getLogger(__name__)

# psutil chip names for the CPU, roughly in order of how much I trust them
CPU_CHIPS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "soc_thermal", "acpitz")
CPU_LABELS = ("package id 0", "tctl", "tdie", "tccd1")

# same idea for LibreHardwareMonitor sensor names
LHM_CPU_NAMES = ("CPU Package", "Core (Tctl/Tdie)", "Core Max", "Core Average", "CPU Core")

DISK_USAGE_EVERY = 30  # seconds, no point stat'ing the drive every tick


@dataclass
class Snapshot:
    ts: float            # wall clock, used for history
    mono: float          # monotonic, used for graphs
    cpu: float
    per_core: list
    cpu_freq: float | None
    mem_used: int
    mem_total: int
    mem_pct: float
    swap_pct: float
    net_rx: float        # bytes/s
    net_tx: float
    disk_read: float     # bytes/s
    disk_write: float
    root_free_pct: float | None = None
    cpu_temp: float | None = None
    temps: dict = field(default_factory=dict)
    fans: dict = field(default_factory=dict)
    gpus: list = field(default_factory=list)

    @property
    def gpu(self):
        return self.gpus[0] if self.gpus else None


def system_drive():
    if sys.platform == "win32":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def cpu_name():
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=2)
            if out.stdout.strip():
                return out.stdout.strip()
        else:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine() or "Unknown CPU"


def _pick_cpu_temp_psutil(raw):
    for chip in CPU_CHIPS:
        entries = [e for e in raw.get(chip, ()) if e.current and 0 < e.current < 150]
        if not entries:
            continue
        for wanted in CPU_LABELS:
            for e in entries:
                if (e.label or "").lower().startswith(wanted):
                    return e.current
        # no labelled package sensor (e.g. Raspberry Pi), hottest one will do
        return max(e.current for e in entries)
    return None


def read_temps(lhm_rows):
    temps, fans = {}, {}
    cpu_temp = None

    if lhm_rows:
        cpu_candidates = {}
        for parent, hw, kind, name, value in lhm_rows:
            if value is None:
                continue
            if kind == "Temperature":
                temps[f"{hw} · {name}"] = float(value)
                if "cpu" in parent:
                    cpu_candidates[name] = float(value)
            elif kind == "Fan":
                fans[f"{hw} · {name}"] = float(value)
        for name in LHM_CPU_NAMES:
            if name in cpu_candidates:
                cpu_temp = cpu_candidates[name]
                break
        return temps, fans, cpu_temp

    if hasattr(psutil, "sensors_temperatures"):
        try:
            raw = psutil.sensors_temperatures()
        except Exception:
            raw = {}
        for chip, entries in raw.items():
            for i, e in enumerate(entries):
                # some boards report -273 or 127 for sensors that aren't wired up
                if e.current is None or not 0 < e.current < 125:
                    continue
                temps[f"{chip} · {e.label or f'temp{i + 1}'}"] = e.current
        cpu_temp = _pick_cpu_temp_psutil(raw)

    if hasattr(psutil, "sensors_fans"):
        try:
            for chip, entries in psutil.sensors_fans().items():
                for i, e in enumerate(entries):
                    fans[f"{chip} · {e.label or f'fan{i + 1}'}"] = float(e.current)
        except Exception:
            pass

    return temps, fans, cpu_temp


def _disk_counters():
    try:
        return psutil.disk_io_counters()
    except Exception:
        return None  # happens in some containers / VMs


class Sampler:
    def __init__(self):
        self.lhm = LibreHardwareMonitor()
        self.gpu_backends = detect_gpu_backends(self.lhm)
        self._root = system_drive()
        self._root_free = None
        self._last_du = float("-inf")  # so free space is known from the first tick

        psutil.cpu_percent(percpu=True)  # first call always returns zeros, prime it
        self._net = psutil.net_io_counters()
        self._disk = _disk_counters()
        self._t = time.monotonic()

    def sample(self):
        now = time.monotonic()
        dt = max(now - self._t, 1e-3)
        self._t = now

        cores = psutil.cpu_percent(percpu=True)
        total = sum(cores) / len(cores) if cores else 0.0
        try:
            freq = psutil.cpu_freq()
            freq = freq.current if freq else None
        except Exception:
            freq = None

        vm = psutil.virtual_memory()
        try:
            swap = psutil.swap_memory().percent
        except Exception:
            swap = 0.0

        net = psutil.net_io_counters()
        # counters can go backwards when an adapter disappears, clamp that away
        rx = max(0, net.bytes_recv - self._net.bytes_recv) / dt
        tx = max(0, net.bytes_sent - self._net.bytes_sent) / dt
        self._net = net

        disk = _disk_counters()
        if disk and self._disk:
            dr = max(0, disk.read_bytes - self._disk.read_bytes) / dt
            dw = max(0, disk.write_bytes - self._disk.write_bytes) / dt
        else:
            dr = dw = 0.0
        self._disk = disk

        if now - self._last_du > DISK_USAGE_EVERY:
            self._last_du = now
            try:
                self._root_free = 100.0 - psutil.disk_usage(self._root).percent
            except Exception:
                self._root_free = None

        lhm_rows = self.lhm.sensors() if self.lhm.available else []
        temps, fans, cpu_temp = read_temps(lhm_rows)

        gpus = []
        for backend in self.gpu_backends:
            try:
                gpus.extend(backend.read(lhm_rows))
            except Exception:
                log.exception("GPU backend %s failed", backend.name)

        return Snapshot(
            ts=time.time(), mono=now,
            cpu=total, per_core=cores, cpu_freq=freq,
            mem_used=vm.used, mem_total=vm.total, mem_pct=vm.percent, swap_pct=swap,
            net_rx=rx, net_tx=tx, disk_read=dr, disk_write=dw,
            root_free_pct=self._root_free,
            cpu_temp=cpu_temp, temps=temps, fans=fans, gpus=gpus,
        )

    def close(self):
        for b in self.gpu_backends:
            b.close()
