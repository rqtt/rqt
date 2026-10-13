import logging
import threading
import time

from PySide6.QtCore import QThread, Signal

from .history import HistoryStore
from .procs import ProcessTable
from .sensors import Sampler

log = logging.getLogger(__name__)

PROCESS_EVERY = 2.0  # seconds


class MonitorThread(QThread):
    snapshot = Signal(object)
    processes = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path, interval_ms=1000, history=True, retention_days=14):
        super().__init__()
        self.db_path = db_path
        self.interval = interval_ms / 1000
        self.history_enabled = history
        self.retention_days = retention_days
        self.want_processes = False   # only poll while the Processes tab is open
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()
        self.wait(3000)

    def run(self):
        try:
            sampler = Sampler()
        except Exception as e:
            log.exception("sampler init failed")
            self.failed.emit(str(e))
            return

        procs = ProcessTable()
        store = None
        last_procs = 0.0

        while not self._stop.is_set():
            started = time.monotonic()
            try:
                snap = sampler.sample()
            except Exception:
                log.exception("sample failed")
                self._stop.wait(self.interval)
                continue

            self.snapshot.emit(snap)

            if self.history_enabled:
                try:
                    if store is None:
                        store = HistoryStore(self.db_path)
                    store.record(snap, self.retention_days)
                except Exception:
                    log.exception("history write failed")
            elif store is not None:
                store.close()
                store = None

            if self.want_processes and started - last_procs >= PROCESS_EVERY:
                last_procs = started
                try:
                    self.processes.emit(procs.poll())
                except Exception:
                    log.exception("process poll failed")

            elapsed = time.monotonic() - started
            self._stop.wait(max(0.05, self.interval - elapsed))

        if store:
            store.close()
        sampler.close()
