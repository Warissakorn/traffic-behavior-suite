from fractions import Fraction
import json
import subprocess
import sys
import wave

import av
import numpy as np
import pyarrow.parquet as pq
import pytest

from tbs.demo import fixture
from tbs.detection import SyntheticColorDetector
from tbs.events import CancelledError, EventParser
from tbs.gui.result_store import ResultStore
from tbs.video import VideoReader, check_playlist, probe_video
from tbs.video_test import run, validate_config


def variable_video(path):
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("ffv1", rate=10)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "bgr0"
        for index, pts in enumerate([100, 101, 103, 107]):
            frame = av.VideoFrame.from_ndarray(np.full((32, 32, 3), index*30, dtype=np.uint8), format="bgr24")
            frame.pts, frame.time_base = pts, Fraction(1, 10)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def test_reader_uses_relative_pts_and_reuses_decoder(tmp_path, monkeypatch):
    path = variable_video(tmp_path/"เวลาต่างกัน.mkv")
    opened = []
    original = av.open
    def opening(*args, **kwargs):
        opened.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr("tbs.video.av.open", opening)
    reader = VideoReader()
    try:
        for target, expected in [(0, 0), (.1, .1), (.25, .3), (.69, .7), (0, 0), (.3, .3)]:
            assert reader.read(path, target)["t_video"] == pytest.approx(expected)
        assert len(opened) == 1
        assert reader.info["last_time_s"] == pytest.approx(.7)
        assert reader.info["duration_s"] is None or reader.info["duration_s"] < 1
        assert reader.read(path, 1)["eof"]
    finally:
        reader.close()
    path.rename(path.with_suffix(".closed"))


def test_probe_rejects_audio_only_and_corrupt_files(tmp_path):
    audio = tmp_path/"audio.wav"
    with wave.open(str(audio), "wb") as handle:
        handle.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\0\0"*800)
    with pytest.raises(ValueError, match="video stream"):
        probe_video(audio)
    broken = tmp_path/"broken.mp4"
    broken.write_bytes(b"not a video")
    with pytest.raises(av.FFmpegError):
        probe_video(broken)
    broken.unlink()


def test_playlist_preflight_uses_last_pts(tmp_path):
    path = variable_video(tmp_path/"clip.mkv")
    config = dict(videos=[dict(path=str(path), start_time="2026-01-01T00:00:00Z"),
                         dict(path=str(path), start_time="2026-01-01T00:00:00.750Z")])
    assert len(check_playlist(config)) == 2
    config["videos"][1]["start_time"] = "2026-01-01T00:00:00.700Z"
    with pytest.raises(ValueError, match="ซ้อน"):
        check_playlist(config)


def config_fixture(tmp_path):
    fixture(tmp_path)
    weights = tmp_path/"local.pt"
    weights.write_bytes(b"test detector boundary")
    config = dict(video=str(tmp_path/"synthetic.mkv"), detector=str(weights), options=dict(confidence=.35))
    path = tmp_path/"video.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path, config


@pytest.mark.parametrize("options", [dict(confidence=float("nan")), dict(confidence=True),
    dict(confidence=1.1), dict(device=""), dict(class_ids=[2, 2]), dict(class_ids=[-1]),
    dict(class_ids=[True]), dict(track_max_distance_m=3)])
def test_video_test_validates_options(tmp_path, options):
    _, config = config_fixture(tmp_path)
    with pytest.raises(ValueError):
        validate_config(dict(config, options=options))


def test_detection_only_results_and_exports(tmp_path, monkeypatch):
    path, _ = config_fixture(tmp_path/"ข้อมูล ทดสอบ")
    monkeypatch.setattr("tbs.video_test.make_detector", lambda config: SyntheticColorDetector())
    out, report = run(path, tmp_path/"runs")
    assert report["status"] == "completed"
    assert report["run_mode"] == "video_test"
    assert (report["frames"], report["detections"], report["tracks"]) == (50, 50, 0)
    store = ResultStore(out)
    assert store.mode == "video_test"
    assert store.counts() == [dict(class_id=0, detections=50)]
    assert store.frame_at(2.53)["frame_index"] == 25
    assert store.frame_at(100)["frame_index"] == 49
    detection = store.frame_detections(25)[0]
    assert detection["gx"] is None and detection["track_id"] is None
    destination = tmp_path/"CSV ภาษาไทย"
    store.export_csv(destination)
    headers = (destination/"detections.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "x1_px" in headers and "t_s" in headers
    assert not (destination/"trajectories.csv").exists()


def test_video_test_cancellation_releases_outputs(tmp_path, monkeypatch):
    path, _ = config_fixture(tmp_path/"fixture")
    calls = []
    class Detector:
        def detect(self, image):
            calls.append(1)
            return []
    monkeypatch.setattr("tbs.video_test.make_detector", lambda config: Detector())
    events = []
    with pytest.raises(CancelledError):
        run(path, tmp_path/"runs", on_progress=events.append, should_cancel=lambda: len(calls) >= 3)
    out = next((tmp_path/"runs").iterdir())
    assert json.loads((out/"manifest.json").read_text())["status"] == "cancelled"
    assert not any(event["type"] == "completed" for event in events)
    for name in ["frames", "detections"]:
        pq.read_table(out/f"{name}.parquet")
        (out/f"{name}.parquet").rename(out/f"closed-{name}.parquet")


def test_video_test_model_failure_is_reported(tmp_path, monkeypatch):
    path, _ = config_fixture(tmp_path)
    def fail(config):
        raise ValueError("incompatible weights")
    monkeypatch.setattr("tbs.video_test.make_detector", fail)
    with pytest.raises(ValueError, match="incompatible"):
        run(path, tmp_path/"runs")
    report = json.loads(next((tmp_path/"runs").glob("*/manifest.json")).read_text())
    assert report["status"] == "failed"


def test_worker_camera_free_protocol(tmp_path):
    path, _ = config_fixture(tmp_path)
    # Use a deterministic detector at the adapter boundary, inside a real worker.
    code = "from tbs import video_test, worker; from tbs.detection import SyntheticColorDetector; video_test.make_detector=lambda config:SyntheticColorDetector(); raise SystemExit(worker.main())"
    result = subprocess.run([sys.executable, "-c", code, "--video-test", str(path),
        "--output", str(tmp_path/"runs"), "--session", "video-session", "--control", str(tmp_path/"cancel.json")],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    events = EventParser().feed(result.stdout.encode())
    assert events[-1]["type"] == "completed"
    assert all(event["session_id"] == "video-session" for event in events)
    assert ResultStore(events[-1]["output"]).mode == "video_test"
