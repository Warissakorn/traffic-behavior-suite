import argparse
import json
import sys
from .config import load_site, load_project


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tbs", description="Traffic Behavior Suite Python reference")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Validate site config, local paths and calibration")
    validate.add_argument("config")
    validate.add_argument("--kind", choices=["site", "project"], default="site")
    execute = sub.add_parser("run", help="Run a single-site offline reference pipeline")
    execute.add_argument("config")
    execute.add_argument("--output", required=True)
    demo = sub.add_parser("demo", help="Generate a synthetic fixture and run its benchmark")
    demo.add_argument("--output", required=True)
    gui = sub.add_parser("gui", help="Open the desktop test application")
    gui.add_argument("--smoke", action="store_true", help="Run an offscreen GUI + worker smoke test")
    sub.add_parser("diagnostics", help="Report installed runtime modules")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            config = load_project(args.config) if args.kind == "project" else load_site(args.config)
            print(json.dumps({"valid": True, "id": config.get("site_id", config.get("project_id"))}))
        elif args.command == "run":
            from .pipeline import run
            out, report = run(args.config, args.output)
            print(json.dumps({"output": str(out), **report}, ensure_ascii=False))
        elif args.command == "demo":
            from .demo import benchmark
            print(json.dumps(benchmark(args.output), indent=2))
        elif args.command == "gui":
            from .gui.app import main as gui_main
            return gui_main(smoke=args.smoke)
        else:
            from .diagnostics import report
            print(json.dumps(report(), indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        print(f"tbs: {exc}", file=sys.stderr)
        return 2
