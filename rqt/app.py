import argparse
import getpass
import logging
import sys
from logging.handlers import RotatingFileHandler

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import APP_NAME, APP_SLUG, __version__
from .config import data_dir, load_settings
from .ui.main_window import MainWindow
from .ui.theme import BG, MUTED, app_icon, apply_theme
from .winapp import relaunch_detached, set_app_id, should_detach

INSTANCE_KEY = f"{APP_SLUG}-monitor-{getpass.getuser()}"


def log_path():
    return data_dir() / f"{APP_SLUG}.log"


def setup_logging(verbose):
    handlers = [RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if verbose and sys.stderr is not None:   # pythonw has no stderr at all
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        handlers=handlers)

    def excepthook(exc_type, exc, tb):
        # without a console these would vanish, so at least get them into the log
        logging.getLogger(APP_SLUG).error("unhandled exception", exc_info=(exc_type, exc, tb))
        if sys.stderr is not None:
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook


def hand_over_to_running_instance():
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if not sock.waitForConnected(400):
        return False
    sock.write(b"show")
    sock.flush()
    sock.waitForBytesWritten(400)
    sock.disconnectFromServer()
    return True


def listen_for_other_instances(win):
    QLocalServer.removeServer(INSTANCE_KEY)  # clears a stale socket after a crash (Linux/macOS)
    server = QLocalServer(win)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: (conn.readAll(), win.show_normal()))
            conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(on_connection)
    server.listen(INSTANCE_KEY)
    return server


def parse_args(argv):
    parser = argparse.ArgumentParser(prog=APP_SLUG, description=f"{APP_NAME}: a desktop hardware monitor")
    parser.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    parser.add_argument("-v", "--verbose", action="store_true", help="log to the console too")
    parser.add_argument("--attached", action="store_true",
                        help="stay attached to this terminal instead of detaching (Windows)")
    parser.add_argument("--screenshot", metavar="PNG",
                        help="save a screenshot of the window after a few seconds, then quit")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser.parse_known_args(argv)


def main(argv=None):
    args, qt_args = parse_args(argv)
    setup_logging(args.verbose)

    # screenshots need to stay in this process so we can wait for the file
    if should_detach(args) and not args.screenshot:
        passthrough = [a for a in ("--minimized", "--verbose") if getattr(args, a[2:])]
        if relaunch_detached(passthrough, log_path()):
            return 0

    log = logging.getLogger(APP_SLUG)
    log.info("%s %s starting", APP_NAME, __version__)
    set_app_id()

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_SLUG)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)  # the tray keeps us alive
    apply_theme(app)

    if not args.screenshot and hand_over_to_running_instance():
        log.info("already running, asked the other instance to show itself")
        return 0

    pg.setConfigOptions(antialias=True, background=BG, foreground=MUTED)

    win = MainWindow(load_settings())

    if args.screenshot:
        # give the charts a few seconds of data first
        win.show()
        QTimer.singleShot(6000, lambda: (win.save_screenshot(args.screenshot), win.quit()))
        return app.exec()

    win._instance_server = listen_for_other_instances(win)
    if not args.minimized:
        win.show()
    return app.exec()
