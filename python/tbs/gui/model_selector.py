"""Shared local-model picker; hashing and inference run off the GUI thread."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QLineEdit, QLabel, QPushButton, QSizePolicy
from ..models import ModelRegistry, PRESETS, check_model
from .preview import TaskService
from .widgets import file_field, MODEL_FILTER


class ModelSelector(QWidget):
    registered = Signal()
    checked = Signal(dict)

    def __init__(self, parent=None, registry=None):
        super().__init__(parent)
        self.registry = registry or ModelRegistry()
        self.options_provider = lambda: {}
        self.image_provider = lambda: None
        self.expected_hash = None
        self.tasks = TaskService(self)
        self.tasks.result.connect(self.finished)
        self.records = []
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.saved = QComboBox()
        self.saved.setToolTip("เลือกไฟล์โมเดลที่ลงทะเบียนไว้ในเครื่องนี้")
        box.addWidget(self.saved)
        self.path = QLineEdit()
        self.path.setPlaceholderText("เลือก local weights เช่น traffic.pt")
        box.addWidget(file_field(self.path, "เลือกโมเดลตรวจจับ", MODEL_FILTER))
        self.profile = QComboBox()
        self.profile.addItem("โมเดลของฉัน / ไม่ระบุรุ่น", "custom")
        for key, preset in PRESETS.items():
            self.profile.addItem(preset["name"], key)
        self.profile.setToolTip("ชื่อโปรไฟล์สำหรับจัดรายการ ไม่ใช่การยืนยันรุ่นหรือการดาวน์โหลด weights")
        box.addWidget(self.profile)
        self.register_button = QPushButton("เพิ่มในรายการ")
        self.check_button = QPushButton("ตรวจและลองโมเดล")
        box.addWidget(self.register_button)
        box.addWidget(self.check_button)
        self.info = QLabel("เลือกไฟล์ในเครื่อง · รองรับ YOLO11 / YOLO26 และ custom detector")
        self.info.setWordWrap(True)
        self.info.setMinimumHeight(64)
        self.info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.info.setObjectName("muted")
        box.addWidget(self.info)
        self.saved.activated.connect(self.select_saved)
        self.path.textChanged.connect(self.path_changed)
        self.register_button.clicked.connect(self.register_current)
        self.check_button.clicked.connect(self.check_current)
        self.profile.currentIndexChanged.connect(self.profile_changed)
        self.refresh()

    def refresh(self):
        try:
            self.records = self.registry.records()
        except (ValueError, OSError) as exc:
            self.records = []
            self.info.setText(str(exc))
        self.saved.clear()
        self.saved.addItem("ไฟล์ที่เลือกเอง / รายการโมเดลในเครื่อง", None)
        for row in self.records:
            self.saved.addItem(f"{row['name']} · {row['format']}", row["id"])

    def select_saved(self, index):
        if index == 0:
            return
        row = self.records[index - 1]
        self.path.setText(row["path"])
        self.expected_hash = row["sha256"]
        self.profile.setCurrentIndex(max(0, self.profile.findData(row["preset"])))
        self.saved.setCurrentIndex(index)
        self.info.setText(f"{row['filename']} · SHA-256 {row['sha256'][:12]}…\nตรวจและลองโมเดลก่อนใช้งาน")

    def path_changed(self):
        self.expected_hash = None
        self.saved.setCurrentIndex(0)
        self.info.setText("ยังไม่ได้ตรวจโมเดลที่เลือก")

    def profile_changed(self):
        preset = PRESETS.get(self.profile.currentData())
        if preset:
            self.info.setText(f"{preset['name']} · เลือกไฟล์ {preset['filename']} ในเครื่อง\n"
                              "โปรไฟล์ COCO: รถยนต์ 2, รถจักรยานยนต์ 3, รถบัส 5, รถบรรทุก 7")

    def set_path(self, path, expected_hash=None):
        self.path.setText(path)
        self.expected_hash = expected_hash

    def busy(self):
        return self.tasks.task is not None or self.tasks.pending is not None

    def begin(self, function):
        self.setEnabled(False)
        self.info.setText("กำลังตรวจโมเดล…")
        self.tasks.request(function)

    def register_current(self):
        path, preset = self.path.text().strip(), self.profile.currentData()
        self.begin(lambda: dict(kind="register", source_path=path, record=self.registry.register(path, preset=preset)))

    def check_current(self):
        try:
            path = self.path.text().strip()
            expected = self.expected_hash
            options, image = self.options_provider(), self.image_provider()
            # Canvas images are RGB; detector inputs follow the pipeline's BGR contract.
            image = image[:, :, ::-1].copy() if image is not None else None
            def check():
                result = check_model(path, options, image, expected)
                result["preview_rgb"] = image[:, :, ::-1].copy() if image is not None else None
                return dict(kind="check", path=path, options=options, result=result)
            self.begin(check)
        except (ValueError, OSError) as exc:
            self.info.setText(str(exc))

    def finished(self, payload, error):
        self.setEnabled(True)
        if error:
            self.info.setText(error)
            return
        if payload["kind"] == "register":
            row = payload["record"]
            self.refresh()
            self.saved.setCurrentIndex(self.saved.findData(row["id"]))
            if payload["source_path"] == self.path.text().strip():
                self.path.setText(row["path"])
                self.expected_hash = row["sha256"]
                self.saved.setCurrentIndex(self.saved.findData(row["id"]))
            self.info.setText("เพิ่มไฟล์ในรายการแล้ว · ยังต้องตรวจ task และลอง inference")
            self.registered.emit()
        else:
            if payload["path"] != self.path.text().strip():
                self.info.setText("ไฟล์ที่เลือกเปลี่ยนไป กรุณาตรวจโมเดลใหม่")
                return
            result = payload["result"]
            info = result["model"]
            self.expected_hash = info["sha256"]
            items = list(info.get("class_names", {}).items())
            names = ", ".join(f"{key}: {value}" for key, value in items[:4])
            if len(items) > 4:
                names += f" … รวม {len(items)} classes (บันทึกครบในผลลัพธ์)"
            self.info.setText(f"ผ่าน inference · {len(result['detections'])} detections\n"
                              f"{info['filename']} · {info['format']} · SHA-256 {info['sha256'][:12]}…\n{names}")
            try:
                same_options = self.options_provider() == payload["options"]
            except ValueError:
                same_options = False
            if same_options:
                self.checked.emit(result)
            else:
                self.info.setText("ตัวเลือกเปลี่ยนระหว่างตรวจ กรุณาลองโมเดลอีกครั้ง")

    def expected_sha256(self):
        return self.expected_hash

    def stop(self):
        return self.tasks.stop()
