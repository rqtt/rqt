from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QPushButton, QSpinBox, QTableWidget,
                               QVBoxLayout, QWidget)

from ..alerts import METRICS, AlertRule
from .widgets import Card, PageHeader


class AlertsPage(QWidget):
    rules_changed = Signal(list)   # list[dict]

    def __init__(self, settings, store, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.store = store
        self._loading = False

        head = PageHeader("alerts")
        head.add_stretch()
        hint = QLabel("Get a notification when a reading stays past a limit. A rule re-arms once the "
                      "value drops back, and never repeats within 5 minutes.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["On", "Metric", "", "Threshold", "For (s)"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (0, 2, 3, 4):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        add = QPushButton("Add rule")
        add.clicked.connect(lambda: self._add_row(AlertRule()) or self._emit())
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)

        self.log = QListWidget()
        clear = QPushButton("Clear")
        clear.clicked.connect(self.log.clear)

        rules_card = Card("RULES")
        rules_card.header.addWidget(add)
        rules_card.header.addWidget(remove)
        rules_card.body.addWidget(self.table)

        log_card = Card("RECENT ALERTS")
        log_card.header.addWidget(clear)
        log_card.body.addWidget(self.log)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(12)
        lay.addWidget(head)
        lay.addWidget(hint)
        lay.addWidget(rules_card, 3)
        lay.addWidget(log_card, 2)

        self.load_rules(settings.alerts)
        for ts, kind, msg in reversed(store.events(200)):
            self._log_line(ts, kind, msg)

    def load_rules(self, rules):
        self._loading = True
        self.table.setRowCount(0)
        for r in rules:
            self._add_row(AlertRule.from_dict(r))
        self._loading = False

    def _add_row(self, rule):
        row = self.table.rowCount()
        self.table.insertRow(row)

        on = QCheckBox()
        on.setChecked(rule.enabled)
        on.toggled.connect(self._emit)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.addWidget(on)
        self.table.setCellWidget(row, 0, holder)

        metric = QComboBox()
        for key, (label, *_rest) in METRICS.items():
            metric.addItem(label, key)
        metric.setCurrentIndex(max(0, metric.findData(rule.metric)))
        metric.currentIndexChanged.connect(self._emit)
        self.table.setCellWidget(row, 1, metric)

        op = QComboBox()
        op.addItems([">", "<"])
        op.setCurrentText(rule.op)
        op.currentIndexChanged.connect(self._emit)
        self.table.setCellWidget(row, 2, op)

        thr = QDoubleSpinBox()
        thr.setRange(-1000, 100000)
        thr.setDecimals(1)
        thr.setValue(rule.threshold)
        thr.valueChanged.connect(self._emit)
        self.table.setCellWidget(row, 3, thr)

        sus = QSpinBox()
        sus.setRange(0, 3600)
        sus.setValue(int(rule.sustain))
        sus.valueChanged.connect(self._emit)
        self.table.setCellWidget(row, 4, sus)

    def _remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        for r in rows:
            self.table.removeRow(r)
        self._emit()

    def rules(self):
        out = []
        for r in range(self.table.rowCount()):
            on = self.table.cellWidget(r, 0).findChild(QCheckBox)
            out.append(AlertRule(
                metric=self.table.cellWidget(r, 1).currentData(),
                op=self.table.cellWidget(r, 2).currentText(),
                threshold=self.table.cellWidget(r, 3).value(),
                sustain=self.table.cellWidget(r, 4).value(),
                enabled=on.isChecked(),
            ).to_dict())
        return out

    def _emit(self, *_):
        if not self._loading:
            self.rules_changed.emit(self.rules())

    def add_event(self, ts, kind, message):
        self._log_line(ts, kind, message)

    def _log_line(self, ts, kind, message):
        stamp = datetime.fromtimestamp(ts).strftime("%d %b %H:%M:%S")
        self.log.insertItem(0, f"{stamp}   [{kind}]   {message}")
        while self.log.count() > 500:
            self.log.takeItem(self.log.count() - 1)
