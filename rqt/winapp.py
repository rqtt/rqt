"""
Windows-specific glue: giving r<q>t its own identity in the taskbar and Task
Manager, a dark title bar, starting with Windows, and building a real rqt.exe.

When started as `python run.py` the process is python.exe, a child of
whatever launched it (VS Code, a terminal...). Task Manager files it under
that parent, and closing VS Code kills it. So on Windows we relaunch
ourselves under pythonw.exe, detached, and let the launcher exit.

To be listed as "r<q>t" (rather than "Python") in Task Manager it has to be
an actual exe with our own version info, which is what pyinstaller_args() is for.
"""
import ctypes
import os
import subprocess
import sys

from . import APP_FILE_NAME, APP_NAME, APP_SLUG

APP_ID = "teo.rqt.monitor"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
OLD_RUN_VALUES = ("Pulse",)

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NO_WINDOW = 0x08000000

IS_WINDOWS = sys.platform == "win32"
FROZEN = getattr(sys, "frozen", False)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(ROOT, "run.py")


def set_app_id():
    """Own taskbar button + icon instead of being lumped in with Python."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def style_title_bar(hwnd, caption_hex):
    """
    Dark title bar that blends into the tab strip, the way Windows Terminal
    looks. Windows 10 understands the dark-mode flag; Windows 11 also takes
    the exact caption colour. Older builds just ignore both.
    """
    if not IS_WINDOWS:
        return
    try:
        dwm = ctypes.windll.dwmapi
        hwnd = ctypes.c_void_p(int(hwnd))
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on pre-20H1 builds)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
        r, g, b = (int(caption_hex[i:i + 2], 16) for i in (1, 3, 5))
        colorref = ctypes.c_int(r | (g << 8) | (b << 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), ctypes.sizeof(colorref))  # caption
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(colorref), ctypes.sizeof(colorref))  # border
    except Exception:
        pass


def pythonw():
    path = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return path if os.path.exists(path) else None


def should_detach(args):
    return (IS_WINDOWS and not FROZEN and not args.attached
            and os.path.basename(sys.executable).lower() == "python.exe"
            and pythonw() is not None and os.path.exists(LAUNCHER))


def relaunch_detached(extra_args, log_path):
    """
    Returns True if a detached copy is now running (the caller should exit).
    If the copy dies within a few seconds we return False so the caller runs
    in this console instead, where the traceback is actually visible.
    """
    cmd = [pythonw(), LAUNCHER, "--attached", *extra_args]
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(cmd, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
                                close_fds=True, cwd=ROOT)
    except OSError:
        # some job objects (certain terminals) forbid breakaway
        try:
            proc = subprocess.Popen(cmd, creationflags=flags, close_fds=True, cwd=ROOT)
        except OSError:
            return False

    try:
        code = proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        print(f"{APP_NAME} is running. You can close this terminal (or VS Code) now.")
        return True

    if code == 0:
        print(f"{APP_NAME} was already running, brought it to the front.")
        return True
    print(f"{APP_NAME} closed right after starting (exit code {code}).")
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-15:]
        print("Last lines of the log:\n" + "".join(tail))
    except OSError:
        pass
    print("Running it here instead so the error is visible...")
    return False


# -- autostart -----------------------------------------------------------------

def launch_command(minimized=True):
    exe = installed_exe()
    if FROZEN:
        cmd = f'"{sys.executable}"'
    elif exe:
        cmd = f'"{exe}"'
    else:
        cmd = f'"{pythonw() or sys.executable}" "{LAUNCHER}" --attached'
    return cmd + (" --minimized" if minimized else "")


def autostart_enabled():
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_SLUG)
            return True
    except OSError:
        return False


def set_autostart(enabled):
    if not IS_WINDOWS:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for old in OLD_RUN_VALUES:  # entries left behind by the old name
            try:
                winreg.DeleteValue(key, old)
            except OSError:
                pass
        if enabled:
            winreg.SetValueEx(key, APP_SLUG, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_SLUG)
            except OSError:
                pass


# -- building rqt.exe ----------------------------------------------------------

def install_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_SLUG, "app")


def installed_exe():
    path = os.path.join(install_dir(), APP_SLUG, f"{APP_SLUG}.exe")
    return path if os.path.exists(path) else None


VERSION_FILE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v}, 0), prodvers=({v}, 0), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'teo'),
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{dotted}'),
      StringStruct('InternalName', '{slug}'),
      StringStruct('OriginalFilename', '{slug}.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{dotted}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def pyinstaller_args(version, icon_path, dist, work):
    """Arguments for `python -m PyInstaller ...`, shared by the app and build.py."""
    os.makedirs(work, exist_ok=True)
    version_file = os.path.join(work, "version.txt")
    parts = (version.split(".") + ["0", "0", "0"])[:3]
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(VERSION_FILE.format(v=", ".join(parts), dotted=".".join(parts),
                                    name=APP_NAME, slug=APP_SLUG))
    args = ["--noconfirm", "--clean", "--windowed", "--onedir",
            "--name", APP_SLUG, "--version-file", version_file,
            "--distpath", dist, "--workpath", work, "--specpath", work]
    if icon_path:
        args += ["--icon", icon_path]
    return args + [LAUNCHER]


def build_exe_commands(version, icon_path):
    """[(label, argv)] for the in-app installer, run one after another."""
    work = os.path.join(os.path.dirname(install_dir()), "build")
    # python.exe rather than pythonw so pip/pyinstaller output can be read
    python = os.path.join(os.path.dirname(sys.executable), "python.exe")
    if not os.path.exists(python):
        python = sys.executable
    pyinstaller = [python, "-m", "PyInstaller", *pyinstaller_args(version, icon_path, install_dir(), work)]
    return [
        ("Installing PyInstaller", [python, "-m", "pip", "install", "--disable-pip-version-check", "pyinstaller"]),
        (f"Building {APP_SLUG}.exe (takes a minute or two)", pyinstaller),
    ]


def create_shortcuts(exe):
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    try:
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY
        desktop = buf.value or desktop
    except Exception:
        pass
    start_menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")

    made = []
    for folder in (desktop, start_menu):
        if not folder or not os.path.isdir(folder):
            continue
        for old in ("Pulse.lnk",):  # shortcuts from before the rename
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        link = os.path.join(folder, f"{APP_FILE_NAME}.lnk")
        ps = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
            "$s.TargetPath='{exe}';$s.WorkingDirectory='{wd}';$s.IconLocation='{exe},0';"
            "$s.Description='{desc}';$s.Save()"
        ).format(link=link.replace("'", "''"), exe=exe.replace("'", "''"),
                 wd=os.path.dirname(exe).replace("'", "''"), desc=f"{APP_NAME} hardware monitor")
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                                capture_output=True, creationflags=CREATE_NO_WINDOW)
        if result.returncode == 0:
            made.append(link)
    return made
