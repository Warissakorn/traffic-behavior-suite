"""Run pytest and expose concise failures as GitHub check annotations."""
import sys
import pytest


def escaped(value):
    return str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A').replace(',', '%2C').replace(':', '%3A')


class FailureAnnotations:
    def __init__(self):
        self.failures = []

    def pytest_runtest_logreport(self, report):
        if report.failed:
            title = report.nodeid.rsplit('::', 1)[-1]
            message = report.longreprtext[-3000:]
            self.failures.append((title, message))

    def pytest_collectreport(self, report):
        if report.failed:
            self.failures.append(('Test collection', str(report.longrepr)[-3000:]))


if __name__ == '__main__':
    annotations = FailureAnnotations()
    code = pytest.main(sys.argv[1:] or ['-q'], plugins=[annotations])
    # Emit after pytest restores output capture, at the start of a fresh line.
    for title, message in annotations.failures:
        print(f'\n::error title={escaped(title)}::{escaped(message)}', flush=True)
    raise SystemExit(code)
