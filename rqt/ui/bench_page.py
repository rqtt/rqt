import json
import threading
from datetime import datetime

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import bench
from ..fmt import to_unit
from ..sensors import cpu_name
from .theme import COLORS
from .widgets import AreaChart, Card, PageHeader


class BenchThread(QThread):
    progress = Signal(float, str)
    finished_ok = Signal(dict, list)
    failed = Signal(str)

    def __init__(self, mode, stress_seconds=60):
        super().__init__()
        self.mode = mode
        self.stress_seconds = stress_seconds
        self.stop_flag = threading.Event()

    def run(self):
        report = lambda frac, msg: self.progress.emit(frac, msg)  # noqa: E731
        try:
            if self.mode == "stress":
                bench.stress(self.stress_seconds, self.stop_flag, report)
                self.finished_ok.emit({}, [])
            else:
                results, notes = bench.run_all(report, self.stop_flag)
                self.finished_ok.emit(results, notes)
        except bench.Cancelled:
            self.failed.emit("Cancelled")
        except Exception as e:
            self.failed.emit(str(e))


class BenchPage(QWidget):
    def __init__(self, store, settings, parent=None):
        super().__init__(parent)
        self.store = store
        self.settings = settings
        self.thread = None

        head = PageHeader("benchmark")
        head.add_stretch()
        hint = QLabel("Repeatable CPU, memory and disk numbers for this machine. Close heavy apps first. "
                      "The stress test pins every core so you can watch clocks and temperatures.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        self.run_btn = QPushButton("Run benchmark")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(lambda: self._start("bench"))
        self.stress_btn = QPushButton("Stress test")
        self.stress_btn.clicked.connect(lambda: self._start("stress"))
        self.stress_len = QSpinBox()
        self.stress_len.setRange(10, 3600)
        self.stress_len.setValue(120)
        self.stress_len.setSuffix(" s")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)

        btns = QHBoxLayout()
        btns.addWidget(self.run_btn)
        btns.addSpacing(16)
        btns.addWidget(self.stress_btn)
        btns.addWidget(self.stress_len)
        btns.addWidget(self.stop_btn)
        btns.addStretch(1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.status = QLabel("Idle")
        self.status.setObjectName("muted")

        # temperature shares the 0-110 scale with load; close enough to read both at a glance
        self.graph = AreaChart(180, y_max=110, fmt=lambda v: f"{v:.0f}")
        self.graph.add_series("cpu", COLORS["cpu"])
        self.graph.add_series("temp", COLORS["cpu_temp"], fill=False, width=2)
        self.graph.setMinimumHeight(150)

        self.results = QTableWidget(len(bench.TESTS), 4)
        self.results.setHorizontalHeaderLabels(["Test", "Result", "Previous run", "Change"])
        self.results.verticalHeader().hide()
        self.results.setShowGrid(False)
        self.results.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (_key, label, _unit) in enumerate(bench.TESTS):
            self.results.setItem(row, 0, QTableWidgetItem(label))

        self.past = QTableWidget(0, 3)
        self.past.setHorizontalHeaderLabels(["When", "CPU", "Multi-thread SHA-256"])
        self.past.verticalHeader().hide()
        self.past.setShowGrid(False)
        self.past.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.past.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        live = Card("cpu load % and temperature during the run")
        live.header.addWidget(self.status)
        live.body.addWidget(self.bar)
        live.body.addWidget(self.graph, 1)

        results = Card("RESULTS")
        results.body.addWidget(self.results)
        past = Card("PAST RUNS")
        past.body.addWidget(self.past)
        tables = QHBoxLayout()
        tables.setSpacing(12)
        tables.addWidget(results, 3)
        tables.addWidget(past, 2)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(12)
        lay.addWidget(head)
        lay.addWidget(hint)
        lay.addLayout(btns)
        lay.addWidget(live, 2)
        lay.addLayout(tables, 3)

        self._load_past()

    def on_snapshot(self, s):
        self.graph.push(s.mono, {"cpu": s.cpu, "temp": to_unit(s.cpu_temp, self.settings.temp_unit)})

    def _start(self, mode):
        if self.thread and self.thread.isRunning():
            return
        self.thread = BenchThread(mode, self.stress_len.value())
        self.thread.progress.connect(self._progress)
        self.thread.finished_ok.connect(self._done)
        self.thread.failed.connect(self._failed)
        self.thread.finished.connect(lambda: self._set_running(False))
        self._set_running(True)
        self.thread.start()

    def _stop(self):
        if self.thread:
            self.thread.stop_flag.set()

    def _set_running(self, running):
        self.run_btn.setEnabled(not running)
        self.stress_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def _progress(self, frac, msg):
        self.bar.setValue(int(frac * 1000))
        self.status.setText(msg)

    def _failed(self, msg):
        self.status.setText(msg)
        self.bar.setValue(0)

    def _done(self, results, notes):
        self.bar.setValue(1000)
        if not results:  # stress test
            self.status.setText("Stress test finished")
            return

        prev = self._previous_results()
        self.store.save_bench(cpu_name(), json.dumps(results))
        for row, (key, _label, unit) in enumerate(bench.TESTS):
            value = results.get(key)
            old = prev.get(key)
            self.results.setItem(row, 1, QTableWidgetItem(f"{value:,.1f} {unit}" if value else "–"))
            self.results.setItem(row, 2, QTableWidgetItem(f"{old:,.1f} {unit}" if old else "–"))
            change = QTableWidgetItem("")
            if value and old:
                delta = (value - old) / old * 100
                change.setText(f"{delta:+.1f}%")
                # anything inside ±3% is basically noise
                if abs(delta) >= 3:
                    change.setForeground(QColor("#46d18c" if delta > 0 else "#ff5d6c"))
            self.results.setItem(row, 3, change)
        self.status.setText("Done. " + " ".join(notes))
        self._load_past()

    def _previous_results(self):
        runs = self.store.bench_runs(1)
        return json.loads(runs[0][3]) if runs else {}

    def _load_past(self):
        runs = self.store.bench_runs(50)
        self.past.setRowCount(len(runs))
        for i, (_id, ts, cpu, res) in enumerate(runs):
            score = json.loads(res).get("hash_nt")
            self.past.setItem(i, 0, QTableWidgetItem(datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")))
            self.past.setItem(i, 1, QTableWidgetItem(cpu or ""))
            self.past.setItem(i, 2, QTableWidgetItem(f"{score:,.0f} MB/s" if score else "–"))

    def shutdown(self):
        if self.thread and self.thread.isRunning():
            self.thread.stop_flag.set()
            self.thread.wait(5000)
