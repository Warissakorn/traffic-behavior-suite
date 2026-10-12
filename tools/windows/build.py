"""Build two Windows executables sharing one-folder runtime dependencies."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from importlib.metadata import version

ROOT=Path(__file__).resolve().parents[2]


def main():
    if sys.platform != "win32":
        raise RuntimeError("Portable Windows builds must run on Windows")
    for name,entry in [("TBSWorker","worker_entry.py"),("TBS","gui_entry.py")]:
        command=[sys.executable,"-m","PyInstaller","--noconfirm","--clean","--onedir","--name",name,
                 "--distpath",str(ROOT/"dist"),"--workpath",str(ROOT/"build"/name),
                 "--specpath",str(ROOT/"build"),"--paths",str(ROOT/"python"),
                 "--collect-data","tbs","--collect-all","av","--collect-all","pyarrow",
                 "--hidden-import","scipy.signal","--hidden-import","tbs.worker",
                 "--hidden-import","tbs.detection",
                 "--hidden-import","tbs.video_test",
                 "--exclude-module","PySide6.QtWebEngineCore","--exclude-module","PySide6.QtWebEngineWidgets",
                 "--exclude-module","PySide6.QtPdf","--exclude-module","tkinter"]
        if name=="TBS":
            command += ["--windowed"]
        command += [str(ROOT/"tools/windows"/entry)]
        subprocess.run(command,check=True,cwd=ROOT)
    target=ROOT/"dist/TBS"
    worker=ROOT/"dist/TBSWorker"
    shutil.copyfile(worker/"TBSWorker.exe",target/"TBSWorker.exe")
    shutil.copytree(worker/"_internal",target/"_internal",dirs_exist_ok=True)
    shutil.copyfile(ROOT/"docs/WINDOWS_TEST.md",target/"WINDOWS_TEST.md")
    versions={name:version(name) for name in ["tbs","PySide6","av","pyarrow","numpy","scipy","opencv-python","PyInstaller"]}
    (target/"build-info.json").write_text(json.dumps({"profile":"demo-only","packages":versions},indent=2))
    subprocess.run([str(target/"TBS.exe"),"--smoke"],check=True,timeout=120)
    shutil.make_archive(str(ROOT/"dist/TBS-Windows-Test"),"zip",root_dir=ROOT/"dist",base_dir="TBS")
    print("Portable Windows smoke PASS")


if __name__=="__main__":
    main()
