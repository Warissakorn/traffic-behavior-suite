"""Comparable detection performance, one fresh subprocess per local model.

This is not an accuracy benchmark. RSS is sampled process RAM; CUDA values are
PyTorch allocator peaks for this process, not total device VRAM.
"""
from contextlib import redirect_stdout
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .models import local_model, detector_options, describe_detector, file_hash


def measure(request):
    import psutil
    from .detection import make_detector
    from .video import frames, VideoReader
    options = detector_options(request["options"])
    peak = [None]
    resource_notes = []
    stop = threading.Event()
    try:
        process = psutil.Process()
    except (psutil.Error, OSError) as exc:
        process = None
        resource_notes.append(f"RSS unavailable: {type(exc).__name__}: {exc}")

    def sample_once():
        if process is None:
            return False
        try:
            peak[0] = max(peak[0] or 0, process.memory_info().rss)
            return True
        except (psutil.Error, OSError) as exc:
            resource_notes.append(f"RSS unavailable: {type(exc).__name__}: {exc}")
            return False

    def sample():
        while not stop.is_set():
            if not sample_once():
                break
            stop.wait(.02)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        if file_hash(request["video"]) != request["video_sha256"]:
            raise ValueError("Video changed during model comparison")
        card = local_model(request["model"], request["sha256"])
        loaded = time.perf_counter()
        detector = make_detector(dict(models=dict(detector=card["path"], detector_sha256=card["sha256"]), options=options))
        load_seconds = time.perf_counter() - loaded
        reader = VideoReader()
        try:
            image = reader.read(request["video"])["image"][:, :, ::-1].copy()
        finally:
            reader.close()
        for _ in range(request["warmup"]):
            detector.detect(image)
        del image
        torch = sys.modules.get("torch")
        cuda_device = None
        runtime_device = getattr(getattr(getattr(detector, "model", None), "predictor", None), "device", None)
        if torch is not None and getattr(runtime_device, "type", None) == "cuda":
            cuda_device = runtime_device
            torch.cuda.synchronize(cuda_device)
            torch.cuda.reset_peak_memory_stats(cuda_device)
        count = detections = 0
        inference_seconds = 0.0
        first_pts = last_pts = None
        config = dict(epoch="2026-01-01T00:00:00Z", videos=[dict(path=request["video"], start_time="2026-01-01T00:00:00Z")])
        started = time.perf_counter()
        iterator = frames(config)
        try:
            for _, _, pts, _, image in iterator:
                before = time.perf_counter()
                result = detector.detect(image)
                if cuda_device is not None:
                    torch.cuda.synchronize(cuda_device)
                inference_seconds += time.perf_counter() - before
                detections += len(result)
                count += 1
                first_pts = pts if first_pts is None else first_pts
                last_pts = pts
                if request["max_frames"] and count >= request["max_frames"]:
                    break
        finally:
            iterator.close()
        elapsed = time.perf_counter() - started
        if not count:
            raise ValueError("No frames decoded")
        sample_once()
        return dict(status="completed", model=describe_detector(detector, card["path"], options, card["sha256"]),
                    frames=count, detections=detections, first_pts_s=first_pts, last_pts_s=last_pts,
                    model_load_s=load_seconds, decode_inference_s=elapsed,
                    decode_inference_fps=count / elapsed, inference_ms_per_frame=1000 * inference_seconds / count,
                    peak_rss_bytes=peak[0], resource_notes=resource_notes,
                    peak_cuda_allocated_bytes=int(torch.cuda.max_memory_allocated(cuda_device)) if cuda_device is not None else None,
                    peak_cuda_reserved_bytes=int(torch.cuda.max_memory_reserved(cuda_device)) if cuda_device is not None else None,
                    environment=dict(pid=os.getpid(), python=platform.python_version(), platform=platform.platform(),
                                     processor=platform.processor(), psutil=psutil.__version__,
                                     torch=getattr(torch, "__version__", None),
                                     torch_threads=torch.get_num_threads() if torch is not None else None,
                                     cuda_device_name=torch.cuda.get_device_name(cuda_device) if cuda_device is not None else None))
    finally:
        stop.set()
        sampler.join(timeout=1)


def compare_models(video, models, output, options=None, max_frames=0, warmup=2, on_progress=None):
    if type(max_frames) is not int or max_frames < 0 or type(warmup) is not int or not 0 <= warmup <= 100:
        raise ValueError("max_frames ต้องไม่ติดลบ และ warmup ต้องอยู่ระหว่าง 0–100")
    if len(models) < 2:
        raise ValueError("เลือกอย่างน้อย 2 โมเดลเพื่อเปรียบเทียบ")
    video = Path(video).expanduser().resolve()
    if not video.is_file():
        raise ValueError(f"Video not found: {video}")
    cards = [local_model(path) for path in models]
    if len({card["path"] for card in cards}) != len(cards):
        raise ValueError("ไม่เลือกไฟล์โมเดลเดียวกันซ้ำ")
    options = detector_options(options or {})
    # Verify the resource sampler exists before starting a partial comparison.
    import psutil  # noqa: F401
    out = Path(output).resolve() / ("comparison-" + str(uuid.uuid4()))
    out.mkdir(parents=True)
    report = dict(schema_version=1, run_mode="model_comparison", status="running",
                  started_at=datetime.now(timezone.utc).isoformat(),
                  video=dict(path=str(video), sha256=file_hash(video)), options=options,
                  max_frames=max_frames, warmup_frames=warmup, models=[], accuracy_metrics=None,
                  notes=["No ground truth: detection counts and FPS do not establish accuracy.",
                         "FPS includes decode and inference; excludes model load, warmup and result export.",
                         "RAM: process RSS sampled every 20 ms, including load/warmup.",
                         "CUDA: per-process PyTorch allocator peaks after warmup; not whole-device VRAM."])

    def save():
        temp = out / "comparison.tmp"
        temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(out / "comparison.json")

    save()
    try:
        for index, card in enumerate(cards):
            if on_progress:
                on_progress(dict(model=card["filename"], index=index + 1, total=len(cards)))
            with tempfile.TemporaryDirectory(dir=out) as temp:
                source, target = Path(temp) / "request.json", Path(temp) / "result.json"
                source.write_text(json.dumps(dict(video=str(video), model=card["path"], sha256=card["sha256"],
                                                 video_sha256=report["video"]["sha256"],
                                                 options=options, max_frames=max_frames, warmup=warmup)), encoding="utf-8")
                child = subprocess.Popen([sys.executable, "-m", "tbs.model_benchmark", str(source), str(target)],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
                try:
                    _, stderr = child.communicate()
                except BaseException:
                    child.kill()
                    child.communicate()
                    raise
                if target.is_file():
                    row = json.loads(target.read_text(encoding="utf-8"))
                else:
                    row = dict(status="failed", model=card, error=f"Worker exit {child.returncode}: {stderr[-2000:]}")
                if child.returncode and row.get("status") != "failed":
                    row.update(status="failed", error=f"Worker exit {child.returncode}: {stderr[-2000:]}")
                report["models"].append(row)
                save()
        report["status"] = "completed" if all(row["status"] == "completed" for row in report["models"]) else "failed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    except BaseException:
        report.update(status="interrupted", finished_at=datetime.now(timezone.utc).isoformat())
        save()
        raise
    fields = ["name", "sha256", "status", "frames", "detections", "decode_inference_fps", "inference_ms_per_frame",
              "model_load_s", "peak_rss_bytes", "peak_cuda_allocated_bytes", "peak_cuda_reserved_bytes", "error"]
    with (out / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in report["models"]:
            writer.writerow({key: row["model"].get("filename") if key == "name" else
                             row["model"].get("sha256") if key == "sha256" else row.get(key) for key in fields})
    return out, report


if __name__ == "__main__":
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        with redirect_stdout(sys.stderr):
            result = measure(request)
        code = 0
    except Exception as exc:
        result = dict(status="failed", model=dict(path=request["model"], filename=Path(request["model"]).name,
                                                   sha256=request["sha256"]), error=f"{type(exc).__name__}: {exc}")
        code = 2
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    raise SystemExit(code)
