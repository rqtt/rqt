import os

import psutil
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QLineEdit,
                               QMenu, QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget)

from ..fmt import human_bytes
from .theme import DANGER, WARN
from . import theme
from .widgets import Card, PageHeader, set_text
from .. import APP_HTML

# (header, attribute, starting width)
COLUMNS = [
    ("Name", "name", 0),
    ("PID", "pid", 80),
    ("User", "user", 130),
    ("CPU", "cpu", 80),
    ("Memory", "rss", 100),
    ("Threads", "threads", 80),
    ("Status", "status", 100),
]
NUMERIC = {"pid", "cpu", "rss", "threads"}
SORT_ROLE = Qt.ItemDataRole.UserRole
RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class ProcessModel(QAbstractTableModel):
    """
    Updated in place: rows that died are removed, new ones appended and the
    rest just get a dataChanged. Resetting the whole model every poll (what
    the first version did) threw away the selection and scroll position and
    forced every column to be re-measured.
    """

    def __init__(self):
        super().__init__()
        self.rows = []

    def update(self, new_rows):
        fresh = {r.pid: r for r in new_rows}

        for i in range(len(self.rows) - 1, -1, -1):
            if self.rows[i].pid not in fresh:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self.rows[i]
                self.endRemoveRows()

        for i, r in enumerate(self.rows):
            self.rows[i] = fresh.pop(r.pid)
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMNS) - 1))

        if fresh:
            start = len(self.rows)
            self.beginInsertRows(QModelIndex(), start, start + len(fresh) - 1)
            self.rows.extend(fresh.values())
            self.endInsertRows()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][0]
        if role == Qt.ItemDataRole.TextAlignmentRole and COLUMNS[section][1] in NUMERIC:
            return RIGHT
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        row = self.rows[index.row()]
        attr = COLUMNS[index.column()][1]
        value = getattr(row, attr)

        if role == SORT_ROLE:
            return value.lower() if isinstance(value, str) else value
        if role == Qt.ItemDataRole.DisplayRole:
            if attr == "cpu":
                return f"{value:.1f}%"
            if attr == "rss":
                return human_bytes(value)
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and attr in NUMERIC:
            return RIGHT
        if role == Qt.ItemDataRole.ForegroundRole and attr == "cpu":
            if value >= 50:
                return QColor(DANGER)
            if value >= 15:
                return QColor(WARN)
        return None


class ProcessesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = ProcessModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setDynamicSortFilter(True)

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.view.setFont(theme.mono_font(9.5))  # htop-ish
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.view.verticalHeader().setDefaultSectionSize(26)
        hdr = self.view.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, (_h, _a, width) in enumerate(COLUMNS):
            if width:
                hdr.resizeSection(i, width)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.doubleClicked.connect(lambda _i: self._open_location(self._selected_pid()))

        self.summary = QLabel()
        self.summary.setObjectName("mono")
        self.search = QLineEdit()
        self.search.setPlaceholderText("filter: name, pid or user")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        end_btn = QPushButton("End task")
        end_btn.setObjectName("danger")
        end_btn.clicked.connect(lambda: self._end(kill=False))

        head = PageHeader("processes")
        head.add(self.summary, 1)
        head.add(self.search)
        head.add(end_btn)

        card = Card()
        card.body.setContentsMargins(4, 4, 4, 4)
        card.body.addWidget(self.view)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)
        lay.addWidget(head)
        lay.addWidget(card, 1)

    def on_processes(self, rows):
        self.model.update(rows)
        threads = sum(r.threads for r in rows)
        set_text(self.summary, f"{len(rows)} procs  ·  {threads:,} threads")

    def _selected_pid(self):
        idx = self.view.selectionModel().selectedRows()
        if not idx:
            return None
        src = self.proxy.mapToSource(idx[0])
        return self.model.rows[src.row()].pid

    def _menu(self, pos):
        pid = self._selected_pid()
        if pid is None:
            return
        menu = QMenu(self)
        menu.addAction("End task", lambda: self._end(kill=False))
        menu.addAction("Force kill", lambda: self._end(kill=True))
        menu.addSeparator()
        menu.addAction("Open file location", lambda: self._open_location(pid))
        menu.addAction("Copy PID", lambda: QGuiApplication.clipboard().setText(str(pid)))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _end(self, kill):
        pid = self._selected_pid()
        if pid is None:
            return
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except psutil.Error:
            return
        if pid == os.getpid():
            QMessageBox.information(self, self.window().windowTitle(),
                                    f"That's {APP_HTML} itself. Use Quit from the tray icon instead.")
            return
        verb = "Force kill" if kill else "End"
        answer = QMessageBox.question(self, f"{verb} task",
                                      f"{verb} {name} (PID {pid})?\nUnsaved work in it will be lost.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            proc.kill() if kill else proc.terminate()
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Access denied",
                                f"Windows won't let {APP_HTML} stop {name}. Run it as administrator to end system processes.")
        except psutil.NoSuchProcess:
            pass

    def _open_location(self, pid):
        if pid is None:
            return
        try:
            exe = psutil.Process(pid).exe()
        except psutil.Error:
            exe = ""
        if exe:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(exe)))
