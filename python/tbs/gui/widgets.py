"""Compact, reusable controls for detector options and file selection."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QFormLayout, QDoubleSpinBox, QComboBox,
                              QLineEdit, QHBoxLayout, QPushButton, QFileDialog, QSpinBox)
from ..models import detector_options


VIDEO_FILTER = "Videos (*.mp4 *.mkv *.avi *.mov *.m4v *.webm *.ts);;All files (*)"
MODEL_FILTER = "Detector weights (*.pt *.onnx *.engine *.torchscript);;All files (*)"


def file_field(field, title, file_filter, callback=None, directory=False):
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(field, 1)
    browse = QPushButton("เลือก…")
    row.addWidget(browse)
    def choose():
        path = (QFileDialog.getExistingDirectory(wrapper, title, field.text()) if directory else
                QFileDialog.getOpenFileName(wrapper, title, field.text(), file_filter)[0])
        if path:
            field.setText(path)
            if callback:
                callback(path)
    browse.clicked.connect(choose)
    return wrapper


class DetectorOptions(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(0, 1)
        self.confidence.setSingleStep(0.05)
        self.confidence.setDecimals(2)
        self.confidence.setValue(0.25)
        self.device = QComboBox()
        self.device.setEditable(True)
        self.device.addItems(["cpu", "0"])
        self.device.setToolTip("cpu หรือหมายเลข GPU เช่น 0")
        self.classes = QLineEdit()
        self.classes.setPlaceholderText("ทุก class หรือ 2, 3, 5, 7")
        self.classes.setToolTip("ID ตามโมเดลที่เลือก คั่นด้วยเครื่องหมายจุลภาค")
        self.image_size = QSpinBox()
        self.image_size.setRange(32, 4096)
        self.image_size.setSingleStep(32)
        self.image_size.setValue(640)
        self.iou = QDoubleSpinBox()
        self.iou.setRange(0, 1)
        self.iou.setSingleStep(.05)
        self.iou.setValue(.7)
        form.addRow("Confidence", self.confidence)
        form.addRow("Device", self.device)
        form.addRow("Class IDs", self.classes)
        form.addRow("Image size", self.image_size)
        form.addRow("IoU", self.iou)
        self.confidence.valueChanged.connect(self.changed)
        self.device.currentTextChanged.connect(self.changed)
        self.classes.textChanged.connect(self.changed)
        self.image_size.valueChanged.connect(self.changed)
        self.iou.valueChanged.connect(self.changed)

    def values(self):
        device = self.device.currentText().strip()
        if not device:
            raise ValueError("ระบุ Device เช่น cpu หรือ 0")
        values = dict(confidence=self.confidence.value(), device=device)
        text = self.classes.text().strip()
        if text:
            try:
                ids = [int(item.strip()) for item in text.split(",")]
            except ValueError as exc:
                raise ValueError("Class IDs ต้องเป็นจำนวนเต็มคั่นด้วยจุลภาค เช่น 2, 3, 5, 7") from exc
            if len(ids) != len(set(ids)) or any(not 0 <= item <= 32767 for item in ids):
                raise ValueError("Class IDs ต้องไม่ซ้ำ และอยู่ระหว่าง 0–32767")
            values["class_ids"] = ids
        values.update(image_size=self.image_size.value(), iou=self.iou.value())
        return detector_options(values)

    def set_values(self, values):
        values = detector_options(values)
        confidence = values.get("confidence", 0.25)
        device = values.get("device", "cpu")
        classes = values.get("class_ids", [])
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("Confidence ในไฟล์ต้องอยู่ระหว่าง 0 และ 1")
        if not isinstance(device, str) or not device.strip():
            raise ValueError("Device ในไฟล์ต้องเป็นข้อความ เช่น cpu หรือ 0")
        if not isinstance(classes, list) or any(type(key) is not int or not 0 <= key <= 32767 for key in classes) or len(classes) != len(set(classes)):
            raise ValueError("Class IDs ในไฟล์ต้องเป็นจำนวนเต็มที่ไม่ซ้ำ ระหว่าง 0–32767")
        for widget in [self.confidence, self.device, self.classes, self.image_size, self.iou]:
            widget.blockSignals(True)
        self.confidence.setValue(confidence)
        self.device.setCurrentText(device)
        self.classes.setText(", ".join(map(str, classes)))
        self.image_size.setValue(values["image_size"])
        self.iou.setValue(values["iou"])
        for widget in [self.confidence, self.device, self.classes, self.image_size, self.iou]:
            widget.blockSignals(False)

