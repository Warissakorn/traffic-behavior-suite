"""Camera-free detection runs, using the same worker/result contracts as sites."""
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid

from . import __version__
from .detection import make_detector
from .events import CancelledError
from .pipeline import file_hash
from .storage import Writer
from .video import frames, probe_video
from .models import model_path, detector_options, describe_detector
from .spatial import Regions, validate_regions


def validate_config(config, base=None):
    if not isinstance(config, dict):
        raise ValueError("ข้อมูลทดสอบวิดีโอต้องเป็น object")
    base = Path(base or Path.cwd())
    resolved = {}
    for key, label in [("video", "วิดีโอ"), ("detector", "โมเดล")]:
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"เลือกไฟล์{label}ก่อนเริ่มทดสอบ")
        path = (base / value).resolve()
        if not path.is_file():
            raise ValueError(f"ไม่พบไฟล์{label}: {path}")
        resolved[key] = str(path)
    options = config.get("options", {})
    if not isinstance(options, dict) or set(options) - {"confidence", "device", "class_ids", "image_size", "iou", "half"}:
        raise ValueError("ตัวเลือกทดสอบรองรับ confidence, device, class_ids, image_size และ iou")
    expected = config.get("detector_sha256")
    model_path(resolved["detector"])
    if expected is not None:
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise ValueError("detector_sha256 must be a lowercase SHA-256 hash")
        resolved["detector_sha256"] = expected
    resolved["options"] = detector_options(options)
    if 'image_regions' in config:
        resolved['image_regions'] = validate_regions(config['image_regions'])
        if resolved['image_regions']['points']:
            raise ValueError('Point gates require site tracking; video test supports ROI only')
    return resolved


def run(config_path, output_dir, on_progress=None, should_cancel=None):
    def check_cancel():
        if should_cancel and should_cancel():
            raise CancelledError("Cancelled by user")

    def event(kind, **values):
        if on_progress:
            on_progress(dict(type=kind, **values))

    check_cancel()
    event("stage", stage="validate")
    source = Path(config_path).resolve()
    test = validate_config(json.loads(source.read_text(encoding="utf-8")), source.parent)
    info = probe_video(test["video"])
    check_cancel()
    epoch = datetime.now(timezone.utc).isoformat()
    config = dict(epoch=epoch, site_id="video_test", run_mode="video_test",
                  videos=[dict(path=test["video"], start_time=epoch)],
                  models=dict(detector=test["detector"]), options=test["options"],
                  road=dict(count_lines=[]))
    if 'image_regions' in test:
        config['image_regions'] = test['image_regions']
    if "detector_sha256" in test:
        config["models"]["detector_sha256"] = test["detector_sha256"]
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    run_id = str(uuid.uuid4())
    out = Path(output_dir).resolve() / run_id
    out.mkdir(parents=True)
    metadata = dict(schema_version="1-foundation", run_id=run_id, config_hash=config_hash,
                    engine_version=__version__, epoch=epoch, site_id="video_test", run_mode="video_test")
    report = dict(**metadata, status="running", frames=0, detections=0, tracks=0, crossings=0,
                  started_at=epoch, video_info=info, model_hashes={},
                  warnings=["Detection test in image pixels; ground coordinates, tracks, speed and line counts are not computed."])
    manifest = out / "manifest.json"

    def save_report():
        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(manifest)

    save_report()
    try:
        event("started", run_id=run_id, output=str(out), site_id="video_test", run_mode="video_test")
        (out / "config.resolved.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        event("stage", stage="load_model")
        report["model_hashes"] = dict(detector=file_hash(test["detector"]))
        check_cancel()
        detector = make_detector(config)
        regions = Regions(config.get('image_regions'))
        report["detector_model"] = describe_detector(detector, test["detector"], test["options"],
                                                     test.get("detector_sha256"))
        report["model_hashes"]["detector"] = report["detector_model"]["sha256"]
        check_cancel()
        with ExitStack() as stack:
            writers = {}
            for name in ("frames", "detections", "trajectories", "vehicles", "line_crossings", "runs"):
                writers[name] = Writer(out / f"{name}.parquet", name, metadata)
                stack.callback(writers[name].close)
            buffers = dict(frames=[], detections=[])
            started = last_update = time.monotonic()
            event("stage", stage="detect_video")
            for index, clip_index, t_video, t, image in frames(config):
                check_cancel()
                buffers["frames"].append(dict(frame_index=index, clip_index=clip_index, t_video=t_video, t=t))
                detections = regions.detect(detector, image)
                report['inference_region'] = regions.inference
                report["detector_model"].update(getattr(detector, "metadata", {}))
                for cls, score, x1, y1, x2, y2 in detections:
                    buffers["detections"].append(dict(frame_index=index, t=t, det_id=report["detections"],
                        class_id=cls, score=score, x1=x1, y1=y1, x2=x2, y2=y2,
                        gx=None, gy=None, ground_method=None, track_id=None))
                    report["detections"] += 1
                report["frames"] += 1
                now = time.monotonic()
                if now - last_update >= 0.2:
                    event("progress", stage="detect_video", frames_done=report["frames"],
                          detections=report["detections"], elapsed_s=now-started,
                          video_time_s=t_video, duration_s=info["duration_s"])
                    last_update = now
                if report["frames"] % 128 == 0:
                    for name, rows in buffers.items():
                        writers[name].write(rows)
                        rows.clear()
            for name, rows in buffers.items():
                writers[name].write(rows)
            if not report["frames"]:
                raise ValueError("No video frames decoded")
            check_cancel()
            event("progress", stage="detect_video", frames_done=report["frames"],
                  detections=report["detections"], elapsed_s=time.monotonic()-started,
                  video_time_s=t_video, duration_s=info["duration_s"])
            event("stage", stage="finalize")
            finished = datetime.now(timezone.utc)
            writers["runs"].write([dict(run_id=run_id, site_id="video_test",
                started_at=datetime.fromisoformat(epoch), finished_at=finished, config_hash=config_hash,
                model_hashes=json.dumps(report["model_hashes"], sort_keys=True), engine_version=__version__,
                clock_offset_s=None, clock_drift_ppm=None)])
        check_cancel()
        report.update(status="completed", finished_at=finished.isoformat())
        save_report()
        event("completed", output=str(out), run_id=run_id, report=report)
        return out, report
    except BaseException as exc:
        report.update(status="cancelled" if isinstance(exc, CancelledError) else "failed",
                      error=f"{type(exc).__name__}: {exc}", finished_at=datetime.now(timezone.utc).isoformat())
        save_report()
        raise

