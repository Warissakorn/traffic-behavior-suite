"""Run pytest and expose concise failures as GitHub check annotations."""
import sys
import pytest


def escaped(value):
    return str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A').replace(',', '%2C').replace(':', '%3A')


class FailureAnnotations:
    def pytest_runtest_logreport(self, report):
        if report.failed:
            title = report.nodeid.rsplit('::', 1)[-1]
            message = report.longreprtext[-3000:]
            print(f'::error title={escaped(title)}::{escaped(message)}', flush=True)

    def pytest_collectreport(self, report):
        if report.failed:
            print(f'::error title=Test collection::{escaped(str(report.longrepr)[-3000:])}', flush=True)


if __name__ == '__main__':
    raise SystemExit(pytest.main(sys.argv[1:] or ['-q'], plugins=[FailureAnnotations()]))
