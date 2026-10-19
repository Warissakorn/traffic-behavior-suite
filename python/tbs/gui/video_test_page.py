"""Video-first test workspace; no site file or camera calibration required."""
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QSplitter, QPushButton, QScrollArea)
from .video_player import VideoPlayer, clock
from .widgets import DetectorOptions, file_field, VIDEO_FILTER, MODEL_FILTER
from ..video_test import validate_config
from .model_selector import ModelSelector
from .spatial_editor import SpatialEditor


class VideoTestPage(QWidget):
    run_requested = Signal(dict)
    site_requested = Signal(str, str, dict)

    def __init__(self, settings, output_field, parent=None):
        super().__init__(parent)
        self.settings = settings
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        controls = QWidget()
        controls.setMinimumWidth(240)
        controls.setMaximumWidth(480)
        form = QVBoxLayout(controls)
        form.setContentsMargins(12, 12, 12, 12)
        title = QLabel("ทดสอบวิดีโอ")
        title.setObjectName("sectionTitle")
        form.addWidget(title)
        form.addWidget(QLabel("ไฟล์วิดีโอ"))
        self.video_path = QLineEdit()
        self.video_path.setPlaceholderText("เลือกวิดีโอในเครื่อง")
        self.video_path.returnPressed.connect(lambda: self.open_video(self.video_path.text()))
        self.video_path.textEdited.connect(self.invalidate_video)
        form.addWidget(file_field(self.video_path, "เปิดวิดีโอเพื่อทดสอบ", VIDEO_FILTER, self.open_video))
        self.video_info = QLabel("รองรับ MP4, MKV, AVI, MOV และไฟล์ที่ decoder อ่านได้")
        self.video_info.setWordWrap(True)
        self.video_info.setObjectName("muted")
        form.addWidget(self.video_info)
        form.addSpacing(12)
        form.addWidget(QLabel("โมเดลตรวจจับในเครื่อง"))
        self.model_selector = ModelSelector()
        self.model_path = self.model_selector.path
        self.model_path.setText(settings.value("test_model", ""))
        form.addWidget(self.model_selector)
        self.options = DetectorOptions()
        form.addWidget(self.options)
        form.addSpacing(12)
        form.addWidget(QLabel("โฟลเดอร์ผลลัพธ์"))
        form.addWidget(file_field(output_field, "เลือกโฟลเดอร์ผลลัพธ์", "", directory=True))
        self.run_button = QPushButton("ทดสอบ detection ทั้งคลิป")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start_test)
        self.run_button.setEnabled(False)
        self.site_button = QPushButton("ใช้วิดีโอนี้ตั้งค่าจุดสำรวจ")
        self.site_button.clicked.connect(self.use_site)
        self.site_button.setEnabled(False)
        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        note = QLabel("การทดสอบนี้แสดงกรอบ class และ confidence\nเพิ่ม calibration ในหน้าจุดสำรวจเมื่อต้องการ trajectory ความเร็ว และเส้นนับ")
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addWidget(note)
        form.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(controls)
        scroll.setMinimumWidth(240)
        panel = QWidget()
        panel_box = QVBoxLayout(panel)
        panel_box.setContentsMargins(0, 0, 0, 0)
        panel_box.addWidget(scroll, 1)
        footer = QWidget()
        footer_box = QVBoxLayout(footer)
        footer_box.setContentsMargins(12, 6, 12, 10)
        footer_box.addWidget(self.error_label)
        footer_box.addWidget(self.run_button)
        footer_box.addWidget(self.site_button)
        panel_box.addWidget(footer)
        self.player = VideoPlayer()
        self.spatial_editor = SpatialEditor(self.player.canvas, allow_points=False)
        self.spatial_editor.changed.connect(self.clear_model_preview)
        self.spatial_editor.drawing_started.connect(self.player.pause)
        form.addWidget(self.spatial_editor)
        self.model_selector.options_provider = self.options.values
        self.model_selector.image_provider = lambda: self.player.canvas.image
        self.model_selector.regions_provider = self.spatial_editor.values
        self.model_selector.checked.connect(self.show_model_preview)
        self.options.changed.connect(self.clear_model_preview)
        self.model_path.textChanged.connect(self.clear_model_preview)
        self.player.loaded.connect(self.loaded)
        self.player.failed.connect(self.failed)
        self.panel_toggle = QPushButton("แผงตั้งค่า")
        self.panel_toggle.setCheckable(True)
        self.panel_toggle.setChecked(True)
        self.panel_toggle.toggled.connect(panel.setVisible)
        self.player.header.addWidget(self.panel_toggle)
        self.split.addWidget(panel)
        self.split.addWidget(self.player)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([310, 800])
        state = settings.value("video_split")
        if state is not None:
            self.split.restoreState(state)
        box.addWidget(self.split, 1)

    def open_video(self, path):
        if not str(path).strip():
            self.failed("เลือกไฟล์วิดีโอก่อน")
            return
        self.video_path.setText(str(Path(path).expanduser().resolve()))
        self.invalidate_video()
        self.video_info.setText("กำลังอ่านวิดีโอ…")
        self.player.open(self.video_path.text())

    def invalidate_video(self):
        self.player.clear()
        self.run_button.setEnabled(False)
        self.site_button.setEnabled(False)
        self.error_label.clear()
        self.error_label.hide()

    def loaded(self, info):
        duration = clock(info["duration_s"]) if info["duration_s"] else "ไม่ทราบระยะเวลา"
        self.video_info.setText(f"{info['width']} × {info['height']} px · {duration}")
        self.error_label.clear()
        self.error_label.hide()
        self.run_button.setEnabled(True)
        self.site_button.setEnabled(True)

    def failed(self, error):
        self.error_label.setText(error)
        self.error_label.show()
        self.run_button.setEnabled(False)
        self.site_button.setEnabled(False)

    def start_test(self):
        try:
            if self.model_selector.busy():
                raise ValueError("รอการตรวจโมเดลให้เสร็จก่อน")
            if not self.player.ready:
                raise ValueError("เปิดวิดีโอให้สำเร็จก่อนเริ่มทดสอบ")
            config = validate_config(dict(video=self.video_path.text(), detector=self.model_path.text(),
                                          detector_sha256=self.model_selector.expected_sha256(),
                                          options=self.options.values(), image_regions=self.spatial_editor.values()))
            self.settings.setValue("test_model", config["detector"])
            self.player.pause()
            self.error_label.clear()
            self.error_label.hide()
            self.run_requested.emit(config)
        except (ValueError, OSError) as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()

    def use_site(self):
        try:
            self.site_requested.emit(self.video_path.text(), self.model_path.text(), self.options.values())
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()

    def save_state(self):
        self.settings.setValue("video_split", self.split.saveState())

    def show_model_preview(self, result):
        self.player.pause()
        same_frame = self.player.ready and result.get("preview_rgb") is not None and np.array_equal(
            self.player.canvas.image, result["preview_rgb"])
        self.player.canvas.detections = result["detections"] if same_frame else []
        self.player.canvas.redraw()

    def clear_model_preview(self):
        self.player.canvas.detections = []
        self.player.canvas.redraw()

