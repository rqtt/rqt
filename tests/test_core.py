"""
Tests for the parts of r<q>t that don't need a display: sampling, history,
alerts, settings and the benchmark. Run with:

    python -m unittest discover -s tests -v
"""
import csv
import os
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rqt import bench, config, fmt  # noqa: E402
from rqt.alerts import AlertEngine, AlertRule  # noqa: E402
from rqt.history import HistoryStore, load_range  # noqa: E402
from rqt.procs import ProcessTable  # noqa: E402
from rqt.sensors import Sampler  # noqa: E402


def fake_snapshot(ts, cpu=10.0, mem=40.0, cpu_temp=None, gpu=None, free=50.0):
    return NS(ts=ts, cpu=cpu, mem_pct=mem, swap_pct=0.0, gpu=gpu, cpu_temp=cpu_temp,
              net_rx=1e5, net_tx=1e4, disk_read=0.0, disk_write=0.0, root_free_pct=free)


class FormatTests(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(fmt.human_bytes(512), "512 B")
        self.assertEqual(fmt.human_bytes(1536), "1.5 KB")
        self.assertEqual(fmt.human_bytes(3 * 1024 ** 3), "3.0 GB")
        self.assertEqual(fmt.human_bytes(None), fmt.DASH)

    def test_temperature_units(self):
        self.assertEqual(fmt.fmt_temp(100, "C"), "100°C")
        self.assertEqual(fmt.fmt_temp(100, "F"), "212°F")
        self.assertIsNone(fmt.to_unit(None, "F"))


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "h.db")
        self.store = HistoryStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_long_range_with_little_data_still_draws(self):
        # The bug from v0.4: a few minutes of data in a 7 day view collapsed
        # into a single bucket and the charts came out empty.
        now = time.time()
        for t in list(range(-900, -720)) + list(range(-120, 0)):
            self.store.record(fake_snapshot(now + t, cpu=20 + (t % 7)))
        self.store.flush()

        r = load_range(self.path, now - 7 * 86400, now)
        self.assertEqual(r["count"], 300)
        self.assertGreater(len(r["ts"]), 250)
        self.assertAlmostEqual(r["start"], now - 900, delta=1)
        # the 10 minute gap is broken with exactly one None
        self.assertEqual(r["series"]["cpu"].count(None), 1)
        lo, avg, hi = r["stats"]["cpu"]
        self.assertEqual((lo, hi), (20, 26))

    def test_empty_range(self):
        r = load_range(self.path, 0, 10)
        self.assertEqual(r["count"], 0)

    def test_csv_export_and_prune(self):
        now = time.time()
        self.store.record(fake_snapshot(now - 30 * 86400))
        self.store.record(fake_snapshot(now))
        self.store.flush()
        out = os.path.join(self.tmp.name, "x.csv")
        self.assertEqual(self.store.export_csv(out, 0, now + 1), 2)
        with open(out, newline="") as f:
            self.assertEqual(next(csv.reader(f))[0], "time")

        self.store.prune(retention_days=7)
        self.assertEqual(load_range(self.path, 0, now + 1)["count"], 1)


class AlertTests(unittest.TestCase):
    def test_sustain_cooldown_and_rearm(self):
        engine = AlertEngine([AlertRule("cpu", ">", 90, sustain=10)])
        clock = [1000.0]
        with mock.patch("rqt.alerts.time.monotonic", lambda: clock[0]):
            self.assertEqual(engine.check(fake_snapshot(0, cpu=95)), [])   # just started
            clock[0] += 11
            self.assertEqual(len(engine.check(fake_snapshot(0, cpu=95))), 1)
            clock[0] += 1
            self.assertEqual(engine.check(fake_snapshot(0, cpu=95)), [])   # already fired

            clock[0] += 1
            engine.check(fake_snapshot(0, cpu=10))                         # re-arms
            clock[0] += 20
            engine.check(fake_snapshot(0, cpu=95))
            clock[0] += 11
            self.assertEqual(engine.check(fake_snapshot(0, cpu=95)), [])   # still in cooldown

            clock[0] += 400
            engine.check(fake_snapshot(0, cpu=10))
            engine.check(fake_snapshot(0, cpu=95))
            clock[0] += 11
            self.assertEqual(len(engine.check(fake_snapshot(0, cpu=95))), 1)

    def test_temperature_rules_follow_unit(self):
        engine = AlertEngine([AlertRule("cpu_temp", ">", 180, sustain=0)], temp_unit="F")
        self.assertEqual(len(engine.check(fake_snapshot(0, cpu_temp=90))), 1)  # 194°F

    def test_missing_reading_never_fires(self):
        engine = AlertEngine([AlertRule("gpu_temp", ">", 10, sustain=0)])
        self.assertEqual(engine.check(fake_snapshot(0, gpu=None)), [])


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_old_keys(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(config, "_base_dir", lambda: config.Path(tmp)), \
                mock.patch.object(config, "_checked_old", True):
            s = config.Settings(interval_ms=500)
            s.overlay.items = ["cpu"]
            config.save_settings(s)
            back = config.load_settings()
            self.assertEqual(back.interval_ms, 500)
            self.assertEqual(back.overlay.items, ["cpu"])

            # unknown keys from older/newer versions are ignored, not fatal
            config.config_path().write_text('{"interval_ms": 2000, "something_old": 1}')
            self.assertEqual(config.load_settings().interval_ms, 2000)


class LiveSystemTests(unittest.TestCase):
    def test_sampler(self):
        sampler = Sampler()
        time.sleep(0.3)
        s = sampler.sample()
        sampler.close()
        self.assertTrue(0 <= s.cpu <= 100)
        self.assertTrue(0 < s.mem_pct < 100)
        self.assertGreater(s.mem_total, 0)
        self.assertGreaterEqual(s.net_rx, 0)

    def test_process_table_sees_us(self):
        rows = ProcessTable().poll()
        self.assertIn(os.getpid(), {r.pid for r in rows})

    def test_benchmark_runs(self):
        results, _notes = bench.run_all(lambda *_: None, threading.Event(),
                                        disk_mb=8, seconds=0.2)
        for key, _label, _unit in bench.TESTS:
            self.assertGreater(results[key], 0, key)


if __name__ == "__main__":
    unittest.main()
