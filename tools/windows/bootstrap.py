"""Source launchers use a per-user venv and never elevate or change shell policy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData/Local"))/"TrafficBehaviorSuite"
KEY = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
ENV = BASE/"environments"/("gui-test-"+KEY)
PYTHON = ENV/"Scripts/python.exe"
MARKER = ENV/"tbs-install.json"


def fingerprint():
    return hashlib.sha256((ROOT/"pyproject.toml").read_bytes()+(ROOT/"tools/windows/constraints.txt").read_bytes()).hexdigest()


def ready():
    if not PYTHON.is_file() or not MARKER.is_file():
        return False
    try:
        marker=json.loads(MARKER.read_text())
        return marker.get("source") == str(ROOT) and marker.get("fingerprint")==fingerprint()
    except (OSError,ValueError):
        return False


def setup(detection=False):
    if sys.version_info[:2] != (3,12) or struct.calcsize("P")*8 != 64:
        raise RuntimeError("Setup needs Python 3.12 x64. Install it, then run Setup-Windows.cmd again.")
    ENV.parent.mkdir(parents=True,exist_ok=True)
    MARKER.unlink(missing_ok=True)
    if not PYTHON.is_file():
        venv.EnvBuilder(with_pip=True).create(ENV)
    profile = "gui,detect" if detection else "gui"
    subprocess.run([str(PYTHON),"-m","pip","install","--upgrade","pip"],check=True)
    subprocess.run([str(PYTHON),"-m","pip","install","-e",f"{ROOT}[{profile}]",
                    "-c",str(ROOT/"tools/windows/constraints.txt")],check=True)
    subprocess.run([str(PYTHON),"-c","from PySide6.QtWidgets import QApplication; import av, pyarrow, cv2"],check=True)
    MARKER.write_text(json.dumps({"source":str(ROOT),"profile":profile,"fingerprint":fingerprint()}),encoding="utf-8")
    print(f"Setup OK. Environment: {ENV}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action",choices=["setup","launch","test"])
    parser.add_argument("--detection",action="store_true")
    parser.add_argument("--debug",action="store_true")
    args = parser.parse_args()
    try:
        if args.action=="setup":
            setup(args.detection)
            return 0
        if not ready():
            raise RuntimeError("Environment is missing/incomplete. Run Setup-Windows.cmd first.")
        if args.action=="test":
            subprocess.run([str(PYTHON),"-m","tbs","diagnostics"],check=True)
            subprocess.run([str(PYTHON),"-m","tbs","demo","--output",str(BASE/"windows-test")],check=True)
            subprocess.run([str(PYTHON),"-m","tbs","gui","--smoke"],check=True)
            print("Windows source smoke PASS")
            return 0
        if args.debug:
            return subprocess.call([str(PYTHON),"-u","-m","tbs","gui"],cwd=ROOT)
        logdir = BASE/"logs"
        logdir.mkdir(parents=True,exist_ok=True)
        with (logdir/"startup.log").open("a",encoding="utf-8") as log:
            subprocess.Popen([str(ENV/"Scripts/pythonw.exe"),"-m","tbs","gui"],cwd=ROOT,
                             stdout=log,stderr=log,stdin=subprocess.DEVNULL)
        return 0
    except (OSError,RuntimeError,subprocess.CalledProcessError) as exc:
        print(f"TBS: {exc}",file=sys.stderr)
        print(f"Diagnostics/logs: {BASE}",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
