"""Single-site offline pipeline with streamed detections and disk-spooled tracks."""
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid
import time
import numpy as np
from . import __version__
from .config import load_site
from .detection import make_detector
from .storage import Writer
from .tracking import Tracker
from .trajectory import reconstruct, crossings
from .video import frames
from .events import CancelledError


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(config_path, output_dir, on_progress=None, should_cancel=None):
    def check_cancel():
        if should_cancel and should_cancel():
            raise CancelledError("Cancelled by user")

    def event(kind, **values):
        if on_progress:
            on_progress(dict(type=kind, **values))

    check_cancel()
    event("stage", stage="validate")
    config = load_site(config_path)
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    detector_path = config["models"]["detector"]
    model_hashes = {"detector": "synthetic-color-v1" if detector_path == "synthetic_color" else file_hash(detector_path)}
    run_id = str(uuid.uuid4())
    out = Path(output_dir).resolve()/run_id
    out.mkdir(parents=True)
    metadata = dict(schema_version="1-foundation", run_id=run_id, config_hash=config_hash, engine_version=__version__, epoch=config["epoch"], site_id=config["site_id"])
    warnings = ["Baseline association and Savitzky-Golay smoothing; accuracy not validated on traffic data.",
                "Lane/headway/vehicle dimensions/quality confidence and clock sync are not implemented."]
    if detector_path == "synthetic_color":
        warnings.append("Synthetic rectangle detector: for tests only.")
    report = dict(**metadata, status="running", model_hashes=model_hashes, warnings=warnings,
                  frames=0, detections=0, tracks=0, crossings=0, started_at=datetime.now(timezone.utc).isoformat())
    manifest = out/"manifest.json"

    def save_report():
        temp = manifest.with_suffix(".tmp")
        temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(manifest)

    save_report()
    try:
        event("started", run_id=run_id, output=str(out), site_id=config["site_id"])
        (out/"config.resolved.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        check_cancel()
        event("stage", stage="load_model")
        detector = make_detector(config)
        options = config["options"]
        tracker = Tracker(options.get("track_max_distance_m", 3), options.get("track_max_gap_s", 0.5))
        h = np.array(config["camera"]["image_to_ground"])
        with ExitStack() as stack:
            db = sqlite3.connect(out/"tracks.sqlite")
            stack.callback(db.close)
            db.execute("CREATE TABLE samples (vehicle INTEGER, class INTEGER, score REAL, t REAL, x REAL, y REAL)")
            db.execute("CREATE INDEX vehicle_time ON samples(vehicle, t)")
            writers = {}
            for name in ("frames", "detections", "trajectories", "vehicles", "line_crossings", "runs"):
                writers[name] = Writer(out/f"{name}.parquet", name, metadata)
                stack.callback(writers[name].close)
            buffers = {"frames": [], "detections": []}
            event("stage", stage="decode_track")
            started = time.monotonic()
            last_update = started
            for index, clip_index, t_video, t, image in frames(config):
                check_cancel()
                buffers["frames"].append(dict(frame_index=index, clip_index=clip_index, t_video=t_video, t=t))
                projected = []
                for cls, score, x1, y1, x2, y2 in detector.detect(image):
                    point = h @ np.array([(x1+x2)/2, y2, 1.0])
                    if not np.isfinite(point).all() or abs(point[2]) < 1e-12:
                        raise ValueError("Ground projection is invalid; check camera calibration")
                    projected.append(dict(class_id=cls, score=score, x1=x1, y1=y1, x2=x2, y2=y2, xy=point[:2]/point[2]))
                ids = tracker.update(t, projected)
                for det, key in zip(projected, ids):
                    x, y = map(float, det.pop("xy"))
                    buffers["detections"].append(dict(**det, frame_index=index, t=t, det_id=report["detections"], gx=x, gy=y, ground_method=0, track_id=key))
                    db.execute("INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?)", (key, det["class_id"], det["score"], t, x, y))
                    report["detections"] += 1
                report["frames"] += 1
                now = time.monotonic()
                if now-last_update >= 0.2:
                    event("progress", stage="decode_track", frames_done=report["frames"], frames_total=None,
                          detections=report["detections"], elapsed_s=now-started)
                    last_update = now
                if report["frames"] % 128 == 0:
                    for name, rows in buffers.items():
                        writers[name].write(rows)
                        rows.clear()
                    db.commit()
            for name, rows in buffers.items():
                writers[name].write(rows)
            db.commit()
            if report["frames"] == 0:
                raise ValueError("No video frames decoded")
            event("progress", stage="decode_track", frames_done=report["frames"], frames_total=None,
                  detections=report["detections"], elapsed_s=time.monotonic()-started)
            total_tracks = db.execute("SELECT COUNT(DISTINCT vehicle) FROM samples").fetchone()[0]
            event("stage", stage="reconstruct", vehicles_total=total_tracks)
            for key, cls, score, first, last, count in db.execute("SELECT vehicle, MIN(class), AVG(score), MIN(t), MAX(t), COUNT(*) FROM samples GROUP BY vehicle"):
                check_cancel()
                if count > 100000:
                    raise ValueError("Track exceeds reference limit of 100000 samples")
                samples = db.execute("SELECT t,x,y FROM samples WHERE vehicle=? ORDER BY t", (key,)).fetchall()
                for rows in reconstruct(samples, options.get("resample_dt", 0.1), options.get("max_interpolation_gap_s", 0.5)):
                    for row in rows:
                        row["vehicle_id"] = key
                    writers["trajectories"].write(rows)
                    events = list(crossings(rows, config["road"]["count_lines"]))
                    writers["line_crossings"].write(events)
                    report["crossings"] += len(events)
                writers["vehicles"].write([dict(vehicle_id=key, class_id=cls, class_conf=score, t_first=first, t_last=last, flags=0, quality=None)])
                report["tracks"] += 1
                event("progress", stage="reconstruct", vehicles_done=report["tracks"], vehicles_total=total_tracks)
            check_cancel()
            event("stage", stage="finalize")
            finished = datetime.now(timezone.utc)
            writers["runs"].write([dict(run_id=run_id, site_id=config["site_id"],
                started_at=datetime.fromisoformat(report["started_at"]), finished_at=finished, config_hash=config_hash,
                model_hashes=json.dumps(model_hashes, sort_keys=True), engine_version=__version__, clock_offset_s=None, clock_drift_ppm=None)])
        (out/"tracks.sqlite").unlink()
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
