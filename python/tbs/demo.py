"""Deterministic generated video with known speed and one finite-line crossing."""
from fractions import Fraction
from pathlib import Path
import json
import av
import numpy as np
import pyarrow.parquet as pq
import yaml
from .pipeline import run


def fixture(output):
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    video = out/"synthetic.mkv"
    with av.open(str(video), mode="w") as container:
        stream = container.add_stream("ffv1", rate=10)
        stream.width, stream.height, stream.pix_fmt = 320, 120, "bgr0"
        for index in range(50):
            image = np.zeros((120, 320, 3), dtype=np.uint8)
            x = 20+4*index
            image[50:70, x:x+20] = (0, 255, 0)
            frame = av.VideoFrame.from_ndarray(image, format="bgr24")
            frame.pts, frame.time_base = index, Fraction(1, 10)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    (out/"camera.yaml").write_text(yaml.safe_dump({"projection": "planar_homography", "image_to_ground": [[0.1,0,0],[0,0.1,0],[0,0,1]]}))
    config = {"schema_version": 1, "site_id": "synthetic", "videos": [{"path": "synthetic.mkv", "start_time": "2026-01-01T00:00:00Z"}],
              "camera": {"model_file": "camera.yaml"}, "road": {"count_lines": [{"id": "mid", "p1": [13,0], "p2": [13,12]}]},
              "models": {"detector": "synthetic_color"}, "options": {"resample_dt": 0.1}}
    path = out/"site.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def benchmark(output):
    root = Path(output).resolve()
    path = fixture(root/"fixture")
    out, report = run(path, root/"runs")
    result = evaluate(out, report)
    (root/"benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def evaluate(out, report):
    out = Path(out)
    traj = pq.read_table(out/"trajectories.parquet").to_pydict()
    events = pq.read_table(out/"line_crossings.parquet").to_pylist()
    speed = np.asarray(traj["v"])
    position_error = np.asarray(traj["x"])-(3+4*np.asarray(traj["t"]))
    metrics = {"frames": report["frames"], "tracks": report["tracks"], "crossings": len(events),
               "position_rmse_m": float(np.sqrt(np.mean(position_error**2))),
               "speed_rmse_m_s": float(np.sqrt(np.mean((speed-4)**2))),
               "crossing_time_error_s": abs(events[0]["t"]-2.5) if len(events)==1 else None}
    passed = (metrics["frames"] == 50 and metrics["tracks"] == 1 and metrics["crossings"] == 1
              and metrics["position_rmse_m"] < 0.01 and metrics["speed_rmse_m_s"] < 0.01
              and metrics["crossing_time_error_s"] < 0.01)
    result = {"fixture": "synthetic rectangles, not real traffic accuracy", "passed": passed, "metrics": metrics, "output": str(out)}
    if not passed:
        raise ValueError(f"Synthetic benchmark failed: {metrics}")
    return result
