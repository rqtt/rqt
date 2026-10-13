"""Lets `python -m rqt` work too."""
import sys

from rqt._bootstrap import ensure_dependencies

ensure_dependencies()

from rqt.app import main  # noqa: E402

sys.exit(main())
