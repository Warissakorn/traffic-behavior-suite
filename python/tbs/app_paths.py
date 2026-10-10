"""Writable user data, separate from the source or frozen bundle."""
import os
from pathlib import Path


def data_dir():
    base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or (Path.home()/".local/share"))
    path = base/"TrafficBehaviorSuite"
    path.mkdir(parents=True, exist_ok=True)
    return path
