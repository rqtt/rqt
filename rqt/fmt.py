"""Small formatting helpers shared by the UI, the overlay and the CSV export."""

DASH = "–"


def human_bytes(n, digits=1):
    if n is None:
        return DASH
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            break
        n /= 1024
    if unit == "B":
        return f"{n:.0f} B"
    return f"{n:.{digits}f} {unit}"


def human_rate(n):
    if n is None:
        return DASH
    return human_bytes(n) + "/s"


def to_unit(celsius, unit="C"):
    if celsius is None:
        return None
    return celsius * 9 / 5 + 32 if unit == "F" else celsius


def fmt_temp(celsius, unit="C"):
    v = to_unit(celsius, unit)
    return DASH if v is None else f"{v:.0f}°{unit}"


def fmt_pct(v, digits=0):
    return DASH if v is None else f"{v:.{digits}f}%"


def fmt_duration(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"
