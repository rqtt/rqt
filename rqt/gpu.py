"""
GPU readers. There's no portable way to do this, so there's one backend per
vendor/platform combo and the sampler just asks all of them:

  NvmlBackend      NVIDIA on Windows + Linux (needs the nvidia-ml-py package)
  AmdSysfsBackend  AMD on Linux, straight from the amdgpu sysfs files
  LhmGpuBackend    anything on Windows, via LibreHardwareMonitor
"""
import glob
import logging
import os
import re
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class GpuReading:
    name: str
    util: float | None = None
    mem_used: int | None = None
    mem_total: int | None = None
    temp: float | None = None
    power: float | None = None   # watts
    clock: int | None = None     # MHz
    fan: float | None = None     # percent

    @property
    def mem_pct(self):
        if self.mem_used is None or not self.mem_total:
            return None
        return 100.0 * self.mem_used / self.mem_total


def _try(fn):
    try:
        return fn()
    except Exception:
        return None


class NvmlBackend:
    name = "NVML"

    def __init__(self):
        import pynvml
        pynvml.nvmlInit()
        self.nv = pynvml
        count = pynvml.nvmlDeviceGetCount()
        if count == 0:
            pynvml.nvmlShutdown()
            raise RuntimeError("NVML loaded but found no devices")
        self.devices = []
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):  # older bindings return bytes
                name = name.decode(errors="replace")
            self.devices.append((h, name))

    def read(self, _lhm_rows=None):
        nv = self.nv
        out = []
        for h, name in self.devices:
            r = GpuReading(name)
            r.util = _try(lambda: float(nv.nvmlDeviceGetUtilizationRates(h).gpu))
            mem = _try(lambda: nv.nvmlDeviceGetMemoryInfo(h))
            if mem is not None:
                r.mem_used, r.mem_total = int(mem.used), int(mem.total)
            r.temp = _try(lambda: float(nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU)))
            mw = _try(lambda: nv.nvmlDeviceGetPowerUsage(h))
            r.power = mw / 1000 if mw is not None else None
            r.clock = _try(lambda: nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_GRAPHICS))
            # laptops and passively cooled cards throw NotSupported here
            r.fan = _try(lambda: float(nv.nvmlDeviceGetFanSpeed(h)))
            out.append(r)
        return out

    def close(self):
        _try(self.nv.nvmlShutdown)


def _read_sys(path, cast=str):
    try:
        with open(path) as f:
            return cast(f.read().strip())
    except (OSError, ValueError):
        return None


class AmdSysfsBackend:
    name = "amdgpu"

    def __init__(self):
        self.cards = []
        for card in sorted(glob.glob("/sys/class/drm/card*")):
            # skip connector entries like card0-DP-1, they point back at the same device
            if not re.fullmatch(r"card\d+", os.path.basename(card)):
                continue
            dev = os.path.join(card, "device")
            if not os.path.exists(os.path.join(dev, "gpu_busy_percent")):
                continue
            hwmons = glob.glob(os.path.join(dev, "hwmon", "hwmon*"))
            name = _read_sys(os.path.join(dev, "product_name")) or "AMD Radeon"
            self.cards.append((dev, hwmons[0] if hwmons else None, name))
        if not self.cards:
            raise RuntimeError("no amdgpu devices")

    def read(self, _lhm_rows=None):
        out = []
        for dev, hwmon, name in self.cards:
            r = GpuReading(name)
            r.util = _read_sys(os.path.join(dev, "gpu_busy_percent"), float)
            r.mem_used = _read_sys(os.path.join(dev, "mem_info_vram_used"), int)
            r.mem_total = _read_sys(os.path.join(dev, "mem_info_vram_total"), int)
            if hwmon:
                t = _read_sys(os.path.join(hwmon, "temp1_input"), int)
                r.temp = t / 1000 if t is not None else None
                uw = (_read_sys(os.path.join(hwmon, "power1_average"), int)
                      or _read_sys(os.path.join(hwmon, "power1_input"), int))
                r.power = uw / 1e6 if uw else None
                hz = _read_sys(os.path.join(hwmon, "freq1_input"), int)
                r.clock = hz // 1_000_000 if hz else None
                pwm = _read_sys(os.path.join(hwmon, "pwm1"), int)
                r.fan = pwm / 255 * 100 if pwm is not None else None
            out.append(r)
        return out

    def close(self):
        pass


class LhmGpuBackend:
    name = "LibreHardwareMonitor"

    def __init__(self, lhm, skip_nvidia=False):
        if not lhm.available:
            raise RuntimeError("LibreHardwareMonitor not running")
        self.skip_nvidia = skip_nvidia

    def read(self, rows):
        gpus = {}
        for parent, hw, kind, name, value in rows or ():
            if not parent.startswith("/gpu"):
                continue
            if self.skip_nvidia and parent.startswith("/gpu-nvidia"):
                continue  # NVML already covers these, and does it better
            g = gpus.setdefault(parent, GpuReading(hw))
            if value is None:
                continue
            if kind == "Load" and name == "GPU Core":
                g.util = float(value)
            elif kind == "Temperature" and name == "GPU Core":
                g.temp = float(value)
            elif kind == "Temperature" and g.temp is None and name.startswith("GPU"):
                g.temp = float(value)
            elif kind == "SmallData" and name in ("GPU Memory Used", "D3D Dedicated Memory Used"):
                g.mem_used = int(value * 1024 * 1024)
            elif kind == "SmallData" and name in ("GPU Memory Total", "D3D Dedicated Memory Total"):
                g.mem_total = int(value * 1024 * 1024)
            elif kind == "Power" and name in ("GPU Package", "GPU Power", "GPU Core"):
                g.power = float(value)
            elif kind == "Clock" and name == "GPU Core":
                g.clock = int(value)
            elif kind == "Control" and name.startswith("GPU Fan"):
                g.fan = float(value)
        return list(gpus.values())

    def close(self):
        pass


def detect_gpu_backends(lhm):
    backends = []
    try:
        backends.append(NvmlBackend())
    except Exception as e:
        log.info("NVML unavailable: %s", e)

    if sys.platform.startswith("linux"):
        try:
            backends.append(AmdSysfsBackend())
        except Exception as e:
            log.info("amdgpu sysfs unavailable: %s", e)

    if lhm is not None and lhm.available:
        has_nvml = any(isinstance(b, NvmlBackend) for b in backends)
        backends.append(LhmGpuBackend(lhm, skip_nvidia=has_nvml))

    log.info("GPU backends: %s", ", ".join(b.name for b in backends) or "none")
    return backends
