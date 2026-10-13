# Contributing to r&lt;q&gt;t

Thanks for taking a look. Small fixes don't need any discussion: just open a
pull request. For bigger changes (a new tab, a new sensor backend) please open
an issue first so we can agree on the shape of it.

## Setting up

```bash
git clone https://github.com/rqtt/rqt.git
cd rqt
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python run.py --attached -v
```

`--attached` keeps the app in your terminal on Windows (normally it detaches),
and `-v` prints the log as it goes.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover everything outside `rqt/ui/`, so they run without a display
and on CI. If you touch `history.py`, `alerts.py`, `sensors.py` or `bench.py`,
add or update a test.

## How the code is split

- **`rqt/` (top level)** has no Qt imports at all. Sampling, history, alerts
  and the benchmark are all plain Python, so they're easy to test and reuse.
- **`rqt/ui/`** is the Qt side. Each tab is its own `*_page.py`, the reusable
  bits (cards, the rolling `AreaChart`, the page header) live in `widgets.py`,
  and every colour and font is in `theme.py`.
- **`rqt/worker.py`** is the only place that runs on a background thread. It
  emits a `Snapshot` once per tick, and the window hands it to whichever tab
  is visible.

A few habits worth keeping:

- Don't repaint what can't be seen. Pages only update when they're on screen.
- Prefer `set_text()` from `widgets.py` over `QLabel.setText` for anything
  updated every tick, since it skips no-op relayouts.
- Keep new colours in `theme.COLORS` so the charts, overlay and history agree.

## Adding a GPU or sensor backend

Write a class in `gpu.py` with `name`, `read(lhm_rows) -> list[GpuReading]`
and `close()`, then register it in `detect_gpu_backends()`. Raise from
`__init__` if the hardware isn't there, and it will simply be skipped.

## Releases

Bump `__version__` in `rqt/__init__.py`, add an entry to `CHANGELOG.md`, then
tag the commit (`git tag v0.7.0 && git push --tags`). The release workflow
builds the Windows zip and attaches it to the release.
