"""Shared frozen runtime; executable name selects GUI or console worker."""
import os
from pathlib import Path
import sys
from multiprocessing import freeze_support

if __name__ == '__main__':
    freeze_support()
    # Model installation is explicit in the application, never an inference side effect.
    os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
    if Path(sys.executable).stem.lower() == 'tbsworker':
        if '--runtime-smoke' in sys.argv:
            from tbs.runtime_smoke import main
            raise SystemExit(main([arg for arg in sys.argv[1:] if arg != '--runtime-smoke']))
        if '--diagnostics' in sys.argv:
            import json
            from tbs.diagnostics import report
            print(json.dumps(report(), ensure_ascii=False, indent=2))
            raise SystemExit(0)
        from tbs.worker import main
        raise SystemExit(main())
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    from tbs.gui.app import main
    raise SystemExit(main(smoke=args.smoke))
