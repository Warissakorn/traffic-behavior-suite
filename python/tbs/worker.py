"""Worker entry point shared by QProcess and the frozen TBSWorker executable."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import threading
import traceback
from .events import CancelledError


def main(argv=None):
    # Windows pipes otherwise inherit an ANSI code page, which cannot represent
    # Thai file paths in JSONL events. The protocol is always UTF-8.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):
            stream.reconfigure(encoding="utf-8",errors="replace",line_buffering=True)
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config")
    source.add_argument("--demo", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args(argv)
    control = Path(args.control)
    output = Path(args.output).resolve()
    channel = sys.stdout
    lock = threading.Lock()
    done = threading.Event()
    current = {}

    def emit(event):
        if event.get("type") in {"completed","failed","cancelled"}:
            done.set()
        if event.get("run_id"):
            current["run_id"] = event["run_id"]
        with lock:
            channel.write(json.dumps({"event_version": 1, "session_id": args.session,
                                      **current, **event}, ensure_ascii=False)+"\n")
            channel.flush()

    def heartbeat():
        while not done.wait(2):
            emit({"type": "heartbeat"})

    def cancelled():
        if not control.is_file():
            return False
        try:
            return json.loads(control.read_text(encoding="utf-8")).get("session_id") == args.session
        except (OSError, ValueError):
            return False

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    code = 0
    completed_event = None
    def progress(event):
        nonlocal completed_event
        if args.demo and event.get("type")=="completed":
            completed_event = event
        else:
            emit(event)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from .pipeline import run
            if cancelled():
                raise CancelledError("Cancelled before start")
            path = args.config
            if args.demo:
                emit({"type": "stage", "stage": "create_fixture"})
                from .demo import fixture
                path = fixture(output/"fixtures"/args.session)
            out, report = run(path, output, on_progress=progress, should_cancel=cancelled)
            if args.demo:
                from .demo import evaluate
                metrics = evaluate(out,report)
                (out/"benchmark.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
                emit({**completed_event,"benchmark":metrics})
    except CancelledError as exc:
        emit({"type": "cancelled", "message": str(exc)})
        code = 3
    except BaseException as exc:
        traceback.print_exc(file=sys.stderr)
        emit({"type": "failed", "message": f"{type(exc).__name__}: {exc}"})
        code = 2
    finally:
        done.set()
        thread.join(timeout=3)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
