"""Build and test a Windows portable CPU/CUDA application with one shared runtime."""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from runtime_profiles import TORCH_VERSION, CUDA_RUNTIME

ROOT = Path(__file__).resolve().parents[2]


def create_onnx_smoke(path):
    """Small local Conv/GAP embedding fixture; no external model download."""
    import numpy as np
    import onnx
    from onnx import helper, numpy_helper, TensorProto
    graph = helper.make_graph([
        helper.make_node('Conv', ['image', 'weight'], ['features']),
        helper.make_node('GlobalAveragePool', ['features'], ['pooled']),
        helper.make_node('Flatten', ['pooled'], ['embedding'], axis=1)], 'runtime-smoke',
        [helper.make_tensor_value_info('image', TensorProto.FLOAT, [1, 3, 32, 32])],
        [helper.make_tensor_value_info('embedding', TensorProto.FLOAT, [1, 16])],
        [numpy_helper.from_array(np.ones((16, 3, 1, 1), np.float32)/3, 'weight')])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)], ir_version=8)
    onnx.checker.check_model(model)
    onnx.save(model, path)


def check_runtime(profile):
    import torch
    import onnxruntime as ort
    if torch.__version__.split('+')[0] != TORCH_VERSION:
        raise RuntimeError(f'Expected PyTorch {TORCH_VERSION}, found {torch.__version__}')
    expected = CUDA_RUNTIME if profile == 'cuda' else None
    if torch.version.cuda != expected:
        raise RuntimeError(f'Profile {profile} requires CUDA runtime {expected}, found {torch.version.cuda}')
    if profile == 'cuda' and 'CUDAExecutionProvider' not in ort.get_available_providers():
        raise RuntimeError('CUDA build requires onnxruntime-gpu')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=['cpu', 'cuda'], default='cpu')
    args = parser.parse_args(argv)
    if sys.platform != 'win32':
        raise RuntimeError('Portable Windows builds must run on Windows / GitHub Actions Windows runner')
    check_runtime(args.profile)
    environment = dict(os.environ, TBS_BUILD_PROFILE=args.profile, YOLO_AUTOINSTALL='false',
                       MPLBACKEND='Agg', QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(ROOT/'dist'), '--workpath', str(ROOT/'build/portable'),
                    str(ROOT/'tools/windows/TBS.spec')], check=True, cwd=ROOT, env=environment)
    target = ROOT/'dist/TBS'
    for name in ['WINDOWS_TEST.md', 'REID_OD.md']:
        shutil.copyfile(ROOT/'docs'/name, target/name)
    shutil.copyfile(ROOT/'LICENSE', target/'LICENSE')
    fixture = target/'self-test/reid-smoke.onnx'
    fixture.parent.mkdir(exist_ok=True)
    create_onnx_smoke(fixture)
    packages = ['tbs', 'PySide6', 'av', 'pyarrow', 'numpy', 'scipy', 'opencv-python',
                'torch', 'torchvision', 'ultralytics', 'PyInstaller',
                'onnxruntime-gpu' if args.profile == 'cuda' else 'onnxruntime']
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    info = dict(profile=args.profile, commit=commit, cuda_runtime=CUDA_RUNTIME if args.profile == 'cuda' else None,
                packages={name: version(name) for name in packages},
                hardware_validation='CPU inference smoke on build runner; real CUDA hardware test required on target PC')
    (target/'build-info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    with (target/'runtime-smoke.json').open('w', encoding='utf-8') as output, (target/'runtime-smoke.log').open('w', encoding='utf-8') as log:
        subprocess.run([str(target/'TBSWorker.exe'), '--runtime-smoke', '--profile', args.profile,
                        '--device', 'cpu', '--onnx-model', str(fixture)],
                       check=True, timeout=300, env=environment, stdout=output, stderr=log)
    smoke = json.loads((target/'runtime-smoke.json').read_text(encoding='utf-8'))
    if smoke['status'] != 'passed' or len(smoke['detectors']) != 2 or not smoke['reid']:
        raise RuntimeError('Packaged inference smoke did not execute required detectors and Re-ID')
    subprocess.run([str(target/'TBS.exe'), '--smoke'], check=True, timeout=150, env=environment)
    (target/'Test-GPU.cmd').write_text(
        '@echo off\ncd /d "%~dp0"\n'
        'TBSWorker.exe --runtime-smoke --device 0 --profile cuda --onnx-model self-test\\reid-smoke.onnx > gpu-test.json 2> gpu-test.log\n'
        'if errorlevel 1 (\n  echo GPU test failed. See gpu-test.log\n  pause\n  exit /b 2\n)\n'
        'echo GPU inference passed. See gpu-test.json\npause\n', encoding='ascii')
    archive = Path(shutil.make_archive(str(ROOT/f'dist/TBS-Windows-{args.profile}'), 'zip',
                                       root_dir=ROOT/'dist', base_dir='TBS'))
    with archive.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'Portable Windows {args.profile} smoke PASS: {archive}')


if __name__ == '__main__':
    main()
