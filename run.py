#!/usr/bin/env python3
"""Start r<q>t. Installs its own dependencies on the first run."""
import sys

from rqt._bootstrap import ensure_dependencies

ensure_dependencies()

from rqt.app import main  # noqa: E402  (needs the dependencies above)

if __name__ == "__main__":
    sys.exit(main())
