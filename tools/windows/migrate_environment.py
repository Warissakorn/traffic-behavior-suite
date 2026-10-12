"""Copy the legacy source environment into this project without downloading packages."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Run with Python 3.12: py -3.12 tools/windows/migrate_environment.py")
    key = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    source = Path(os.environ["LOCALAPPDATA"]) / "TrafficBehaviorSuite" / "environments" / ("gui-test-" + key)
    target = ROOT / ".venv"
    if target.exists():
        raise RuntimeError(f"Destination already exists: {target}")
    if not (source / "Scripts/python.exe").is_file():
        raise RuntimeError(f"Legacy environment not found: {source}")
    shutil.copytree(source, target)
    venv.EnvBuilder(with_pip=False).create(target)
    # Windows console launchers embed an absolute interpreter path. Rebuild them
    # from installed metadata so pip/tbs and dependency commands use this copy.
    subprocess.run([str(target / "Scripts/python.exe"), "-c", """
import importlib.metadata
import sys
from pathlib import Path
from pip._vendor.distlib.scripts import ScriptMaker
maker = ScriptMaker(None, str(Path(sys.executable).parent))
maker.executable = sys.executable
maker.clobber = True
maker.variants = {'', 'X', 'X.Y'}
for dist in importlib.metadata.distributions():
    for entry in dist.entry_points:
        if entry.group in ('console_scripts', 'gui_scripts'):
            maker.make(f'{entry.name} = {entry.value}', {'gui': entry.group == 'gui_scripts'})
"""], check=True)
    print(f"Environment copied to {target}; legacy copy retained at {source}")


if __name__ == "__main__":
    main()
