"""Shared frozen runtime; executable name selects GUI or console worker."""
import os
from pathlib import Path
import sys
from multiprocessing import freeze_support
import traceback


def dispatch():
    os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
    if Path(sys.executable).stem.lower() == 'tbsworker':
        if '--runtime-smoke' in sys.argv:
            from tbs.runtime_smoke import main
            return main([arg for arg in sys.argv[1:] if arg != '--runtime-smoke'])
        if '--diagnostics' in sys.argv:
            import json
            from tbs.diagnostics import report
            print(json.dumps(report(), ensure_ascii=False, indent=2))
            return 0
        from tbs.worker import main
        return main()
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    from tbs.gui.app import main
    return main(smoke=args.smoke)


if __name__ == '__main__':
    freeze_support()
    try:
        code = dispatch()
    except Exception:
        base = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or Path.home())
        path = Path(os.environ.get('TBS_STARTUP_LOG') or base/'TrafficBehaviorSuite/logs/frozen-startup.log')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(traceback.format_exc(), encoding='utf-8')
        # A windowed executable's error dialog otherwise blocks hosted smoke tests.
        if '--smoke' in sys.argv:
            raise SystemExit(2)
        raise
    raise SystemExit(code)
