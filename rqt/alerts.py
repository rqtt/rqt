import time
from dataclasses import asdict, dataclass

from .fmt import to_unit

# key -> (label, unit, getter). Temperatures are stored in °C internally.
METRICS = {
    "cpu":       ("CPU usage",        "%",    lambda s: s.cpu),
    "cpu_temp":  ("CPU temperature",  "temp", lambda s: s.cpu_temp),
    "mem":       ("Memory usage",     "%",    lambda s: s.mem_pct),
    "swap":      ("Swap usage",       "%",    lambda s: s.swap_pct),
    "gpu":       ("GPU usage",        "%",    lambda s: s.gpu.util if s.gpu else None),
    "gpu_temp":  ("GPU temperature",  "temp", lambda s: s.gpu.temp if s.gpu else None),
    "vram":      ("VRAM usage",       "%",    lambda s: s.gpu.mem_pct if s.gpu else None),
    "net_rx":    ("Download",         "MB/s", lambda s: s.net_rx / 1e6),
    "net_tx":    ("Upload",           "MB/s", lambda s: s.net_tx / 1e6),
    "disk_free": ("System drive free", "%",   lambda s: s.root_free_pct),
}

COOLDOWN = 300  # don't re-notify the same rule more than once every 5 min


@dataclass
class AlertRule:
    metric: str = "cpu"
    op: str = ">"
    threshold: float = 90
    sustain: float = 10
    enabled: bool = True

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in ("metric", "op", "threshold", "sustain", "enabled") if k in d})

    def to_dict(self):
        return asdict(self)

    def unit(self, temp_unit):
        u = METRICS[self.metric][1]
        return f"°{temp_unit}" if u == "temp" else u


class AlertEngine:
    def __init__(self, rules=(), temp_unit="C"):
        self.temp_unit = temp_unit
        self.set_rules(rules)

    def set_rules(self, rules):
        self.rules = [r if isinstance(r, AlertRule) else AlertRule.from_dict(r) for r in rules]
        self._since = {}
        self._armed = {}
        self._last_fired = {}

    def check(self, snap):
        """Returns a list of human readable messages for rules that just fired."""
        now = time.monotonic()
        fired = []
        for i, rule in enumerate(self.rules):
            if not rule.enabled or rule.metric not in METRICS:
                continue
            label, unit, getter = METRICS[rule.metric]
            value = getter(snap)
            if value is None:
                self._since.pop(i, None)
                continue
            if unit == "temp":
                value = to_unit(value, self.temp_unit)

            tripped = value > rule.threshold if rule.op == ">" else value < rule.threshold
            if not tripped:
                self._since.pop(i, None)
                self._armed[i] = True
                continue

            start = self._since.setdefault(i, now)
            if now - start < rule.sustain or not self._armed.get(i, True):
                continue
            if now - self._last_fired.get(i, -COOLDOWN) < COOLDOWN:
                continue

            self._armed[i] = False
            self._last_fired[i] = now
            u = rule.unit(self.temp_unit)
            held = f" for {int(rule.sustain)}s" if rule.sustain else ""
            fired.append(f"{label} is {value:.0f}{u} ({rule.op} {rule.threshold:g}{u}{held})")
        return fired
