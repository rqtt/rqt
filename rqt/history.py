"""
SQLite-backed metric history.

One row per sample, which sounds like a lot but works out to ~86k rows/day at
the default 1s interval, or about 6 MB. Queries over long ranges are averaged
into buckets in SQL so the plots never get more than ~1500 points.

The monitor thread owns a writer connection and the UI opens its own reader;
WAL mode lets them coexist without locking each other out.
"""
import csv
import sqlite3
import time
from datetime import datetime

COLUMNS = ("cpu", "mem", "swap", "gpu", "vram", "cpu_temp", "gpu_temp",
           "net_rx", "net_tx", "disk_r", "disk_w")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS samples (
    ts REAL PRIMARY KEY,
    {", ".join(c + " REAL" for c in COLUMNS)}
);
CREATE TABLE IF NOT EXISTS events (
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS bench_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    cpu_name TEXT,
    results TEXT NOT NULL      -- json, test key -> score
);
"""

COMMIT_EVERY = 15      # samples
PRUNE_EVERY = 3600     # seconds


def row_from_snapshot(s):
    g = s.gpu
    return (
        s.ts, s.cpu, s.mem_pct, s.swap_pct,
        g.util if g else None, g.mem_pct if g else None,
        s.cpu_temp, g.temp if g else None,
        s.net_rx, s.net_tx, s.disk_read, s.disk_write,
    )


class HistoryStore:
    def __init__(self, path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._pending = 0
        self._last_prune = 0.0

    # -- writing -----------------------------------------------------------

    def record(self, snap, retention_days=None):
        placeholders = ",".join("?" * (len(COLUMNS) + 1))
        self.db.execute(f"INSERT OR REPLACE INTO samples VALUES ({placeholders})",
                        row_from_snapshot(snap))
        self._pending += 1
        if self._pending >= COMMIT_EVERY:
            self.flush()
        if retention_days and time.time() - self._last_prune > PRUNE_EVERY:
            self.prune(retention_days)

    def flush(self):
        if self._pending:
            self.db.commit()
            self._pending = 0

    def prune(self, retention_days):
        self._last_prune = time.time()
        cutoff = time.time() - retention_days * 86400
        self.db.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
        self.db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        self.db.commit()

    def log_event(self, kind, message, ts=None):
        self.db.execute("INSERT INTO events VALUES (?, ?, ?)", (ts or time.time(), kind, message))
        self.db.commit()

    def save_bench(self, cpu_name, results_json):
        cur = self.db.execute("INSERT INTO bench_runs (ts, cpu_name, results) VALUES (?, ?, ?)",
                              (time.time(), cpu_name, results_json))
        self.db.commit()
        return cur.lastrowid

    def clear(self):
        self.db.execute("DELETE FROM samples")
        self.db.execute("DELETE FROM events")
        self.db.commit()
        self.db.execute("VACUUM")

    # -- reading -----------------------------------------------------------

    def events(self, limit=200):
        return self.db.execute("SELECT ts, kind, message FROM events ORDER BY ts DESC LIMIT ?",
                               (limit,)).fetchall()

    def bench_runs(self, limit=50):
        return self.db.execute(
            "SELECT id, ts, cpu_name, results FROM bench_runs ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()

    def export_csv(self, path, start, end):
        cur = self.db.execute(
            f"SELECT ts, {', '.join(COLUMNS)} FROM samples WHERE ts BETWEEN ? AND ? ORDER BY ts",
            (start, end))
        n = 0
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(("time",) + COLUMNS)
            for row in cur:
                stamp = datetime.fromtimestamp(row[0]).isoformat(timespec="seconds")
                w.writerow((stamp,) + tuple("" if v is None else round(v, 3) for v in row[1:]))
                n += 1
        return n

    def close(self):
        try:
            self.flush()
            self.db.close()
        except sqlite3.Error:
            pass


def load_range(path, start, end, max_points=1200):
    """
    Everything the History page needs for one range, in a single pass over the
    table. Runs on a worker thread with its own short-lived connection.

    The old version bucketed the *requested* range, so with three minutes of
    data in a 7 day view every sample landed in one bucket and the charts drew
    a single invisible point. Now the range is clipped to where data actually
    starts, and lines are broken wherever the app wasn't running.
    """
    db = sqlite3.connect(str(path), timeout=5)
    try:
        first, last, count = db.execute(
            "SELECT MIN(ts), MAX(ts), COUNT(*) FROM samples WHERE ts BETWEEN ? AND ?",
            (start, end)).fetchone()
        if not count:
            return {"count": 0, "start": start, "end": end}

        lo = max(start, first)
        bucket = max(1.0, (end - lo) / max_points)
        aggs = ", ".join(f"COUNT({c}), AVG({c}), MIN({c}), MAX({c})" for c in COLUMNS)
        rows = db.execute(
            f"SELECT CAST(ts / ? AS INTEGER) * ? AS t, {aggs} FROM samples "
            f"WHERE ts BETWEEN ? AND ? GROUP BY t ORDER BY t",
            (bucket, bucket, lo, end)).fetchall()
    finally:
        db.close()

    # a gap is anything noticeably longer than one bucket (app closed, PC asleep)
    gap = max(bucket * 3, 15.0)
    ts, series = [], {c: [] for c in COLUMNS}
    prev = None
    for r in rows:
        if prev is not None and r[0] - prev > gap:
            ts.append(prev + bucket)
            for c in COLUMNS:
                series[c].append(None)
        ts.append(r[0])
        for i, c in enumerate(COLUMNS):
            series[c].append(r[2 + i * 4])
        prev = r[0]

    stats = {}
    for i, c in enumerate(COLUMNS):
        n_total = sum(r[1 + i * 4] for r in rows)
        if not n_total:
            stats[c] = (None, None, None)
            continue
        avg = sum(r[2 + i * 4] * r[1 + i * 4] for r in rows if r[1 + i * 4]) / n_total
        lo_v = min(r[3 + i * 4] for r in rows if r[1 + i * 4])
        hi_v = max(r[4 + i * 4] for r in rows if r[1 + i * 4])
        stats[c] = (lo_v, avg, hi_v)

    return {"count": count, "first": first, "last": last, "start": lo, "end": end,
            "bucket": bucket, "ts": ts, "series": series, "stats": stats}
