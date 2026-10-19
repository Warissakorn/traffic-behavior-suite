"""Keep build failures visible as GitHub annotations as well as full logs."""
from collections import deque
from pathlib import Path
import subprocess
import sys


def annotation(text):
    text = text[-12000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print(f'::error title=Portable Windows build::{text}', flush=True)


def main():
    root = Path(__file__).resolve().parents[2]
    lines = deque(maxlen=100)
    command = [sys.executable, '-u', str(root/'tools/windows/build.py'), *sys.argv[1:]]
    process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace')
    for line in process.stdout:
        print(line, end='', flush=True)
        lines.append(line)
    code = process.wait()
    if code:
        annotation(''.join(lines))
        for name in ['runtime-smoke.log', 'runtime-smoke.json']:
            path = root/'dist/TBS'/name
            if path.is_file() and path.stat().st_size:
                annotation(name + '\n' + path.read_text(encoding='utf-8', errors='replace')[-12000:])
    return code


if __name__ == '__main__':
    raise SystemExit(main())
