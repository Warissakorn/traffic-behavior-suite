"""Install the exact portable runtime profile into the current Python environment."""
import argparse
from pathlib import Path
import subprocess
import sys
from runtime_profiles import runtime_install, extras, PYINSTALLER_VERSION, ONNX_BUILD_VERSION

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=['cpu', 'cuda'], required=True)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    pip = [sys.executable, '-m', 'pip']
    subprocess.run([*pip, 'install', *runtime_install(args.profile)], check=True)
    subprocess.run([*pip, 'uninstall', '-y', 'onnxruntime' if args.profile == 'cuda' else 'onnxruntime-gpu'], check=True)
    packages = ['-e', f'{ROOT}[{extras(args.profile, args.build)}]']
    if args.build:
        packages += [f'pyinstaller=={PYINSTALLER_VERSION}', f'onnx=={ONNX_BUILD_VERSION}']
    subprocess.run([*pip, 'install', *packages, '-c', str(ROOT/'tools/windows/constraints.txt')], check=True)
    subprocess.run([*pip, 'check'], check=True)


if __name__ == '__main__':
    main()
