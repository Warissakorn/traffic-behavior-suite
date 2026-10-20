"""Thai desktop workspaces for video tests and calibrated site analysis."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import time
import numpy as np
import yaml
from PySide6.QtCore import Qt, QTimer, QUrl, QSettings
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QListWidget, QStackedWidget, QTabWidget, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QSplitter, QPlainTextEdit, QProgressBar,
    QSlider, QAbstractItemView, QComboBox, QScrollArea, QHeaderView)
from ..app_paths import data_dir
from ..diagnostics import report as diagnostics
from ..video import VideoReader, probe_video, check_playlist
from ..camera_calibration import camera_matrix, check_image_size
from .job_controller import JobController
from .site_document import SiteDocument
from .preview import Canvas, TaskService
from .result_store import ResultStore
from .video_player import VideoPlayer
from .video_test_page import VideoTestPage
from .widgets import DetectorOptions, VIDEO_FILTER, MODEL_FILTER, file_field
from .theme import STYLE
from .model_selector import ModelSelector
from .reid_page import ReIDPage
from .spatial_editor import SpatialEditor
from .camera_dialog import CameraDialog
from .wheel_guard import install_wheel_guard
from .clip_import import ClipImportDialog
from .resume_dialog import ResumeDialog


def button(text, callback):
    value = QPushButton(text)
    value.clicked.connect(callback)
    return value


def table(headers):
    value = QTableWidget(0, len(headers))
    value.setHorizontalHeaderLabels(headers)
    value.horizontalHeader().setStretchLastSection(True)
    value.verticalHeader().setVisible(False)
    value.setAlternatingRowColors(True)
    value.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    return value


def display_table(widget, rows):
    headers = list(rows[0]) if rows else []
    widget.setColumnCount(len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setRowCount(len(rows))
    for i,row in enumerate(rows):
        for j,key in enumerate(headers):
            value = row[key]
            text = "ยังไม่คำนวณ" if value is None or (key in {"lane_id","leader_id"} and value == -1) else str(value)
            widget.setItem(i,j,QTableWidgetItem(text))
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        install_wheel_guard()
        self.setWindowTitle("Traffic Behavior Suite · Windows Test")
        self.resize(1280,800)
        self.setMinimumSize(840,500)
        self.setStyleSheet(STYLE)
        self.document = SiteDocument()
        self.dirty = False
        self.loading = False
        self.store = None
        self.offset = 0
        self.job = JobController(self)
        self.job.event.connect(self.on_event)
        self.job.log.connect(self.append_log)
        self.job.finished.connect(self.on_finished)
        self.preview_tasks = TaskService(self)
        self.preview_tasks.result.connect(self.preview_loaded)
        self.result_tasks = TaskService(self)
        self.result_tasks.result.connect(self.result_loaded)
        self.export_tasks = TaskService(self)
        self.export_tasks.result.connect(self.export_finished)
        self.validation_tasks = TaskService(self)
        self.validation_tasks.result.connect(self.validated)
        self.import_tasks = TaskService(self)
        self.import_tasks.result.connect(self.videos_imported)
        self.review_reader = VideoReader()
        self.settings = QSettings("TrafficBehaviorSuite", "DesktopTest")
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(30)
        self.play_timer.timeout.connect(self.play_next)
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.setInterval(80)
        self.seek_timer.timeout.connect(self.request_review)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 6)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.nav_toggle = button("เมนู", self.toggle_navigation)
        header.addWidget(self.nav_toggle)
        title = QLabel("Traffic Behavior Suite")
        title.setObjectName("brand")
        header.addWidget(title)
        header.addStretch()
        self.site_label = QLabel("จุดสำรวจ")
        self.site_label.setObjectName("muted")
        header.addWidget(button("เปิดวิดีโอ", self.open_test_video))
        header.addWidget(button("เปิดจุดสำรวจ", self.open_site))
        header.addWidget(button("บันทึก site", self.save_site))
        layout.addLayout(header)
        body = QHBoxLayout()
        self.nav = QListWidget()
        self.nav.setObjectName("navigation")
        self.nav.addItems(["ทดสอบวิดีโอ", "จุดสำรวจ", "ประมวลผล", "ผลลัพธ์", "จับคู่รถ / OD"])
        self.nav.setFixedWidth(126)
        self.stack = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.stack,1)
        layout.addLayout(body)
        self.setCentralWidget(root)
        for page in [self.start_page(), self.setup_page(), self.run_page(), self.results_page()]:
            self.stack.addWidget(page)
        self.reid_page = ReIDPage(self.output_path)
        self.stack.addWidget(self.reid_page)
        self.nav.currentRowChanged.connect(self.change_workspace)
        self.start_tabs.currentChanged.connect(lambda index: self.video_page.player.pause() if index != 0 else None)
        self.result_tabs.currentChanged.connect(lambda index: self.pause_review() if index != 2 else None)
        self.nav.setCurrentRow(0)
        self.statusBar().addPermanentWidget(self.site_label)
        self.statusBar().showMessage("พร้อม · เปิดวิดีโอเพื่อเริ่มทดสอบ")
        self.populate()
        self.model_selector.registered.connect(self.video_page.model_selector.refresh)
        self.video_page.model_selector.registered.connect(self.model_selector.refresh)
        self.model_selector.registered.connect(self.changed)
        self.model_selector.checked.connect(lambda _: self.changed())
        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.nav.setVisible(self.settings.value("navigation_visible", True, type=bool))

    def start_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.start_tabs = QTabWidget()
        self.output_path = QLineEdit(self.settings.value("output", str(data_dir()/"output")))
        self.video_page = VideoTestPage(self.settings, self.output_path)
        self.video_page.run_requested.connect(self.start_video_test)
        self.video_page.site_requested.connect(self.site_from_video)
        self.start_tabs.addTab(self.video_page, "วิดีโอจริง")
        tools = QWidget()
        tools_box = QVBoxLayout(tools)
        intro = QLabel("ทดสอบระบบด้วยข้อมูลจำลอง หรือเปิดจุดสำรวจที่บันทึกไว้")
        intro.setWordWrap(True)
        intro.setObjectName("sectionTitle")
        tools_box.addWidget(intro)
        row = QHBoxLayout()
        self.demo_button = button("ทดสอบตัวอย่าง", self.start_demo)
        self.demo_button.setObjectName("primary")
        row.addWidget(self.demo_button)
        row.addWidget(button("สร้างจุดสำรวจ", self.new_site))
        row.addWidget(button("เปิดผลลัพธ์เดิม", self.open_result))
        tools_box.addLayout(row)
        self.demo_output = QLabel("ผลลัพธ์: " + self.output_path.text())
        self.demo_output.setWordWrap(True)
        self.output_path.textChanged.connect(lambda text: self.demo_output.setText("ผลลัพธ์: " + text))
        tools_box.addWidget(self.demo_output)
        self.recent = QListWidget()
        for path in self.settings.value("recent", [], type=list):
            self.recent.addItem(path)
        self.recent.itemDoubleClicked.connect(lambda item: self.open_site(path=item.text()))
        tools_box.addWidget(QLabel("จุดสำรวจล่าสุด · ดับเบิลคลิกเพื่อเปิด"))
        tools_box.addWidget(self.recent, 1)
        tools_box.addWidget(button("คัดลอกข้อมูลเครื่องสำหรับตรวจปัญหา", self.copy_diagnostics))
        note = QLabel("Demo ใช้สี่เหลี่ยมจำลอง · ความแม่นยำกับรถจริงต้องทดสอบกับข้อมูลอ้างอิง")
        note.setWordWrap(True)
        note.setObjectName("muted")
        tools_box.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tools)
        self.start_tabs.addTab(scroll, "ตัวอย่าง / ล่าสุด")
        box.addWidget(self.start_tabs, 1)
        return page

    def path_widget(self, field, directory=False, callback=None):
        file_filter = MODEL_FILTER if field is getattr(self, "model_path", None) else "YAML (*.yaml *.yml);;All files (*)"
        return file_field(field, "เลือกโฟลเดอร์" if directory else "เลือกไฟล์", file_filter,
                          (lambda _: callback()) if callback else None, directory)

    def setup_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.setup_toggle = QPushButton("แผงตั้งค่า")
        self.setup_toggle.setCheckable(True)
        self.setup_toggle.setChecked(True)
        top.addWidget(self.setup_toggle)
        self.site_id, self.epoch = QLineEdit(), QLineEdit()
        self.site_id.setMaximumWidth(140)
        self.epoch.setPlaceholderText("2026-10-12T07:00:00+07:00")
        self.epoch.setToolTip("เวลาเริ่มอ้างอิง ต้องมี timezone เช่น +07:00")
        top.addWidget(QLabel("Site"))
        top.addWidget(self.site_id)
        top.addWidget(QLabel("เวลาอ้างอิง"))
        top.addWidget(self.epoch, 1)
        box.addLayout(top)
        self.setup_split = QSplitter(Qt.Orientation.Horizontal)
        self.setup_split.setChildrenCollapsible(False)
        tabs = QTabWidget()
        tabs.setMinimumWidth(260)
        videos = QWidget()
        vbox = QVBoxLayout(videos)
        self.videos = table(["ไฟล์วิดีโอ", "เวลาเริ่มเฟรมแรก (timezone)"])
        self.videos.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.videos.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.videos.setColumnWidth(1, 180)
        self.videos.itemSelectionChanged.connect(lambda: self.load_preview() if not self.loading else None)
        vbox.addWidget(self.videos)
        row = QHBoxLayout()
        self.add_video_button = button("นำเข้าชุดคลิป…",self.add_videos)
        row.addWidget(self.add_video_button)
        row.addWidget(button("ลบ",lambda: self.remove_row(self.videos)))
        row.addWidget(button("ขึ้น",lambda: self.move_video(-1)))
        row.addWidget(button("ลง",lambda: self.move_video(1)))
        vbox.addLayout(row)
        tabs.addTab(videos,"วิดีโอ")
        camera = QWidget()
        form = QFormLayout(camera)
        self.camera_path = QLineEdit()
        form.addRow("Camera YAML",self.path_widget(self.camera_path,callback=self.load_preview))
        self.create_camera_button = button("สร้าง Camera YAML จากภาพ…", self.create_camera)
        form.addRow(self.create_camera_button)
        hint = QLabel("ใช้ planar homography เพื่อแปลงพิกัดภาพเป็นเมตร\nภาพต้องผ่าน undistort แล้ว")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        form.addRow(hint)
        form.addRow(button("โหลดภาพและ calibration",self.load_preview))
        tabs.addTab(camera,"กล้อง")
        lines = QWidget()
        lbox = QVBoxLayout(lines)
        self.lines = table(["ID", "p1 x (ม.)", "p1 y (ม.)", "p2 x (ม.)", "p2 y (ม.)"])
        self.lines.itemSelectionChanged.connect(self.select_line)
        lbox.addWidget(self.lines)
        row = QHBoxLayout()
        row.addWidget(button("เพิ่มเส้น",self.add_line))
        row.addWidget(button("วาด 2 จุดบนภาพ",self.draw_line))
        row.addWidget(button("ลบเส้น",lambda: self.remove_row(self.lines)))
        lbox.addLayout(row)
        hint = QLabel("เลือกเส้นเพื่อเลื่อนจุดปลาย · ล้อเมาส์ซูม · ลากภาพเพื่อเลื่อน")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        lbox.addWidget(hint)
        tabs.addTab(lines,"เส้นนับ")
        model = QWidget()
        form = QFormLayout(model)
        self.model_selector = ModelSelector()
        self.model_path = self.model_selector.path
        form.addRow(self.model_selector)
        self.model_options = DetectorOptions()
        self.model_options.changed.connect(self.changed)
        form.addRow(self.model_options)
        self.options = QPlainTextEdit()
        self.options.setMinimumHeight(100)
        form.addRow("Tracking (JSON)",self.options)
        hint = QLabel("Class IDs อ้างอิงโมเดลที่เลือก · CPU เป็นค่าเริ่มต้น")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        form.addRow(hint)
        model_scroll = QScrollArea()
        model_scroll.setWidgetResizable(True)
        model_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        model_scroll.setWidget(model)
        tabs.addTab(model_scroll,"โมเดล")
        self.setup_player = VideoPlayer()
        self.model_selector.options_provider = self.model_options.values
        self.model_selector.image_provider = lambda: self.setup_player.canvas.image
        self.setup_canvas = self.setup_player.canvas
        self.spatial_editor = SpatialEditor(self.setup_canvas)
        self.model_selector.regions_provider = self.spatial_editor.values
        self.spatial_editor.changed.connect(self.changed)
        self.spatial_editor.drawing_started.connect(self.setup_player.pause)
        spatial_scroll = QScrollArea()
        spatial_scroll.setWidgetResizable(True)
        spatial_scroll.setWidget(self.spatial_editor)
        tabs.addTab(spatial_scroll, 'พื้นที่ / จุดผ่าน')
        self.setup_canvas.line_changed.connect(self.line_changed)
        self.setup_canvas.problem.connect(self.show_error)
        self.setup_player.failed.connect(lambda text: self.validation_label.setText(text))
        self.setup_player.loaded.connect(lambda _: self.apply_camera_preview())
        self.setup_controls = tabs
        self.setup_controls.setMinimumWidth(260)
        self.setup_split.addWidget(self.setup_controls)
        self.setup_split.addWidget(self.setup_player)
        self.setup_split.setStretchFactor(0, 0)
        self.setup_split.setStretchFactor(1, 1)
        self.setup_split.setSizes([320,760])
        state = self.settings.value("setup_split")
        if state is not None:
            self.setup_split.restoreState(state)
        self.setup_toggle.toggled.connect(self.setup_controls.setVisible)
        box.addWidget(self.setup_split,1)
        self.validation_label = QLabel("ยังไม่ได้ตรวจความพร้อม")
        self.validation_label.setWordWrap(True)
        self.validation_label.setObjectName("muted")
        box.addWidget(self.validation_label)
        row = QHBoxLayout()
        row.addWidget(button("ตรวจความพร้อม",self.validate_site))
        self.run_button = button("ประมวลผลจุดสำรวจนี้",self.start_site)
        self.run_button.setObjectName("primary")
        row.addWidget(self.run_button)
        box.addLayout(row)
        for field in [self.site_id,self.epoch,self.camera_path,self.model_path]:
            field.textChanged.connect(self.changed)
        self.videos.itemChanged.connect(self.changed)
        self.lines.itemChanged.connect(self.changed)
        self.options.textChanged.connect(self.changed)
        return page

    def run_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.run_title = QLabel("พร้อมเริ่มงาน")
        self.run_title.setObjectName("sectionTitle")
        box.addWidget(self.run_title)
        self.progress = QProgressBar()
        box.addWidget(self.progress)
        self.counters = QLabel("Frames: 0 · Detections: 0")
        box.addWidget(self.counters)
        self.clip_progress = QLabel('คลิป: —')
        self.clip_progress.setWordWrap(True)
        box.addWidget(self.clip_progress)
        row = QHBoxLayout()
        self.pause_button = button('พักงาน / บันทึกจุดทำต่อ', self.pause_job)
        self.pause_button.setEnabled(False)
        self.resume_button = button('งานที่พักไว้ / ทำต่อ…', self.resume_job)
        self.cancel_button = button("ยกเลิก",self.cancel_job)
        self.force_button = button("หยุดแบบบังคับ",self.force_job)
        self.cancel_button.setEnabled(False)
        self.force_button.setEnabled(False)
        row.addWidget(self.pause_button)
        row.addWidget(self.resume_button)
        row.addWidget(self.cancel_button)
        row.addWidget(self.force_button)
        row.addWidget(button("เปิดโฟลเดอร์ผลลัพธ์",self.open_output))
        box.addLayout(row)
        self.clip_jobs = table(['คลิป', 'เวลาเริ่ม', 'สถานะ'])
        self.clip_jobs.setMaximumHeight(170)
        box.addWidget(self.clip_jobs)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(2000)
        box.addWidget(self.log,1)
        return page

    def results_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("เปิดผลลัพธ์ที่ประมวลผลสำเร็จเพื่อดูข้อมูล")
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        self.point_filter = QComboBox()
        self.point_filter.addItem('รถทุกคัน', None)
        self.point_filter.currentIndexChanged.connect(self.filter_point)
        box.addWidget(QLabel('เลือกเฉพาะรถที่ผ่านจุด'))
        box.addWidget(self.point_filter)
        self.result_tabs = tabs = QTabWidget()
        counts = QWidget()
        counts_box = QVBoxLayout(counts)
        self.counts_note = QLabel("จำนวน detection รวมทุกเฟรม แยกตาม class · ไม่ใช่จำนวนรถไม่ซ้ำ")
        self.counts_note.setWordWrap(True)
        self.counts_note.setObjectName("muted")
        self.counts_note.hide()
        counts_box.addWidget(self.counts_note)
        self.counts_table = table([])
        counts_box.addWidget(self.counts_table,1)
        tabs.addTab(counts,"การนับ")
        samples = QWidget()
        vbox = QVBoxLayout(samples)
        row = QHBoxLayout()
        self.dataset = QComboBox()
        self.dataset.addItems(["vehicles","trajectories","line_crossings"])
        self.dataset.currentTextChanged.connect(self.reset_page)
        row.addWidget(self.dataset)
        row.addWidget(button("หน้าก่อน",lambda: self.change_page(-200)))
        row.addWidget(button("หน้าถัดไป",lambda: self.change_page(200)))
        self.page_label = QLabel("0–0")
        row.addWidget(self.page_label)
        vbox.addLayout(row)
        self.results_table = table([])
        vbox.addWidget(self.results_table)
        tabs.addTab(samples,"ตารางข้อมูล")
        review = QWidget()
        rbox = QVBoxLayout(review)
        self.review_canvas = Canvas()
        rbox.addWidget(self.review_canvas,1)
        row = QHBoxLayout()
        self.play_button = button("เล่น / หยุด",self.toggle_play)
        row.addWidget(self.play_button)
        self.speed = QComboBox()
        self.speed.addItems(["0.5×","1×","2×"])
        self.speed.setCurrentIndex(1)
        self.speed.currentIndexChanged.connect(self.review_speed_changed)
        row.addWidget(self.speed)
        self.review_label = QLabel("Frame 0 · PTS 0 s")
        row.addWidget(self.review_label)
        row.addStretch()
        row.addWidget(button("พอดีภาพ",self.review_canvas.fit_image))
        self.review_slider = QSlider(Qt.Orientation.Horizontal)
        self.review_slider.setRange(0,0)
        self.review_slider.valueChanged.connect(self.seek_review)
        rbox.addLayout(row)
        rbox.addWidget(self.review_slider)
        tabs.addTab(review,"ภาพ + overlay")
        self.result_diagnostics = QPlainTextEdit()
        self.result_diagnostics.setReadOnly(True)
        tabs.addTab(self.result_diagnostics,"รายละเอียด run")
        box.addWidget(tabs,1)
        row = QHBoxLayout()
        row.addWidget(button("เปิดผลลัพธ์",self.open_result))
        row.addWidget(button("ส่งออก CSV",self.export_csv))
        row.addWidget(button("เปิดโฟลเดอร์",self.open_output))
        box.addLayout(row)
        return page

    def changed(self,*args):
        if not self.loading:
            self.dirty = True
            self.validation_tasks.token += 1
            self.validation_tasks.pending = None
            self.run_button.setEnabled(not self.job.active)
            self.validation_label.setText("มีการแก้ไข · ตรวจความพร้อมอีกครั้งก่อนรัน")

    def toggle_navigation(self):
        self.nav.setVisible(self.nav.isHidden())

    def pause_review(self):
        self.play_timer.stop()
        self.play_button.setText("เล่น")

    def change_workspace(self, index):
        self.stack.setCurrentIndex(index)
        if index != 0:
            self.video_page.player.pause()
        if index != 1:
            self.setup_player.pause()
        if index != 3:
            self.pause_review()

    def open_test_video(self, checked=False, path=None):
        path = path or QFileDialog.getOpenFileName(self, "เปิดวิดีโอเพื่อทดสอบ", filter=VIDEO_FILTER)[0]
        if path:
            self.nav.setCurrentRow(0)
            self.start_tabs.setCurrentIndex(0)
            self.video_page.open_video(path)

    def site_from_video(self, path, model, options):
        if not self.confirm_discard():
            return
        self.document = SiteDocument()
        self.document.config["videos"] = [dict(path=path, start_time=self.document.config["epoch"])]
        self.document.config["models"]["detector"] = model
        expected = self.video_page.model_selector.expected_sha256()
        if expected:
            self.document.config["models"]["detector_sha256"] = expected
        self.document.config["options"].update(options)
        self.document.config['image_regions'] = self.video_page.spatial_editor.values()
        self.populate()
        self.dirty = True
        self.nav.setCurrentRow(1)
        self.load_preview()

    def start_video_test(self, config):
        if self.job.active:
            return
        try:
            from .site_document import atomic_text
            snapshot = data_dir()/"sessions"/f"video-{time.time_ns()}.json"
            atomic_text(snapshot, json.dumps(config, ensure_ascii=False))
            if self.prepare_run():
                self.job.start(self.output_path.text(), video_test=snapshot)
        except Exception as exc:
            self.on_finished("failed",str(exc))

    def populate(self):
        self.loading = True
        c = self.document.config
        self.site_id.setText(c.get("site_id",""))
        self.epoch.setText(c.get("epoch",c.get("videos",[{}])[0].get("start_time","") if c.get("videos") else ""))
        self.camera_path.setText(c.get("camera",{}).get("model_file",""))
        self.model_selector.set_path(c.get("models",{}).get("detector",""),
                                     c.get("models",{}).get("detector_sha256"))
        options = c.get("options",{})
        self.model_options.set_values(options)
        self.spatial_editor.set_regions(c.get('image_regions'))
        self.options.setPlainText(json.dumps({key:value for key,value in options.items()
            if key not in {"confidence", "device", "class_ids", "image_size", "iou", "half"}},indent=2))
        self.videos.setRowCount(0)
        for clip in c.get("videos",[]):
            self.append_row(self.videos,[clip.get("path",""),clip.get("start_time","")])
            self.videos.item(self.videos.rowCount()-1, 0).setData(Qt.ItemDataRole.UserRole, dict(clip))
        self.lines.setRowCount(0)
        for line in c.get("road",{}).get("count_lines",[]):
            self.append_row(self.lines,[line["id"],*line["p1"],*line["p2"]])
        self.loading = False
        self.dirty = False
        self.site_label.setText("Site: " + c.get("site_id",""))

    def collect(self):
        c = deepcopy(self.document.config)
        c["site_id"],c["epoch"] = self.site_id.text().strip(),self.epoch.text().strip()
        c["videos"] = [{"path":self.cell(self.videos,i,0),"start_time":self.cell(self.videos,i,1)} for i in range(self.videos.rowCount())]
        for index, clip in enumerate(c['videos']):
            previous = self.videos.item(index, 0).data(Qt.ItemDataRole.UserRole) or {}
            if previous.get('start_time') == clip['start_time']:
                clip.update({key: previous[key] for key in ('time_source', 'time_format', 'interval_s') if key in previous})
            elif previous.get('time_source'):
                clip['time_source'] = 'manual'
        c.setdefault("camera",{})["model_file"] = self.camera_path.text().strip()
        c.setdefault("models",{})["detector"] = self.model_path.text().strip()
        c["models"].pop("detector_sha256", None)
        if self.model_selector.expected_sha256():
            c["models"]["detector_sha256"] = self.model_selector.expected_sha256()
        c["options"] = json.loads(self.options.toPlainText())
        if not isinstance(c["options"], dict):
            raise ValueError("ตัวเลือกขั้นสูงต้องเป็น JSON object")
        for key in ["confidence", "device", "class_ids", "image_size", "iou", "half"]:
            c["options"].pop(key, None)
        c["options"].update(self.model_options.values())
        c['image_regions'] = self.spatial_editor.values()
        previous = {line["id"]:line for line in c.get("road",{}).get("count_lines",[])}
        lines = []
        for i in range(self.lines.rowCount()):
            key = self.cell(self.lines,i,0)
            line = deepcopy(previous.get(key,{}))
            line.update(id=key,p1=[float(self.cell(self.lines,i,j)) for j in [1,2]],p2=[float(self.cell(self.lines,i,j)) for j in [3,4]])
            lines.append(line)
        c.setdefault("road",{})["count_lines"] = lines
        self.document.config = c
        return c

    @staticmethod
    def cell(widget,row,column):
        item = widget.item(row,column)
        return item.text().strip() if item else ""

    @staticmethod
    def append_row(widget,values):
        row = widget.rowCount()
        widget.insertRow(row)
        for column,value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            widget.setItem(row,column,item)

    def confirm_discard(self):
        if self.job.active:
            self.show_error("กรุณารอหรือยกเลิกงานปัจจุบันก่อนเปลี่ยนจุดสำรวจ")
            return False
        if self.dirty:
            return QMessageBox.question(self,"มีข้อมูลยังไม่บันทึก","ยกเลิกการแก้ไขและเปิดข้อมูลอื่น?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        return True

    def new_site(self):
        if self.confirm_discard():
            self.document = SiteDocument()
            self.populate()
            self.setup_player.clear()
            self.nav.setCurrentRow(1)

    def open_site(self,checked=False,path=None):
        if not self.confirm_discard():
            return
        path = path or QFileDialog.getOpenFileName(self,"เปิด site YAML",filter="YAML (*.yaml *.yml)")[0]
        if not path:
            return
        try:
            self.document.open(path)
            self.populate()
            self.remember(path)
            self.nav.setCurrentRow(1)
            self.load_preview()
        except Exception as exc:
            self.loading = False
            self.show_error(str(exc))

    def remember(self,path):
        recent = [str(Path(path).resolve())]+[self.recent.item(i).text() for i in range(self.recent.count()) if self.recent.item(i).text()!=str(Path(path).resolve())]
        self.recent.clear()
        self.recent.addItems(recent[:10])
        self.settings.setValue("recent",recent[:10])

    def save_site(self):
        if self.job.active:
            self.show_error("งานกำลังรันจาก snapshot; รอให้งานจบก่อนบันทึก")
            return
        path = QFileDialog.getSaveFileName(self,"บันทึก site YAML",str(self.document.path or "site.yaml"),"YAML (*.yaml)")[0]
        if path:
            try:
                self.collect()
                self.document.save(path)
                self.dirty = False
                self.remember(path)
                self.statusBar().showMessage("บันทึกแล้ว · ใช้ตรวจความพร้อมก่อนรัน")
            except Exception as exc:
                self.show_error(str(exc))

    def add_videos(self, paths=None):
        if paths is None or isinstance(paths, bool):
            self.import_clip_set()
            return
        if self.import_tasks.task is not None:
            return
        paths = paths if isinstance(paths, list) else QFileDialog.getOpenFileNames(self,"เพิ่มวิดีโอ",filter=VIDEO_FILTER)[0]
        if not paths:
            return
        previous = ([self.cell(self.videos,self.videos.rowCount()-1,j) for j in range(2)]
                    if self.videos.rowCount() else None)
        epoch = self.epoch.text()
        document = self.document
        self.add_video_button.setEnabled(False)
        def prepare():
            if previous:
                info = probe_video(previous[0])
                start = datetime.fromisoformat(previous[1].replace("Z", "+00:00")) if previous[1] else None
                start = start+timedelta(seconds=info["duration_s"]) if start and info["duration_s"] else None
            else:
                start = datetime.fromisoformat(epoch.replace("Z", "+00:00"))
            rows = []
            for path in paths:
                info = probe_video(path)
                rows.append([path, start.isoformat(timespec="microseconds") if start else ""])
                start = start+timedelta(seconds=info["duration_s"]) if start and info["duration_s"] else None
            return document, rows
        self.import_tasks.request(prepare)

    def import_clip_set(self):
        if self.job.active:
            return
        dialog = ClipImportDialog(self.epoch.text(), self)
        try:
            if dialog.exec():
                self.apply_clip_import(dialog.selected_rows, replace=dialog.replace.isChecked())
        finally:
            dialog.deleteLater()

    def apply_clip_import(self, rows, replace=False):
        existing = {self.cell(self.videos, index, 0) for index in range(self.videos.rowCount())} if not replace else set()
        if any(row['path'] in existing for row in rows):
            self.validation_label.setText('มีไฟล์อยู่ใน playlist เดิมแล้ว เลือกแทนรายการเดิมหรือเอาไฟล์ซ้ำออก')
            return False
        self.loading = True
        if replace:
            self.videos.setRowCount(0)
        for row in rows:
            self.append_row(self.videos, [row['path'], row['start_time']])
            values = {key: row[key] for key in ('start_time', 'time_source', 'time_format', 'interval_s') if key in row}
            self.videos.item(self.videos.rowCount()-1, 0).setData(Qt.ItemDataRole.UserRole, values)
        self.loading = False
        self.changed()
        self.validation_label.setText(f'นำเข้า {len(rows)} คลิปตามเวลาที่ตรวจทานแล้ว · ตรวจความพร้อมก่อนรัน')
        if rows:
            self.videos.setCurrentCell(0, 0)
        return True

    def videos_imported(self, payload, error):
        self.add_video_button.setEnabled(True)
        if error:
            self.validation_label.setText(error)
            return
        document, rows = payload
        if document is not self.document:
            return
        first = self.videos.rowCount()
        self.loading = True
        for row in rows:
            self.append_row(self.videos,row)
            self.videos.item(self.videos.rowCount()-1, 0).setData(Qt.ItemDataRole.UserRole,
                dict(start_time=row[1], time_source='legacy_contiguous'))
        self.loading = False
        self.changed()
        self.videos.setCurrentCell(first,0)
        self.validation_label.setText("เพิ่มวิดีโอแล้ว · เวลาเริ่มจัดต่อเนื่องตามระยะเวลาคลิป โปรดแก้ให้ตรงเวลาถ่ายจริง")

    def remove_row(self,widget):
        widget.removeRow(widget.currentRow())
        self.changed()

    def move_video(self,direction):
        row = self.videos.currentRow()
        target = row+direction
        if 0 <= row < self.videos.rowCount() and 0 <= target < self.videos.rowCount():
            first_data = self.videos.item(row, 0).data(Qt.ItemDataRole.UserRole)
            second_data = self.videos.item(target, 0).data(Qt.ItemDataRole.UserRole)
            a = [self.cell(self.videos,row,j) for j in range(2)]
            b = [self.cell(self.videos,target,j) for j in range(2)]
            for j in range(2):
                self.videos.setItem(row,j,QTableWidgetItem(b[j]))
                self.videos.setItem(target,j,QTableWidgetItem(a[j]))
            self.videos.item(row, 0).setData(Qt.ItemDataRole.UserRole, second_data)
            self.videos.item(target, 0).setData(Qt.ItemDataRole.UserRole, first_data)
            self.videos.setCurrentCell(target,0)

    def add_line(self):
        self.append_row(self.lines,[f"L{self.lines.rowCount()+1}","","","",""])
        self.lines.setCurrentCell(self.lines.rowCount()-1,0)

    def draw_line(self):
        if self.setup_canvas.matrix is None or self.setup_canvas.image is None:
            self.show_error("โหลดภาพและ calibration ก่อนวาดเส้น")
            return
        self.setup_player.pause()
        if self.lines.currentRow() < 0:
            self.add_line()
        self.setup_canvas.selected = self.cell(self.lines,self.lines.currentRow(),0)
        self.setup_canvas.first = None
        self.setup_canvas.image_draw = self.setup_canvas.image_first = None
        self.setup_canvas.drawing = True
        self.statusBar().showMessage("คลิก p1 และ p2 บนภาพ · หน่วยที่บันทึกเป็นเมตร")

    def select_line(self):
        self.setup_canvas.selected = self.cell(self.lines,self.lines.currentRow(),0)
        try:
            self.setup_canvas.lines = deepcopy(self.collect()["road"]["count_lines"])
        except (ValueError,KeyError):
            pass
        self.setup_canvas.redraw()

    def line_changed(self,key,a,b):
        row = next((i for i in range(self.lines.rowCount()) if self.cell(self.lines,i,0)==key),None)
        if row is not None:
            self.lines.blockSignals(True)
            for column,value in enumerate([*a,*b],1):
                self.lines.setItem(row,column,QTableWidgetItem(f"{value:.8g}"))
            self.lines.blockSignals(False)
            self.changed()
            self.select_line()

    def create_camera(self):
        self.setup_player.pause()
        suggested = (Path(self.camera_path.text()) if self.camera_path.text().strip() else
                     (self.document.path.parent if self.document.path else Path.cwd()) / 'camera.yaml')
        dialog = CameraDialog(image=self.setup_canvas.image, parent=self, suggested_path=suggested)
        try:
            if dialog.exec() and dialog.saved_path:
                self.camera_path.setText(dialog.saved_path)
                applied = self.apply_camera_preview()
                if applied:
                    self.validation_label.setText('สร้าง Camera YAML และเลือกใช้งานแล้ว · ตรวจตำแหน่งเส้นนับและระยะจริงก่อนประมวลผล')
        finally:
            dialog.deleteLater()

    def load_preview(self):
        if self.loading:
            return
        path = self.cell(self.videos,max(0,self.videos.currentRow()),0)
        if not path:
            self.setup_player.clear()
            return
        self.setup_player.open(path)
        self.apply_camera_preview()

    def apply_camera_preview(self):
        self.setup_canvas.matrix = None
        self.setup_canvas.lines = []
        if not self.camera_path.text().strip():
            self.validation_label.setText("ดูวิดีโอได้แล้ว · สร้างหรือเลือก Camera YAML เพื่อวิเคราะห์พิกัดพื้น")
            self.setup_canvas.redraw()
            return False
        try:
            calibration = yaml.safe_load(Path(self.camera_path.text()).read_text(encoding="utf-8"))
            matrix = camera_matrix(calibration)
            if self.setup_canvas.image is not None:
                check_image_size(calibration, [self.setup_canvas.image.shape[1], self.setup_canvas.image.shape[0]])
            self.setup_canvas.matrix = matrix
            self.setup_canvas.lines = [dict(id=self.cell(self.lines, row, 0),
                p1=[float(self.cell(self.lines, row, column)) for column in (1, 2)],
                p2=[float(self.cell(self.lines, row, column)) for column in (3, 4)])
                for row in range(self.lines.rowCount())]
        except Exception as exc:
            self.validation_label.setText(f"Calibration: {exc}")
            return False
        finally:
            self.setup_canvas.redraw()
        return True

    def preview_loaded(self,payload,error):
        if error:
            self.play_timer.stop()
            self.play_button.setText("เล่น")
            self.statusBar().showMessage(error)
            return
        mode,image,detections,info = payload
        canvas = self.setup_canvas if mode=="setup" else self.review_canvas
        canvas.detections = detections or []
        canvas.set_image(image,fit=canvas.auto_fit or canvas.image is None)
        if info:
            self.review_label.setText(f"Frame {info['frame_index']} · clip {info['clip_index']} · PTS {info['t_video']:.3f} s")
            self.review_slider.blockSignals(True)
            self.review_slider.setValue(info["frame_index"])
            self.review_slider.blockSignals(False)
            if self.play_timer.isActive() and info["frame_index"] >= self.review_slider.maximum():
                self.play_timer.stop()
                self.play_button.setText("เล่น")

    def validate_site(self, checked=False, start_run=False):
        if self.job.active:
            return False
        try:
            self.collect()
            snapshot = data_dir()/"sessions"/f"site-{time.time_ns()}.yaml"
            config = self.document.validate(snapshot)
            self.run_button.setEnabled(False)
            self.validation_label.setText("กำลังตรวจไฟล์วิดีโอและเวลาเริ่ม…")
            def preflight():
                return check_playlist(config), str(snapshot), start_run
            self.validation_tasks.request(preflight)
            return True
        except Exception as exc:
            self.validation_label.setText(str(exc))
            return False

    def validated(self, payload, error):
        self.run_button.setEnabled(not self.job.active)
        if error:
            self.validation_label.setText(error)
            return
        infos, snapshot, start_run = payload
        from ..playlist import timeline
        config = yaml.safe_load(Path(snapshot).read_text(encoding='utf-8'))
        reviewed = timeline([dict(clip, info=info) for clip, info in zip(config['videos'], infos)])
        gaps = sum(bool(row['gap_s']) for row in reviewed)
        self.validation_label.setText(f"พร้อม · {len(infos)} คลิป · ช่องว่าง {gaps} ช่วง · ตรวจการโหลดโมเดลเมื่อเริ่มงาน")
        if start_run and not self.job.active:
            try:
                if self.prepare_run():
                    self.job.start(self.output_path.text(),config=snapshot)
            except Exception as exc:
                self.on_finished("failed",str(exc))

    def prepare_run(self):
        if self.job.active:
            return False
        if self.model_selector.busy() or self.video_page.model_selector.busy():
            raise ValueError("รอการตรวจโมเดลให้เสร็จก่อนเริ่มงาน")
        if not self.output_path.text().strip():
            raise ValueError("เลือกโฟลเดอร์ผลลัพธ์ก่อนเริ่ม")
        output = Path(self.output_path.text()).expanduser().resolve()
        output.mkdir(parents=True,exist_ok=True)
        self.settings.setValue("output",str(output))
        self.validation_tasks.token += 1
        self.validation_tasks.pending = None
        self.video_page.player.pause()
        self.setup_player.pause()
        self.play_timer.stop()
        self.play_button.setText("เล่น")
        self.log.clear()
        self.counters.setText("Frames: 0 · Detections: 0")
        self.run_title.setText("กำลังเริ่มงาน")
        self.progress.setRange(0,0)
        self.nav.setCurrentRow(2)
        self.cancel_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.clip_jobs.setRowCount(0)
        self.clip_progress.setText('กำลังเตรียมรายการคลิป…')
        self.force_button.setEnabled(False)
        self.demo_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.stack.widget(1).setEnabled(False)
        self.video_page.setEnabled(False)
        return True

    def start_demo(self):
        try:
            if self.prepare_run():
                self.job.start(self.output_path.text(),demo=True)
        except Exception as exc:
            self.on_finished("failed",str(exc))

    def start_site(self):
        self.validate_site(start_run=True)

    def on_event(self,event):
        stages = {"validate":"ตรวจความพร้อม","create_fixture":"สร้างตัวอย่างจำลอง","load_model":"โหลดโมเดล","decode_track":"อ่านวิดีโอ / detect / track","detect_video":"ทดสอบ detection จากวิดีโอ","reconstruct":"สร้าง trajectory / นับเส้น","finalize":"ปิดและบันทึกไฟล์"}
        stages['fingerprint'] = 'กำลังตรวจไฟล์ต้นฉบับสำหรับทำงานต่อ'
        if event['type'] == 'started':
            self.pause_button.setEnabled(event.get('resumable', False))
        if event.get('clips_total') is not None:
            total, done = event['clips_total'], event.get('clips_done', 0)
            self.clip_progress.setText(f'บันทึกสำเร็จ {done}/{total} คลิป · คลิปที่ยังไม่ commit จะเริ่มใหม่เมื่อทำต่อ')
            if self.clip_jobs.rowCount() != total:
                self.clip_jobs.setRowCount(total)
                if self.job.output and (Path(self.job.output)/'config.resolved.json').is_file():
                    config = json.loads((Path(self.job.output)/'config.resolved.json').read_text(encoding='utf-8'))
                    for index, clip in enumerate(config['videos']):
                        self.clip_jobs.setItem(index, 0, QTableWidgetItem(Path(clip['path']).name))
                        self.clip_jobs.setItem(index, 1, QTableWidgetItem(clip['start_time']))
            for index in range(total):
                self.clip_jobs.setItem(index, 2, QTableWidgetItem('บันทึกแล้ว' if index < done else
                    'กำลังทำ' if index == event.get('clip_index') else 'รอทำ'))
        if event["type"]=="stage":
            self.run_title.setText(stages.get(event.get("stage"),event.get("stage","")))
            self.progress.setRange(0,0)
        elif event["type"]=="progress":
            if event.get('stage') == 'fingerprint':
                self.clip_progress.setText(f"ตรวจไฟล์ {event['file_index']}/{event['file_count']}: {event['filename']}")
            if event.get("vehicles_total"):
                self.progress.setRange(0,event["vehicles_total"])
                self.progress.setValue(event["vehicles_done"])
            if "frames_done" in event:
                self.counters.setText(f"Frames: {event['frames_done']} · Detections: {event['detections']} · {event['elapsed_s']:.1f} s")
                if event.get("duration_s"):
                    self.progress.setRange(0,100)
                    self.progress.setValue(min(99,int(100*event["video_time_s"]/event["duration_s"])))
        elif event["type"] in {"warning","failed","cancelled","paused"}:
            self.append_log(event.get("message","")+"\n")
        elif event["type"]=="completed" and event.get("benchmark"):
            self.append_log("Synthetic benchmark PASS\n"+json.dumps(event["benchmark"]["metrics"],indent=2))

    def append_log(self,text):
        self.log.appendPlainText(text.rstrip())

    def cancel_job(self):
        self.job.cancel()
        self.run_title.setText("กำลังรอขั้นปัจจุบันหยุด…")
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        QTimer.singleShot(5000,lambda: self.force_button.setEnabled(self.job.active))

    def pause_job(self):
        self.job.pause()
        self.pause_button.setEnabled(False)
        self.run_title.setText('กำลังพักงาน · เก็บเฉพาะคลิปที่ commit แล้ว')
        QTimer.singleShot(5000, lambda: self.force_button.setEnabled(self.job.active))

    def resume_job(self, checked=False, path=None):
        if self.job.active:
            return
        if path is None:
            dialog = ResumeDialog(self.output_path.text(), self)
            try:
                if dialog.exec():
                    path = dialog.selected_path
            finally:
                dialog.deleteLater()
        if path:
            try:
                if self.prepare_run():
                    self.job.start(Path(path).parent, resume=path)
            except Exception as exc:
                self.on_finished('failed', str(exc))

    def force_job(self):
        if QMessageBox.question(self,"หยุดแบบบังคับ","คลิปที่ยังไม่ commit ต้องทำใหม่ คลิปที่บันทึกแล้วทำต่อได้ ต้องการหยุด worker?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.job.force_stop()

    def on_finished(self,status,message):
        self.cancel_button.setEnabled(False)
        self.force_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(True)
        self.demo_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.stack.widget(1).setEnabled(True)
        self.video_page.setEnabled(True)
        labels = {"completed":"สำเร็จ","cancelled":"ยกเลิกแล้ว","failed":"ไม่สำเร็จ", 'paused':'พักงานแล้ว · เปิดทำต่อได้'}
        self.run_title.setText(labels.get(status,status))
        self.progress.setRange(0,100)
        self.progress.setValue(100 if status=="completed" else 0)
        self.append_log(message)
        if self.job.output and (Path(self.job.output)/'manifest.json').is_file():
            manifest = json.loads((Path(self.job.output)/'manifest.json').read_text(encoding='utf-8'))
            for index, clip in enumerate(manifest.get('clips', [])):
                if index < self.clip_jobs.rowCount():
                    self.clip_jobs.setItem(index, 2, QTableWidgetItem('บันทึกแล้ว' if clip['status'] == 'committed' else 'ยังไม่บันทึก'))
            if manifest.get('clips'):
                self.clip_progress.setText(f"บันทึกสำเร็จ {manifest.get('clips_done', 0)}/{len(manifest['clips'])} คลิป")
        if status=="completed" and self.job.output:
            self.load_result(self.job.output)

    def open_result(self):
        path = QFileDialog.getExistingDirectory(self,"เลือกโฟลเดอร์ run ที่มี manifest.json",self.output_path.text())
        if path:
            self.load_result(path)

    def load_result(self,path):
        self.play_timer.stop()
        self.seek_timer.stop()
        self.play_button.setText("เล่น")
        self.preview_tasks.token += 1
        self.preview_tasks.pending = None
        self.result_tasks.request(lambda: ("load",ResultStore(path),None))
        self.statusBar().showMessage("กำลังอ่านผลลัพธ์…")

    def result_loaded(self,payload,error):
        if error:
            self.show_error(error)
            return
        kind,value,extra = payload
        if kind=="load":
            self.store = value
            self.point_filter.blockSignals(True)
            self.point_filter.clear()
            self.point_filter.addItem('รถทุกคัน', None)
            for gate in value.config.get('image_regions', {}).get('points', []):
                self.point_filter.addItem(gate['id'], gate['id'])
            self.point_filter.blockSignals(False)
            m = value.manifest
            if value.mode == "video_test":
                self.summary.setText(f"ทดสอบ detection · {m['frames']} frames · {m['detections']} detections\nกรอบอยู่ในพิกัดภาพ · ยังไม่คำนวณ track ความเร็ว หรือเส้นนับ")
            else:
                self.summary.setText(f"Site {m['site_id']} · {m['frames']} frames · {m['tracks']} tracks · {m['crossings']} crossing events")
            self.summary.setToolTip("\n".join(m.get("warnings",[])))
            self.result_diagnostics.setPlainText(json.dumps(m,indent=2,ensure_ascii=False))
            matrix = value.config.get("camera",{}).get("image_to_ground")
            self.review_canvas.matrix = np.asarray(matrix) if matrix is not None else None
            self.review_canvas.lines = value.config.get("road",{}).get("count_lines",[])
            regions = value.config.get('image_regions', {})
            self.review_canvas.roi = regions.get('roi', [])
            self.review_canvas.point_gates = regions.get('points', [])
            self.review_canvas.image = None
            self.dataset.blockSignals(True)
            self.dataset.clear()
            self.dataset.addItems(value.datasets)
            self.dataset.blockSignals(False)
            self.result_tabs.setTabText(0,"Detection ตาม class" if value.mode == "video_test" else "การนับ")
            self.counts_note.setVisible(value.mode == "video_test")
            self.result_tabs.setCurrentIndex(2)
            self.review_slider.blockSignals(True)
            self.review_slider.setRange(0,max(0,m["frames"]-1))
            self.review_slider.setValue(0)
            self.review_slider.blockSignals(False)
            self.nav.setCurrentRow(3)
            self.offset = 0
            self.result_tasks.request(lambda: ("tables",self.store.page(self.dataset.currentText(),0),self.store.counts()))
            self.request_review(reset=True)
        elif kind == 'filter':
            self.store = value
            self.offset = 0
            store, dataset = value, self.dataset.currentText()
            self.result_tasks.request(lambda: ('tables', store.page(dataset, 0), store.counts()))
            self.request_review()
        elif kind=="tables":
            display_table(self.results_table,value)
            if extra is not None:
                display_table(self.counts_table,extra)
            self.page_label.setText(f"{self.offset+1 if value else 0}–{self.offset+len(value)}")
        self.statusBar().showMessage("อ่านผลลัพธ์แล้ว")

    def filter_point(self):
        if self.store:
            store, point = self.store, self.point_filter.currentData()
            self.result_tasks.request(lambda: ('filter', store.with_point(point), None))

    def reset_page(self):
        self.offset = 0
        self.change_page(0)

    def change_page(self,delta):
        if self.store:
            self.offset = max(0,self.offset+delta)
            store,name,offset = self.store,self.dataset.currentText(),self.offset
            self.result_tasks.request(lambda: ("tables",store.page(name,offset),None))

    def request_review(self, reset=False):
        if not self.store:
            return
        store,index = self.store,self.review_slider.value()
        def preview():
            if reset:
                self.review_reader.close()
            info = store.frame(index)
            return self.decode_review(store,info)
        self.preview_tasks.request(preview)

    def decode_review(self, store, info):
        path = store.config["videos"][info["clip_index"]]["path"]
        image = self.review_reader.read(path,info["t_video"])["image"]
        return "review",image,store.frame_detections(info["frame_index"]),info

    def seek_review(self):
        self.play_timer.stop()
        self.play_button.setText("เล่น")
        self.preview_tasks.token += 1
        self.preview_tasks.pending = None
        self.seek_timer.start()

    def review_speed_changed(self):
        if self.play_timer.isActive() and self.store:
            self.play_wall = time.monotonic()
            self.play_start = self.store.frame(self.review_slider.value())["t"]

    def toggle_play(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.play_button.setText("เล่น")
        elif self.store:
            self.seek_timer.stop()
            if self.review_slider.value() >= self.review_slider.maximum():
                self.review_slider.blockSignals(True)
                self.review_slider.setValue(0)
                self.review_slider.blockSignals(False)
            self.play_wall = time.monotonic()
            self.play_start = self.store.frame(self.review_slider.value())["t"]
            self.play_button.setText("พัก")
            self.play_timer.start()

    def play_next(self):
        if not self.store or self.preview_tasks.task is not None:
            return
        index = self.review_slider.value()
        if index >= self.review_slider.maximum():
            self.play_timer.stop()
            self.play_button.setText("เล่น")
            return
        target = self.play_start+(time.monotonic()-self.play_wall)*[.5,1,2][self.speed.currentIndex()]
        store = self.store
        self.preview_tasks.request(lambda: self.decode_review(store,store.frame_at(target)))

    def export_csv(self):
        if not self.store:
            return
        path = QFileDialog.getExistingDirectory(self,"เลือกโฟลเดอร์ว่างสำหรับ CSV")
        if path:
            store = self.store
            self.export_tasks.request(lambda: store.export_csv(path))
            self.statusBar().showMessage("กำลังส่งออก CSV…")

    def export_finished(self,payload,error):
        if error:
            self.show_error(error)
        else:
            self.statusBar().showMessage("ส่งออก CSV แล้ว")

    def open_output(self):
        path = str(self.store.path) if self.store else self.job.output or self.output_path.text()
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def copy_diagnostics(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(json.dumps(diagnostics(),indent=2,ensure_ascii=False))
        self.statusBar().showMessage("คัดลอกข้อมูลเครื่องแล้ว")

    def show_error(self,text):
        QMessageBox.warning(self,"ตรวจสอบข้อมูล",text)

    def stop_services(self):
        stopped = [service.stop() for service in [self.preview_tasks,self.result_tasks,self.export_tasks,
                                                   self.validation_tasks,self.import_tasks]]
        stopped += [self.video_page.player.stop(), self.setup_player.stop()]
        stopped += [self.model_selector.stop(), self.video_page.model_selector.stop()]
        stopped += [self.reid_page.stop()]
        stopped += [self.model_options.stop(), self.video_page.options.stop()]
        if stopped[0]:
            self.review_reader.close()
        return all(stopped)

    def closeEvent(self,event):
        if self.job.active:
            answer = QMessageBox.question(self,"งานกำลังประมวลผล","หยุดงานก่อนปิดโปรแกรม? เลือก No เพื่อกลับไปรอให้งานจบ",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if answer==QMessageBox.StandardButton.Yes:
                self.cancel_job()
                self.close_when_done = True
                self.job.finished.connect(lambda *_: QTimer.singleShot(0,self.close))
            event.ignore()
            return
        if self.dirty and not getattr(self,"close_when_done",False) and not self.confirm_discard():
            event.ignore()
            return
        self.play_timer.stop()
        self.seek_timer.stop()
        if not self.stop_services():
            event.ignore()
            self.statusBar().showMessage("กำลังรอ background task จบ กรุณาปิดอีกครั้ง")
            return
        self.settings.setValue("window_geometry",self.saveGeometry())
        self.settings.setValue("navigation_visible",not self.nav.isHidden())
        self.settings.setValue("setup_split",self.setup_split.saveState())
        self.video_page.save_state()
        event.accept()

