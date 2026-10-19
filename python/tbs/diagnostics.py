import importlib.metadata
import platform
import struct
import sys
from . import __version__
from .accelerators import hardware_report


def report():
    versions = {}
    for name in ["numpy", "scipy", "av", "pyarrow", "opencv-python", "PySide6", "ultralytics"]:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return dict(tbs=__version__, python=sys.version, executable=sys.executable,
                os=platform.platform(), bits=struct.calcsize("P")*8, packages=versions,
                accelerators=hardware_report())
