"""Detector boundary: local YOLO weights or a deliberately synthetic fixture."""
import cv2
import numpy as np


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
    def __init__(self, path, options):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ValueError("ยังไม่ได้ติดตั้งส่วนตรวจจับ: เปิด Setup-Detection-Windows.cmd หรือติดตั้ง tbs[detect]") from exc
        self.model = YOLO(path)
        self.options = options

    def detect(self, image):
        result = self.model.predict(image, conf=self.options.get("confidence", 0.25),
                                    classes=self.options.get("class_ids"),
                                    device=self.options.get("device", "cpu"), verbose=False)[0]
        return [(int(cls), float(score), *map(float, box)) for cls, score, box in
                zip(result.boxes.cls.cpu(), result.boxes.conf.cpu(), result.boxes.xyxy.cpu())]


def make_detector(config):
    path = config["models"]["detector"]
    return SyntheticColorDetector() if path == "synthetic_color" else YoloDetector(path, config["options"])
