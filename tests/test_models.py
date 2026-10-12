import csv
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from tbs.cli import main
from tbs.config import load_site
from tbs.demo import fixture
from tbs.models import ModelRegistry, PRESETS, check_model, detector_options, file_hash, local_model


def weights(tmp_path, name="รถไทย.pt"):
    path = tmp_path / name
    path.write_bytes(b"local adapter fixture")
    return path


def test_registry_roundtrip_replacement_and_changed_weights(tmp_path):
    path = weights(tmp_path)
    registry = ModelRegistry(tmp_path / "ทะเบียน" / "models.json")
    first = registry.register(path, "โมเดลของฉัน", "yolo11s")
    assert registry.records()[0]["sha256"] == file_hash(path)
    assert registry.records()[0]["validation"] == "file_only"
    registry.register(path, "ชื่อใหม่", "custom")
    assert len(registry.records()) == 1
    assert registry.records()[0]["name"] == "ชื่อใหม่"
    path.write_bytes(b"replaced weights")
    with pytest.raises(ValueError, match="เปลี่ยน"):
        local_model(path, first["sha256"])
    assert not list(registry.path.parent.glob("*.tmp"))


def test_invalid_registry_is_preserved(tmp_path):
    path = tmp_path / "models.json"
    path.write_text('{"schema_version": 99, "models": []}')
    original = path.read_bytes()
    with pytest.raises(ValueError, match="ทะเบียน"):
        ModelRegistry(path).register(weights(tmp_path))
    assert path.read_bytes() == original


@pytest.mark.parametrize("options", [dict(image_size=True), dict(image_size=641), dict(image_size=0),
    dict(iou=float("nan")), dict(iou=True), dict(iou=-1), dict(confidence=float("inf")), dict(class_ids=[2, 2])])
def test_invalid_detector_options(options):
    with pytest.raises(ValueError):
        detector_options(options)


def test_schema_accepts_legacy_and_checks_registered_hash(tmp_path):
    path = fixture(tmp_path)
    old = load_site(path)
    assert old["options"]["image_size"] == 640
    model = weights(tmp_path)
    config = yaml.safe_load(path.read_text())
    config["models"].update(detector=model.name, detector_sha256=file_hash(model))
    config["options"].update(image_size=320, iou=.5)
    path.write_text(yaml.safe_dump(config))
    assert load_site(path)["options"]["iou"] == .5
    model.write_bytes(b"different")
    with pytest.raises(ValueError, match="เปลี่ยน"):
        load_site(path)


def fake_ultralytics(monkeypatch, task="detect"):
    from tbs import detection
    calls = []
    class Array:
        def __init__(self, values):
            self.values = values
        def cpu(self):
            return self.values
    class Yolo:
        def __init__(self, path):
            self.task = task
        def predict(self, image, **kwargs):
            calls.append(kwargs)
            boxes = SimpleNamespace(cls=Array([2]), conf=Array([.9]), xyxy=Array([[1, 2, 3, 4]]))
            return [SimpleNamespace(boxes=boxes, names={2: "car"})]
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Yolo))
    monkeypatch.setattr(detection, "version", lambda name: "test-adapter")
    return calls


def test_adapter_options_metadata_and_wrong_task(tmp_path, monkeypatch):
    calls = fake_ultralytics(monkeypatch)
    model = weights(tmp_path)
    result = check_model(model, dict(image_size=320, iou=.45, class_ids=[2]))
    assert calls[0]["imgsz"] == 320 and calls[0]["iou"] == .45
    assert result["model"]["class_names"] == {"2": "car"}
    assert result["model"]["sha256"] == file_hash(model)
    assert result["detections"][0]["x2"] == 3
    with pytest.raises(ValueError, match="Class IDs"):
        check_model(model, dict(class_ids=[7]))
    fake_ultralytics(monkeypatch, task="classify")
    with pytest.raises(ValueError, match="task=detect"):
        check_model(model)


def test_models_cli_local_only(tmp_path, capsys):
    assert main(["models", "catalog"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert set(catalog) == set(PRESETS)
    path, registry = weights(tmp_path), tmp_path / "models.json"
    assert main(["models", "--registry", str(registry), "register", str(path), "--preset", "yolo26s"]) == 0
    capsys.readouterr()
    assert main(["models", "--registry", str(registry), "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["preset"] == "yolo26s"
    assert main(["models", "check", str(tmp_path / "missing.pt")]) == 2


def test_manifest_records_actual_classes_and_selected_options(tmp_path, monkeypatch):
    from tbs.video_test import run
    fixture(tmp_path)
    model = weights(tmp_path)
    fake_ultralytics(monkeypatch)
    path = tmp_path / "video.json"
    path.write_text(json.dumps(dict(video=str(tmp_path / "synthetic.mkv"), detector=str(model),
        detector_sha256=file_hash(model), options=dict(image_size=320, iou=.45, class_ids=[2]))))
    out, report = run(path, tmp_path / "runs")
    card = report["detector_model"]
    assert card["class_names"] == {"2": "car"}
    assert card["options"]["image_size"] == 320
    assert card["sha256"] == report["model_hashes"]["detector"]
    assert json.loads((out / "manifest.json").read_text())["detector_model"] == card


def test_comparison_uses_distinct_processes_same_pts_and_reports_failure(tmp_path, monkeypatch):
    from tbs.model_benchmark import compare_models
    fixture(tmp_path)
    first, second = weights(tmp_path, "one.pt"), weights(tmp_path, "two.pt")
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    # Exercise real subprocesses/decoders/resource sampling with the same
    # deterministic adapter boundary as the worker regression tests.
    (hooks / "sitecustomize.py").write_text(
        "from tbs import detection\nfrom tbs.detection import SyntheticColorDetector\n"
        "def make(config):\n"
        "    if config['models']['detector'].endswith('bad.pt'): raise ValueError('bad fixture model')\n"
        "    return SyntheticColorDetector()\n"
        "detection.make_detector=make\n")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(hooks), str(Path(__file__).resolve().parents[1] / "python")]))
    out, report = compare_models(tmp_path / "synthetic.mkv", [first, second], tmp_path / "output", max_frames=4)
    assert report["status"] == "completed" and report["accuracy_metrics"] is None
    rows = report["models"]
    assert len({row["environment"]["pid"] for row in rows}) == 2
    for row in rows:
        assert row["frames"] == row["detections"] == 4
        assert row["last_pts_s"] == pytest.approx(.3)
        assert row["decode_inference_fps"] > 0
        assert row["peak_rss_bytes"] is None and row["resource_notes"] or row["peak_rss_bytes"] > 0
        assert row["peak_cuda_allocated_bytes"] is None
    with (out / "comparison.csv").open(encoding="utf-8-sig") as handle:
        assert len(list(csv.DictReader(handle))) == 2
    bad = weights(tmp_path, "bad.pt")
    out, report = compare_models(tmp_path / "synthetic.mkv", [bad, first], tmp_path / "output", max_frames=2)
    assert report["status"] == "failed"
    assert [row["status"] for row in report["models"]] == ["failed", "completed"]
    assert "bad fixture" in report["models"][0]["error"]
    assert json.loads((out / "comparison.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("architecture", ["yolo11n", "yolo26n"])
def test_optional_real_yolo_cpu_adapter(tmp_path, architecture):
    # Random initialized local weights verify runtime compatibility, not accuracy.
    ultralytics = pytest.importorskip("ultralytics")
    import torch
    try:
        torch.ones(1).half()
    except RuntimeError as exc:
        if "cpuinfo" in str(exc):
            pytest.skip("Sandbox hides CPU information required by PyTorch; run detector-smoke CI")
        raise
    model = ultralytics.YOLO(architecture + ".yaml")
    path = tmp_path / (architecture + ".pt")
    model.save(path)
    result = check_model(path, dict(device="cpu", image_size=64))
    assert result["model"]["task"] == "detect"
    assert result["model"]["backend_version"] == ultralytics.__version__
    assert result["model"]["class_names"]
