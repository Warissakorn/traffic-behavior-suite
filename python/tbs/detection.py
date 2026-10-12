"""Detector boundary: local YOLO weights or a deliberately synthetic fixture."""
import cv2
import numpy as np
from importlib.metadata import version
from .models import local_model, detector_options


class SyntheticColorDetector:
    """Bright green rectangles only. Never a traffic vehicle detector."""
    def detect(self, image):
        mask = cv2.inRange(image, np.array([0, 180, 0], dtype=np.uint8), np.array([100, 255, 100], dtype=np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        result = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h >= 25:
                result.append((0, 1.0, float(x), float(y), float(x+w), float(y+h)))
        return sorted(result, key=lambda item: item[2])


class YoloDetector:
    def __init__(self, path, options, expected_sha256=None):
        info = local_model(path, expected_sha256)
        self.options = detector_options(options)
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ValueError("ยังไม่ได้ติดตั้งส่วนตรวจจับ: เปิด Setup-Detection-Windows.cmd หรือติดตั้ง tbs[detect]") from exc
        try:
            self.model = YOLO(info["path"])
        except Exception as exc:
            raise ValueError(f"โหลดโมเดลไม่ได้: {info['filename']}: {exc}") from exc
        if self.model.task != "detect":
            raise ValueError(f"ต้องใช้โมเดล task=detect; ไฟล์นี้เป็น {self.model.task}")
        self.metadata = dict(info, task="detect", backend="ultralytics", backend_version=version("ultralytics"))
        architecture = getattr(getattr(self.model, "model", None), "yaml", {})
        if isinstance(architecture, dict) and architecture.get("yaml_file"):
            self.metadata["architecture"] = str(architecture["yaml_file"])

    def detect(self, image):
        result = self.model.predict(image, conf=self.options.get("confidence", 0.25),
                                    iou=self.options["iou"], imgsz=self.options["image_size"],
                                    classes=self.options.get("class_ids"),
                                    device=self.options.get("device", "cpu"), verbose=False)[0]
        names = result.names
        self.metadata["class_names"] = {str(key): str(value) for key, value in
                                        (names.items() if isinstance(names, dict) else enumerate(names))}
        ids = self.options.get("class_ids")
        if ids is not None and any(str(key) not in self.metadata["class_names"] for key in ids):
            raise ValueError("Class IDs ไม่มีอยู่ในโมเดลที่เลือก")
        return [(int(cls), float(score), *map(float, box)) for cls, score, box in
                zip(result.boxes.cls.cpu(), result.boxes.conf.cpu(), result.boxes.xyxy.cpu())]


def make_detector(config):
    path = config["models"]["detector"]
    return SyntheticColorDetector() if path == "synthetic_color" else YoloDetector(
        path, config["options"], config["models"].get("detector_sha256"))

