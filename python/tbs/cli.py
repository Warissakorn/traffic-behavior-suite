import argparse
import json
import sys
from contextlib import redirect_stdout
from .config import load_site, load_project


def model_arguments(parser):
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--confidence", type=float, default=.25)
    parser.add_argument("--iou", type=float, default=.7)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--class-ids", type=int, nargs="+")


def model_options(args):
    from .models import detector_options
    values = dict(device=args.device, confidence=args.confidence, iou=args.iou, image_size=args.image_size)
    if args.class_ids is not None:
        values["class_ids"] = args.class_ids
    return detector_options(values)


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
    models = sub.add_parser("models", help="Catalog, register or check local detector weights")
    models.add_argument("--registry", help="Override the local model registry JSON path")
    model_sub = models.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("catalog", help="List detector presets; does not download weights")
    model_sub.add_parser("list", help="List registered local files")
    register = model_sub.add_parser("register", help="Register a local file and its SHA-256; does not run inference")
    register.add_argument("weights")
    register.add_argument("--name")
    from .models import PRESETS
    register.add_argument("--preset", choices=["custom", *PRESETS], default="custom")
    check = model_sub.add_parser("check", help="Check detector task and run one-frame inference")
    check.add_argument("weights")
    check.add_argument("--video", help="Use this video frame instead of a blank smoke-test image")
    check.add_argument("--time", type=float, default=0)
    model_arguments(check)
    compare = sub.add_parser("compare-models", help="Compare detector speed/resources in isolated processes; no accuracy claims")
    compare.add_argument("video")
    compare.add_argument("--model", action="append", required=True)
    compare.add_argument("--output", required=True)
    compare.add_argument("--max-frames", type=int, default=0, help="0 = entire clip, otherwise same first N frames per model")
    compare.add_argument("--warmup", type=int, default=2)
    model_arguments(compare)
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
        elif args.command == "models":
            from .models import ModelRegistry, check_model
            if args.model_command == "catalog":
                result = PRESETS
            elif args.model_command == "list":
                result = ModelRegistry(args.registry).records()
            elif args.model_command == "register":
                result = ModelRegistry(args.registry).register(args.weights, args.name, args.preset)
            else:
                image = None
                if args.video:
                    from .video import VideoReader
                    reader = VideoReader()
                    try:
                        image = reader.read(args.video, args.time)["image"][:, :, ::-1].copy()
                    finally:
                        reader.close()
                with redirect_stdout(sys.stderr):
                    result = check_model(args.weights, model_options(args), image)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.command == "compare-models":
            from .model_benchmark import compare_models
            out, report = compare_models(args.video, args.model, args.output, model_options(args), args.max_frames, args.warmup,
                                         on_progress=lambda event: print(json.dumps(event), file=sys.stderr))
            print(json.dumps(dict(output=str(out), status=report["status"]), ensure_ascii=False))
            return 0 if report["status"] == "completed" else 2
        else:
            from .diagnostics import report
            print(json.dumps(report(), indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        print(f"tbs: {exc}", file=sys.stderr)
        return 2

