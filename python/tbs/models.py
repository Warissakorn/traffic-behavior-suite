"""Local detector catalog and registry. Catalog entries never download weights."""
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading

PRESETS = {
    f"{family}{scale}": {"name": f"{label}{scale}", "filename": f"{family}{scale}.pt",
                         "task": "detect", "dataset": "COCO", "vehicle_class_ids": [2, 3, 5, 7]}
    for family, label in [("yolo11", "YOLO11"), ("yolo26", "YOLO26")]
    for scale in ("n", "s", "m")
}
FORMATS = {".pt", ".onnx", ".engine", ".torchscript"}
_REGISTRY_LOCK = threading.RLock()


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def model_path(path):
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ValueError("เลือกไฟล์โมเดลในเครื่องก่อน")
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"ไม่พบไฟล์โมเดล: {path}")
    if path.suffix.lower() not in FORMATS or path.stat().st_size == 0:
        raise ValueError("โมเดลต้องเป็นไฟล์ .pt, .onnx, .engine หรือ .torchscript ที่ไม่ว่าง")
    return path


def local_model(path, expected_sha256=None):
    path = model_path(path)
    digest = file_hash(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("ไฟล์โมเดลเปลี่ยนจากที่บันทึกไว้ กรุณาตรวจและลงทะเบียนใหม่")
    return dict(path=str(path), filename=path.name, format=path.suffix.lower()[1:],
                size_bytes=path.stat().st_size, sha256=digest)


def detector_options(options):
    """Validate only detector options; site tracking options remain independent."""
    if not isinstance(options, dict):
        raise ValueError("ตัวเลือกโมเดลต้องเป็น object")
    result = dict(options)
    for key, default in [("confidence", .25), ("iou", .7)]:
        value = options.get(key, default)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key} ต้องอยู่ระหว่าง 0 และ 1")
        result[key] = value
    size = options.get("image_size", 640)
    if type(size) is not int or not 32 <= size <= 4096 or size % 32:
        raise ValueError("Image size ต้องเป็นจำนวนเต็มที่หาร 32 ลงตัว ระหว่าง 32–4096")
    device = options.get("device", "cpu")
    if not isinstance(device, str) or not device.strip():
        raise ValueError("ระบุ device เช่น cpu หรือ 0")
    classes = options.get("class_ids")
    if classes is not None and (not isinstance(classes, list) or
            any(type(key) is not int or not 0 <= key <= 32767 for key in classes) or
            len(classes) != len(set(classes))):
        raise ValueError("Class IDs ต้องเป็นจำนวนเต็มที่ไม่ซ้ำกัน ระหว่าง 0–32767")
    result.update(image_size=size, device=device.strip())
    if type(options.get('half', False)) is not bool:
        raise ValueError('half ต้องเป็น boolean')
    result['half'] = options.get('half', False)
    return result


class ModelRegistry:
    def __init__(self, path=None):
        if path is None:
            from .app_paths import data_dir
            path = data_dir() / "models.json"
        self.path = Path(path)

    def records(self):
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("models"), list):
                raise ValueError("Unsupported registry schema")
            ids = set()
            for row in data["models"]:
                if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key]
                        for key in ["id", "name", "path", "sha256", "preset"]):
                    raise ValueError("Invalid model record")
                if row["id"] in ids or len(row["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["sha256"]):
                    raise ValueError("Invalid model ID/hash")
                if row.get("format") not in {suffix[1:] for suffix in FORMATS} or row.get("task") != "detect":
                    raise ValueError("Invalid model format/task")
                if row["preset"] != "custom" and row["preset"] not in PRESETS:
                    raise ValueError("Unknown model preset")
                ids.add(row["id"])
            return data["models"]
        except (ValueError, TypeError) as exc:
            raise ValueError(f"อ่านทะเบียนโมเดลไม่ได้: {self.path}: {exc}") from exc

    def register(self, path, name=None, preset="custom"):
        with _REGISTRY_LOCK:
            return self._register(path, name, preset)

    def _register(self, path, name, preset):
        if preset != "custom" and preset not in PRESETS:
            raise ValueError("Unknown detector preset")
        info = local_model(path)
        row = dict(info, id=hashlib.sha256(info["path"].encode()).hexdigest()[:16],
                   name=(name or info["filename"]).strip(), preset=preset, task="detect",
                   validation="file_only")
        if not row["name"]:
            raise ValueError("Model name must not be empty")
        rows = [old for old in self.records() if old["id"] != row["id"]] + [row]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name, suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(dict(schema_version=1, models=rows), handle, indent=2, ensure_ascii=False)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return row


def describe_detector(detector, path, options, expected_sha256=None):
    if path == "synthetic_color":
        info = dict(filename=path, format="synthetic", sha256="synthetic-color-v1",
                    task="synthetic", class_names={"0": "synthetic_rectangle"})
    else:
        metadata = getattr(detector, "metadata", {})
        info = dict(metadata) if "sha256" in metadata else local_model(path, expected_sha256)
        info.update(metadata)
        if expected_sha256 is not None and info["sha256"] != expected_sha256:
            raise ValueError("Model SHA-256 mismatch")
    info["options"] = detector_options(options)
    return info


def check_model(path, options=None, image=None, expected_sha256=None):
    """Run real adapter inference once; file registration alone is not validation."""
    import numpy as np
    from .detection import make_detector
    options = detector_options(options or {})
    local_model(path, expected_sha256)
    detector = make_detector(dict(models=dict(detector=str(path), detector_sha256=expected_sha256), options=options))
    image = np.zeros((640, 640, 3), dtype=np.uint8) if image is None else image
    detections = detector.detect(image)
    info = describe_detector(detector, path, options, expected_sha256)
    return dict(model=info, detections=[dict(class_id=cls, score=score, x1=x1, y1=y1, x2=x2, y2=y2,
                                            track_id=None) for cls, score, x1, y1, x2, y2 in detections])
