"""PTS-based player with bounded background decoding and persistent file handles."""
import time
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QComboBox, QSlider, QSizePolicy)
from .preview import Canvas, TaskService
from ..video import VideoReader


def clock(seconds):
    seconds = max(0, seconds)
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


class VideoPlayer(QWidget):
    loaded = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader = VideoReader()
        self.tasks = TaskService(self)
        self.tasks.result.connect(self._result)
        self.path = None
        self.ready = False
        self.position = 0.0
        self.duration = None
        self.at_end = False
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel("เปิดวิดีโอเพื่อดูภาพและเลือกโมเดลทดสอบ")
        self.caption.setWordWrap(True)
        self.caption.setObjectName("muted")
        self.header = QHBoxLayout()
        self.header.addWidget(self.caption, 1)
        box.addLayout(self.header)
        self.canvas = Canvas()
        box.addWidget(self.canvas, 1)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._seek)
        self.slider.sliderPressed.connect(self.pause)
        box.addWidget(self.slider)
        row = QHBoxLayout()
        self.play_button = QPushButton("เล่น")
        self.play_button.clicked.connect(self.toggle_play)
        self.rewind_button = QPushButton("กลับต้น")
        self.rewind_button.clicked.connect(self.rewind)
        self.speed = QComboBox()
        self.speed.addItems(["0.5×", "1×", "2×"])
        self.speed.setCurrentIndex(1)
        self.speed.currentIndexChanged.connect(self._speed_changed)
        self.time_label = QLabel("00:00.000")
        self.time_label.setMinimumWidth(76)
        self.time_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.time_label.setObjectName("muted")
        fit = QPushButton("พอดีภาพ")
        fit.clicked.connect(self.canvas.fit_image)
        for widget in [self.play_button, self.rewind_button, self.speed]:
            row.addWidget(widget)
        row.addWidget(self.time_label, 1)
        row.addWidget(fit)
        box.addLayout(row)
        self.play_button.setEnabled(False)
        self.rewind_button.setEnabled(False)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.setInterval(80)
        self.seek_timer.timeout.connect(lambda: self._request(self.slider.value()/1000))

    def open(self, path):
        self.clear()
        self.path = str(path)
        self.caption.setText("กำลังอ่านวิดีโอ…")
        def load():
            self.reader.close()
            return self.reader.read(path, 0)
        self.tasks.request(load)

    def clear(self):
        self.pause()
        self.seek_timer.stop()
        self.tasks.token += 1
        self.tasks.pending = None
        self.tasks.request(self.reader.close)
        self.path = None
        self.ready = False
        self.position = 0.0
        self.duration = None
        self.at_end = False
        self.canvas.image = None
        self.canvas.detections = []
        self.canvas.lines = []
        self.canvas.matrix = None
        self.canvas.image_draw = self.canvas.image_first = None
        self.canvas.redraw()
        self.slider.blockSignals(True)
        self.slider.setRange(0, 0)
        self.slider.blockSignals(False)
        self.slider.setEnabled(False)
        self.play_button.setEnabled(False)
        self.rewind_button.setEnabled(False)
        self.time_label.setText("00:00.000")
        self.caption.setText("เปิดวิดีโอเพื่อดูภาพและเลือกโมเดลทดสอบ")

    def _request(self, target):
        if self.path:
            path = self.path
            self.tasks.request(lambda: self.reader.read(path, target))

    def _result(self, payload, error):
        if error:
            self.clear()
            self.caption.setText(error)
            self.failed.emit(error)
            return
        if payload is None:
            return
        first = not self.ready
        self.ready = True
        self.position = payload["t_video"]
        self.at_end = payload["eof"]
        self.duration = payload["info"]["duration_s"]
        self.canvas.detections = []
        self.canvas.set_image(payload["image"], fit=first or self.canvas.auto_fit)
        self.play_button.setEnabled(True)
        self.rewind_button.setEnabled(True)
        self.slider.blockSignals(True)
        self.slider.setRange(0, min(2_147_483_647, int(self.duration*1000)) if self.duration else 0)
        self.slider.setValue(int(self.position*1000))
        self.slider.blockSignals(False)
        self.slider.setEnabled(self.duration is not None)
        end = clock(self.duration) if self.duration else "ไม่ทราบระยะเวลา"
        self.time_label.setText(f"{clock(self.position)} / {end}" if self.width() >= 440 else clock(self.position))
        self.time_label.setToolTip(f"{clock(self.position)} / {end}")
        info = payload["info"]
        self.caption.setText(f"{info['width']} × {info['height']} px · PTS {self.position:.3f} s")
        if first:
            self.loaded.emit(info)
        if self.at_end:
            self.pause()

    def pause(self):
        self.timer.stop()
        self.play_button.setText("เล่น")

    def toggle_play(self):
        if self.timer.isActive():
            self.pause()
        elif self.ready:
            self.seek_timer.stop()
            self.play_start = 0.0 if self.at_end else self.slider.value()/1000 if self.slider.isEnabled() else self.position
            self.play_wall = time.monotonic()
            self.at_end = False
            self.play_button.setText("พัก")
            self.timer.start()

    def _speed_changed(self):
        if self.timer.isActive():
            self.play_start = self.position
            self.play_wall = time.monotonic()

    def _tick(self):
        if self.tasks.task is None:
            target = self.play_start+(time.monotonic()-self.play_wall)*[0.5, 1, 2][self.speed.currentIndex()]
            self._request(target)

    def _seek(self):
        self.pause()
        self.at_end = False
        self.seek_timer.start()

    def rewind(self):
        self.pause()
        self.seek_timer.stop()
        self.at_end = False
        self._request(0)

    def stop(self):
        self.pause()
        self.seek_timer.stop()
        if not self.tasks.stop():
            return False
        self.reader.close()
        return True

