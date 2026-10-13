#!/usr/bin/env python3
"""
Build a standalone r<q>t with PyInstaller:

    pip install pyinstaller
    python build.py            ->  dist/rqt/rqt.exe  (or dist/rqt/rqt on Linux/macOS)

The release workflow runs exactly this.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from rqt import __version__  # noqa: E402
from rqt.winapp import pyinstaller_args  # noqa: E402


def main():
    icon = os.path.join(ROOT, "assets", "icon.ico")
    args = pyinstaller_args(__version__, icon if os.path.exists(icon) else None,
                            dist=os.path.join(ROOT, "dist"), work=os.path.join(ROOT, "build"))
    print("PyInstaller", " ".join(args))
    return subprocess.call([sys.executable, "-m", "PyInstaller", *args])


if __name__ == "__main__":
    sys.exit(main())
