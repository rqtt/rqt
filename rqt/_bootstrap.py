"""
First-run dependency check. Imported before anything that needs Qt, so a
fresh clone works with just `python run.py`, no manual pip step.
"""
import importlib
import importlib.util
import subprocess
import sys

REQUIRED = {"PySide6": "PySide6", "pyqtgraph": "pyqtgraph", "psutil": "psutil", "numpy": "numpy"}
OPTIONAL = {"pynvml": "nvidia-ml-py"}  # NVIDIA stats, harmless without an NVIDIA card
if sys.platform == "win32":
    OPTIONAL.update({"wmi": "WMI", "pythoncom": "pywin32"})


def _pip(packages):
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    # plain install first, then --user for setups where site-packages is read-only
    for extra in ([], ["--user"]):
        if subprocess.call(base + extra + packages) == 0:
            return True
    return False


def ensure_dependencies():
    if getattr(sys, "frozen", False):
        return  # inside the built exe everything is bundled already
    if sys.version_info < (3, 10):
        sys.exit(f"r<q>t needs Python 3.10 or newer, this is {sys.version.split()[0]}")

    missing = [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        return
    print(f"First run: installing {', '.join(missing)} (this can take a minute)...", flush=True)
    if not _pip(missing):
        sys.exit("Couldn't install dependencies. Try:\n"
                 f"  {sys.executable} -m pip install -r requirements.txt")
    # extras get exactly one attempt, on that first run, so a failed optional
    # install never slows down later starts
    for mod, pkg in OPTIONAL.items():
        if importlib.util.find_spec(mod) is None:
            _pip([pkg])
    importlib.invalidate_caches()
