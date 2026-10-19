# One analysis and one dependency folder shared by GUI and console worker.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parents[1]
profile = os.environ.get('TBS_BUILD_PROFILE', 'cpu')
datas, binaries, hiddenimports = [], [], ['tbs.worker', 'tbs.runtime_smoke', 'tbs.gui.app',
    'tbs.video_test', 'tbs.reid.features', 'scipy.signal', 'scipy.sparse.csgraph']
for package in ['tbs', 'av', 'pyarrow', 'ultralytics', 'onnxruntime', 'onnx']:
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for package in ['tbs', 'torch', 'torchvision', 'ultralytics',
                'onnxruntime-gpu' if profile == 'cuda' else 'onnxruntime']:
    datas += copy_metadata(package)

a = Analysis([str(root/'tools/windows/portable_entry.py')], pathex=[str(root/'python')],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineWidgets', 'PySide6.QtPdf', 'pytest'],
    noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TBS',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TBSWorker',
             debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
collection = COLLECT(gui, worker, a.binaries, a.datas, strip=False, upx=False, name='TBS')
