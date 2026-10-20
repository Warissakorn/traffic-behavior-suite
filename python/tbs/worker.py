"""Worker entry point shared by QProcess and the frozen TBSWorker executable."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import threading
import traceback
from .events import CancelledError, PausedError


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
    source.add_argument("--video-test", help="Camera-free video/model JSON snapshot")
    source.add_argument('--resume', help='Resume a site run directory with a clip checkpoint')
    parser.add_argument("--output", required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument('--pause-after-clips', type=int, help='Pause automatically after this many committed clips')
    args = parser.parse_args(argv)
    if args.pause_after_clips is not None and args.pause_after_clips < 1:
        parser.error('--pause-after-clips must be positive')
    control = Path(args.control)
    output = Path(args.output).resolve()
    channel = sys.stdout
    lock = threading.Lock()
    done = threading.Event()
    current = {}
    committed_clips = 0

    def emit(event):
        nonlocal committed_clips
        if 'clips_done' in event:
            committed_clips = event['clips_done']
        if event.get("type") in {"completed","failed","cancelled","paused"}:
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

    def requested(action):
        if action == 'pause' and args.pause_after_clips and committed_clips >= args.pause_after_clips:
            return True
        if not control.is_file():
            return False
        try:
            value = json.loads(control.read_text(encoding='utf-8'))
            return value.get('session_id') == args.session and value.get('action', 'cancel') == action
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
            if args.video_test:
                from .video_test import run
            else:
                from .pipeline import run
            if requested('cancel'):
                raise CancelledError("Cancelled before start")
            path = args.video_test or args.config or (Path(args.resume)/'source.yaml' if args.resume else None)
            if args.demo:
                emit({"type": "stage", "stage": "create_fixture"})
                from .demo import fixture
                path = fixture(output/"fixtures"/args.session)
            extra = dict(resume=args.resume, should_pause=lambda: requested('pause')) if not args.video_test else {}
            out, report = run(path, output, on_progress=progress, should_cancel=lambda: requested('cancel'), **extra)
            if args.demo:
                from .demo import evaluate
                metrics = evaluate(out,report)
                (out/"benchmark.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
                emit({**completed_event,"benchmark":metrics})
    except PausedError as exc:
        emit({'type': 'paused', 'message': str(exc)})
        code = 4
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
