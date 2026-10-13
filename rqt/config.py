import json
import logging
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)


def _base_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home()))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


_checked_old = False


def data_dir():
    global _checked_old
    path = _base_dir() / "rqt"
    if not _checked_old:
        _checked_old = True
        # the app used to be called Pulse; bring its history and settings along
        for old_name in ("Pulse", "pulse"):
            old = _base_dir() / old_name
            if old.is_dir() and not path.exists():
                try:
                    shutil.move(str(old), str(path))
                    log.info("moved old data from %s", old)
                except OSError:
                    log.warning("couldn't move %s, starting fresh", old)
                break
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_alerts():
    return [
        {"metric": "cpu", "op": ">", "threshold": 95, "sustain": 30, "enabled": True},
        {"metric": "cpu_temp", "op": ">", "threshold": 90, "sustain": 10, "enabled": True},
        {"metric": "gpu_temp", "op": ">", "threshold": 85, "sustain": 10, "enabled": True},
        {"metric": "mem", "op": ">", "threshold": 90, "sustain": 30, "enabled": True},
        {"metric": "disk_free", "op": "<", "threshold": 10, "sustain": 0, "enabled": True},
    ]


@dataclass
class OverlaySettings:
    enabled: bool = False
    items: list = field(default_factory=lambda: ["cpu", "cpu_temp", "gpu", "gpu_temp", "ram", "net"])
    opacity: float = 0.78
    font_size: int = 11
    locked: bool = True
    corner: str = "top-left"
    pos: list | None = None
    show_bars: bool = True


@dataclass
class Settings:
    interval_ms: int = 1000
    graph_window: int = 120
    temp_unit: str = "C"
    history_enabled: bool = True
    retention_days: int = 14
    minimize_to_tray: bool = True
    tray_notifications: bool = True
    alert_sound: bool = False
    hide_temp_hint: bool = False
    alerts: list = field(default_factory=default_alerts)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)


def _merge(cls, raw):
    # only take keys we still know about, so old config files don't blow up
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in raw.items() if k in known}


def config_path():
    return data_dir() / "settings.json"


def load_settings():
    path = config_path()
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        overlay = OverlaySettings(**_merge(OverlaySettings, raw.pop("overlay", {}) or {}))
        return Settings(**_merge(Settings, raw), overlay=overlay)
    except Exception:
        log.exception("couldn't read %s, using defaults", path)
        return Settings()


def save_settings(settings):
    path = config_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    tmp.replace(path)
