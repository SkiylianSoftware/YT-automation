"""Auto-skip test files whose dependencies are not installed."""

from __future__ import annotations

import importlib.util
import sys

collect_ignore: list[str] = []

# calendar tests need google auth
if importlib.util.find_spec("googleapiclient") is None:
    collect_ignore.append("test_calendar.py")

# playlist tests need pyyoutube
if importlib.util.find_spec("pyyoutube") is None:
    collect_ignore.append("test_playlist_automation.py")
