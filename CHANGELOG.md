# Changelog

## 0.6.0

- Renamed from Pulse to **r&lt;q&gt;t**, with a new icon. Existing settings
  and history move over automatically on the first start.
- New look modelled on Windows Terminal: tabs in a strip that blends into a
  dark title bar, Cascadia for numbers, and prompt-style page titles.
- Keyboard shortcuts: Ctrl+1…7 and Ctrl+Tab.
- `--screenshot` flag for README images.
- Proper repo layout: `run.py`, `python -m rqt`, `pip install .`, tests,
  CI, and a release workflow that builds the Windows exe.

## 0.5.0

- Fixed the history tab showing empty charts for 24 h / 7 d / 30 d ranges.
- Dashboard redrawn with lightweight hand-painted charts, which makes it much
  less laggy.
- The process list updates in place instead of being rebuilt every poll.
- Sensors tab, hover readout on history charts, and a single-instance guard.
- On Windows the app detaches from the terminal, gets its own taskbar
  identity, can start with Windows, and can build itself into an exe.

## 0.4.0

- First version: dashboard, processes, history, alerts, benchmark, overlay.
