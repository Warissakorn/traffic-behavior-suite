"""Stream pytest output and attach its failure tail to GitHub Checks."""
import os
import subprocess
import sys


def escaped(value):
    return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def main():
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    tail = bytearray()
    process = subprocess.Popen([sys.executable, '-m', 'pytest', *(sys.argv[1:] or ['-q'])],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment)
    for line in iter(process.stdout.readline, b''):
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
        tail.extend(line)
        if len(tail) > 16000:
            del tail[:-16000]
    process.stdout.close()
    code = process.wait()
    if code:
        message = bytes(tail).decode('utf-8', errors='replace')[-3000:]
        annotation = '\n::error title=Source tests failed::'+escaped(message)+'\n'
        sys.stdout.buffer.write(annotation.encode('utf-8'))
        sys.stdout.buffer.flush()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
