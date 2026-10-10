"""Four-page Thai desktop application for the single-site reference pipeline."""
from copy import deepcopy
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
    QSlider, QAbstractItemView, QComboBox, QDoubleSpinBox, QScrollArea)
from ..app_paths import data_dir
from ..diagnostics import report as diagnostics
from .job_controller import JobController
from .site_document import SiteDocument
from .preview import Canvas, TaskService, decode_image
from .result_store import ResultStore


def button(text, callback):
    value = QPushButton(text)
    value.clicked.connect(callback)
    return value


def table(headers):
    value = QTableWidget(0, len(headers))
    value.setHorizontalHeaderLabels(headers)
    value.horizontalHeader().setStretchLastSection(True)
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
        self.setWindowTitle("Traffic Behavior Suite · Windows Test")
        self.resize(1280,800)
        self.setMinimumSize(1024,720)
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
        header = QHBoxLayout()
        title = QLabel("Traffic Behavior Suite")
        title.setStyleSheet("font-size:22px;font-weight:600")
        header.addWidget(title)
        header.addStretch()
        self.site_label = QLabel("Single-site · CPU reference")
        header.addWidget(self.site_label)
        header.addWidget(button("เปิดจุดสำรวจ", self.open_site))
        header.addWidget(button("บันทึก", self.save_site))
        layout.addLayout(header)
        body = QHBoxLayout()
        self.nav = QListWidget()
        self.nav.addItems(["เริ่มต้น", "ตั้งค่าจุดสำรวจ", "ประมวลผล", "ผลลัพธ์"])
        self.nav.setFixedWidth(190)
        self.stack = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.stack,1)
        layout.addLayout(body)
        self.setCentralWidget(root)
        for page in [self.start_page(), self.setup_page(), self.run_page(), self.results_page()]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.statusBar().showMessage("พร้อมทดสอบ · ยังไม่มีข้อมูลกล้องจริง")
        self.populate()

    def start_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        intro = QLabel("เริ่มทดสอบ pipeline จากหน้าจอ\nเลือกตัวอย่างจำลอง หรือเปิดวิดีโอและโมเดลที่มีอยู่ในเครื่อง")
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size:20px;padding:20px")
        box.addWidget(intro)
        row = QHBoxLayout()
        self.demo_button = button("ทดสอบตัวอย่าง", self.start_demo)
        self.demo_button.setMinimumHeight(70)
        row.addWidget(self.demo_button)
        row.addWidget(button("สร้างจุดสำรวจ", self.new_site))
        row.addWidget(button("เปิดผลลัพธ์เดิม", self.open_result))
        box.addLayout(row)
        form = QFormLayout()
        self.output_path = QLineEdit(self.settings.value("output", str(data_dir()/"output")))
        form.addRow("โฟลเดอร์ผลลัพธ์", self.path_widget(self.output_path, directory=True))
        box.addLayout(form)
        self.recent = QListWidget()
        for path in self.settings.value("recent", [], type=list):
            self.recent.addItem(path)
        self.recent.itemDoubleClicked.connect(lambda item: self.open_site(path=item.text()))
        box.addWidget(QLabel("จุดสำรวจล่าสุด — ดับเบิลคลิกเพื่อเปิด"))
        box.addWidget(self.recent)
        box.addWidget(button("คัดลอกข้อมูลเครื่องสำหรับตรวจปัญหา", self.copy_diagnostics))
        box.addWidget(QLabel("Demo ใช้สี่เหลี่ยมจำลอง · ผลทดสอบนี้ไม่ได้ยืนยันความแม่นยำกับรถจริง"))
        box.addStretch()
        return page

    def path_widget(self, field, directory=False, callback=None):
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0,0,0,0)
        row.addWidget(field)
        def browse():
            path = QFileDialog.getExistingDirectory(self,"เลือกโฟลเดอร์",field.text()) if directory else QFileDialog.getOpenFileName(self,"เลือกไฟล์",field.text())[0]
            if path:
                field.setText(path)
                if callback:
                    callback()
        row.addWidget(button("เลือก…",browse))
        return wrapper

    def setup_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        top = QFormLayout()
        self.site_id, self.epoch = QLineEdit(), QLineEdit()
        top.addRow("Site ID",self.site_id)
        top.addRow("Epoch (พร้อม timezone เช่น +07:00)",self.epoch)
        box.addLayout(top)
        split = QSplitter()
        tabs = QTabWidget()
        videos = QWidget()
        vbox = QVBoxLayout(videos)
        self.videos = table(["ไฟล์วิดีโอ", "เวลาเริ่มเฟรมแรก (timezone)"])
        vbox.addWidget(self.videos)
        row = QHBoxLayout()
        row.addWidget(button("เพิ่มวิดีโอ",self.add_videos))
        row.addWidget(button("ลบรายการ",lambda: self.remove_row(self.videos)))
        row.addWidget(button("ขึ้น",lambda: self.move_video(-1)))
        row.addWidget(button("ลง",lambda: self.move_video(1)))
        vbox.addLayout(row)
        tabs.addTab(videos,"วิดีโอ")
        camera = QWidget()
        form = QFormLayout(camera)
        self.camera_path = QLineEdit()
        form.addRow("Camera YAML",self.path_widget(self.camera_path,callback=self.load_preview))
        form.addRow(QLabel("Planar homography เท่านั้น\nภาพต้องผ่าน undistort แล้ว\nยังไม่มีการรับรองความแม่นยำ calibration"))
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
        lbox.addWidget(QLabel("เลือกเส้นเพื่อเลื่อน endpoint · หมุนล้อเมาส์เพื่อ zoom · ลากพื้นที่ภาพเพื่อ pan"))
        tabs.addTab(lines,"เส้นนับ")
        model = QWidget()
        form = QFormLayout(model)
        self.model_path = QLineEdit()
        form.addRow("Local detector weights",self.path_widget(self.model_path))
        self.options = QPlainTextEdit()
        self.options.setMinimumHeight(220)
        form.addRow("ตัวเลือกขั้นสูง (JSON)",self.options)
        form.addRow(QLabel("CPU เป็นค่าเริ่มต้น · class_ids ใช้ ID ของโมเดลจริง\nsynthetic_color ใช้เฉพาะตัวอย่างจำลอง"))
        tabs.addTab(model,"โมเดล/ตัวเลือก")
        self.setup_canvas = Canvas()
        self.setup_canvas.line_changed.connect(self.line_changed)
        self.setup_canvas.problem.connect(self.show_error)
        split.addWidget(tabs)
        split.addWidget(self.setup_canvas)
        split.setSizes([500,600])
        box.addWidget(split,1)
        self.validation_label = QLabel("ยังไม่ได้ตรวจความพร้อม")
        self.validation_label.setWordWrap(True)
        box.addWidget(self.validation_label)
        row = QHBoxLayout()
        row.addWidget(button("ตรวจความพร้อม",self.validate_site))
        self.run_button = button("ประมวลผลจุดสำรวจนี้",self.start_site)
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
        self.run_title = QLabel("พร้อมเริ่มงาน")
        self.run_title.setStyleSheet("font-size:22px")
        box.addWidget(self.run_title)
        self.progress = QProgressBar()
        box.addWidget(self.progress)
        self.counters = QLabel("Frames: 0 · Detections: 0")
        box.addWidget(self.counters)
        row = QHBoxLayout()
        self.cancel_button = button("ยกเลิก",self.cancel_job)
        self.force_button = button("หยุดแบบบังคับ",self.force_job)
        self.cancel_button.setEnabled(False)
        self.force_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        row.addWidget(self.force_button)
        row.addWidget(button("เปิดโฟลเดอร์ผลลัพธ์",self.open_output))
        box.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(2000)
        box.addWidget(self.log,1)
        return page

    def results_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        self.summary = QLabel("เปิดผลลัพธ์ที่ประมวลผลสำเร็จเพื่อดูข้อมูล")
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        tabs = QTabWidget()
        self.counts_table = table([])
        tabs.addTab(self.counts_table,"การนับ")
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
        tabs.addTab(samples,"ข้อมูลรายคัน/trajectory")
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
        row.addWidget(self.speed)
        self.review_label = QLabel("Frame 0 · PTS 0 s")
        row.addWidget(self.review_label)
        self.review_slider = QSlider(Qt.Orientation.Horizontal)
        self.review_slider.setRange(0,0)
        self.review_slider.valueChanged.connect(lambda: self.seek_timer.start())
        rbox.addLayout(row)
        rbox.addWidget(self.review_slider)
        tabs.addTab(review,"ตรวจภาพ + track overlay")
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
            self.validation_label.setText("มีการแก้ไข · ตรวจความพร้อมอีกครั้งก่อนรัน")

    def populate(self):
        self.loading = True
        c = self.document.config
        self.site_id.setText(c.get("site_id",""))
        self.epoch.setText(c.get("epoch",c.get("videos",[{}])[0].get("start_time","") if c.get("videos") else ""))
        self.camera_path.setText(c.get("camera",{}).get("model_file",""))
        self.model_path.setText(c.get("models",{}).get("detector",""))
        self.options.setPlainText(json.dumps(c.get("options",{}),indent=2))
        self.videos.setRowCount(0)
        for clip in c.get("videos",[]):
            self.append_row(self.videos,[clip.get("path",""),clip.get("start_time","")])
        self.lines.setRowCount(0)
        for line in c.get("road",{}).get("count_lines",[]):
            self.append_row(self.lines,[line["id"],*line["p1"],*line["p2"]])
        self.loading = False
        self.dirty = False
        self.site_label.setText(c.get("site_id","")+" · CPU reference")

    def collect(self):
        c = deepcopy(self.document.config)
        c["site_id"],c["epoch"] = self.site_id.text().strip(),self.epoch.text().strip()
        c["videos"] = [{"path":self.cell(self.videos,i,0),"start_time":self.cell(self.videos,i,1)} for i in range(self.videos.rowCount())]
        c.setdefault("camera",{})["model_file"] = self.camera_path.text().strip()
        c.setdefault("models",{})["detector"] = self.model_path.text().strip()
        c["options"] = json.loads(self.options.toPlainText())
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
            widget.setItem(row,column,QTableWidgetItem(str(value)))

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
            self.setup_canvas.image = None
            self.setup_canvas.redraw()
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

    def add_videos(self):
        paths = QFileDialog.getOpenFileNames(self,"เพิ่มวิดีโอ",filter="Videos (*.mp4 *.mkv *.avi *.mov);;All files (*)")[0]
        for path in paths:
            self.append_row(self.videos,[path,self.epoch.text()])

    def remove_row(self,widget):
        widget.removeRow(widget.currentRow())
        self.changed()

    def move_video(self,direction):
        row = self.videos.currentRow()
        target = row+direction
        if 0 <= row < self.videos.rowCount() and 0 <= target < self.videos.rowCount():
            a = [self.cell(self.videos,row,j) for j in range(2)]
            b = [self.cell(self.videos,target,j) for j in range(2)]
            for j in range(2):
                self.videos.setItem(row,j,QTableWidgetItem(b[j]))
                self.videos.setItem(target,j,QTableWidgetItem(a[j]))
            self.videos.setCurrentCell(target,0)

    def add_line(self):
        self.append_row(self.lines,[f"L{self.lines.rowCount()+1}","","","",""])
        self.lines.setCurrentCell(self.lines.rowCount()-1,0)

    def draw_line(self):
        if self.setup_canvas.matrix is None or self.setup_canvas.image is None:
            self.show_error("โหลดภาพและ calibration ก่อนวาดเส้น")
            return
        if self.lines.currentRow() < 0:
            self.add_line()
        self.setup_canvas.selected = self.cell(self.lines,self.lines.currentRow(),0)
        self.setup_canvas.first = None
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

    def load_preview(self):
        try:
            path = self.cell(self.videos,max(0,self.videos.currentRow()),0)
            calibration = yaml.safe_load(Path(self.camera_path.text()).read_text(encoding="utf-8"))
            if calibration.get("projection") != "planar_homography":
                raise ValueError("รองรับ planar_homography เท่านั้น")
            matrix = np.asarray(calibration["image_to_ground"],dtype=float)
            if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix))<1e-12:
                raise ValueError("Camera matrix ไม่ถูกต้อง")
            self.setup_canvas.matrix = matrix
            self.setup_canvas.lines = deepcopy(self.document.config.get("road",{}).get("count_lines",[]))
            self.preview_tasks.request(lambda: ("setup",decode_image(path),None,None))
        except Exception as exc:
            self.validation_label.setText(f"Preview: {exc}")

    def preview_loaded(self,payload,error):
        if error:
            self.statusBar().showMessage(error)
            return
        mode,image,detections,info = payload
        canvas = self.setup_canvas if mode=="setup" else self.review_canvas
        canvas.detections = detections or []
        canvas.set_image(image,fit=mode=="setup" or canvas.image is None)
        if info:
            self.review_label.setText(f"Frame {info['frame_index']} · clip {info['clip_index']} · PTS {info['t_video']:.3f} s")

    def validate_site(self):
        try:
            self.collect()
            self.document.validate(data_dir()/"validation-site.yaml")
            self.validation_label.setText("Config และไฟล์ผ่านการตรวจ · ตรวจการโหลดโมเดลเมื่อเริ่มงาน · calibration ยังต้องตรวจภาคสนาม")
            return True
        except Exception as exc:
            self.validation_label.setText(str(exc))
            return False

    def prepare_run(self):
        if self.job.active:
            return False
        if not self.output_path.text().strip():
            raise ValueError("เลือกโฟลเดอร์ผลลัพธ์ก่อนเริ่ม")
        output = Path(self.output_path.text()).expanduser().resolve()
        output.mkdir(parents=True,exist_ok=True)
        self.settings.setValue("output",str(output))
        self.log.clear()
        self.run_title.setText("กำลังเริ่มงาน")
        self.progress.setRange(0,0)
        self.nav.setCurrentRow(2)
        self.cancel_button.setEnabled(True)
        self.force_button.setEnabled(False)
        self.demo_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.stack.widget(1).setEnabled(False)
        return True

    def start_demo(self):
        try:
            if self.prepare_run():
                self.job.start(self.output_path.text(),demo=True)
        except Exception as exc:
            self.on_finished("failed",str(exc))

    def start_site(self):
        if not self.validate_site():
            return
        try:
            snapshot = self.document.snapshot(data_dir()/"sessions"/f"site-{time.time_ns()}.yaml")
            if self.prepare_run():
                self.job.start(self.output_path.text(),config=snapshot)
        except Exception as exc:
            self.on_finished("failed",str(exc))

    def on_event(self,event):
        stages = {"validate":"ตรวจความพร้อม","create_fixture":"สร้างตัวอย่างจำลอง","load_model":"โหลดโมเดล","decode_track":"อ่านวิดีโอ / detect / track","reconstruct":"สร้าง trajectory / นับเส้น","finalize":"ปิดและบันทึกไฟล์"}
        if event["type"]=="stage":
            self.run_title.setText(stages.get(event.get("stage"),event.get("stage","")))
            self.progress.setRange(0,0)
        elif event["type"]=="progress":
            if event.get("vehicles_total"):
                self.progress.setRange(0,event["vehicles_total"])
                self.progress.setValue(event["vehicles_done"])
            if "frames_done" in event:
                self.counters.setText(f"Frames: {event['frames_done']} · Detections: {event['detections']} · {event['elapsed_s']:.1f} s")
        elif event["type"] in {"warning","failed","cancelled"}:
            self.append_log(event.get("message","")+"\n")
        elif event["type"]=="completed" and event.get("benchmark"):
            self.append_log("Synthetic benchmark PASS\n"+json.dumps(event["benchmark"]["metrics"],indent=2))

    def append_log(self,text):
        self.log.appendPlainText(text.rstrip())

    def cancel_job(self):
        self.job.cancel()
        self.run_title.setText("กำลังรอขั้นปัจจุบันหยุด…")
        self.cancel_button.setEnabled(False)
        QTimer.singleShot(5000,lambda: self.force_button.setEnabled(self.job.active))

    def force_job(self):
        if QMessageBox.question(self,"หยุดแบบบังคับ","ผลลัพธ์อาจไม่สมบูรณ์ ต้องการหยุด worker?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.job.force_stop()

    def on_finished(self,status,message):
        self.cancel_button.setEnabled(False)
        self.force_button.setEnabled(False)
        self.demo_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.stack.widget(1).setEnabled(True)
        labels = {"completed":"สำเร็จ","cancelled":"ยกเลิกแล้ว","failed":"ไม่สำเร็จ"}
        self.run_title.setText(labels.get(status,status))
        self.progress.setRange(0,100)
        self.progress.setValue(100 if status=="completed" else 0)
        self.append_log(message)
        if status=="completed" and self.job.output:
            self.load_result(self.job.output)

    def open_result(self):
        path = QFileDialog.getExistingDirectory(self,"เลือกโฟลเดอร์ run ที่มี manifest.json",self.output_path.text())
        if path:
            self.load_result(path)

    def load_result(self,path):
        self.play_timer.stop()
        self.result_tasks.request(lambda: ("load",ResultStore(path),None))
        self.statusBar().showMessage("กำลังอ่านผลลัพธ์…")

    def result_loaded(self,payload,error):
        if error:
            self.show_error(error)
            return
        kind,value,extra = payload
        if kind=="load":
            self.store = value
            m = value.manifest
            self.summary.setText(f"Site {m['site_id']} · {m['frames']} frames · {m['tracks']} tracks · {m['crossings']} crossing events\n"+"\n".join(m.get("warnings",[])))
            self.result_diagnostics.setPlainText(json.dumps(m,indent=2,ensure_ascii=False))
            self.review_canvas.matrix = np.asarray(value.config["camera"]["image_to_ground"])
            self.review_canvas.lines = value.config["road"]["count_lines"]
            self.review_canvas.image = None
            self.review_slider.setRange(0,max(0,m["frames"]-1))
            self.review_slider.setValue(0)
            self.nav.setCurrentRow(3)
            self.offset = 0
            self.result_tasks.request(lambda: ("tables",self.store.page(self.dataset.currentText(),0),self.store.counts()))
            self.request_review()
        elif kind=="tables":
            display_table(self.results_table,value)
            if extra is not None:
                display_table(self.counts_table,extra)
            self.page_label.setText(f"{self.offset+1 if value else 0}–{self.offset+len(value)}")
        self.statusBar().showMessage("อ่านผลลัพธ์แล้ว")

    def reset_page(self):
        self.offset = 0
        self.change_page(0)

    def change_page(self,delta):
        if self.store:
            self.offset = max(0,self.offset+delta)
            store,name,offset = self.store,self.dataset.currentText(),self.offset
            self.result_tasks.request(lambda: ("tables",store.page(name,offset),None))

    def request_review(self):
        if not self.store:
            return
        store,index = self.store,self.review_slider.value()
        def preview():
            info = store.frame(index)
            path = store.config["videos"][info["clip_index"]]["path"]
            return "review",decode_image(path,info["t_video"]),store.frame_detections(index),info
        self.preview_tasks.request(preview)

    def toggle_play(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
        elif self.store:
            self.play_wall = time.monotonic()
            self.play_start = self.store.frame(self.review_slider.value())["t"]
            self.play_timer.start()

    def play_next(self):
        if not self.store or self.preview_tasks.task is not None:
            return
        index = self.review_slider.value()
        if index >= self.review_slider.maximum():
            self.play_timer.stop()
            return
        target = self.play_start+(time.monotonic()-self.play_wall)*[.5,1,2][self.speed.currentIndex()]
        if self.store.frame(index+1)["t"] <= target:
            self.review_slider.setValue(index+1)

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
        if not all(service.stop() for service in [self.preview_tasks,self.result_tasks,self.export_tasks]):
            event.ignore()
            self.statusBar().showMessage("กำลังรอ background task จบ กรุณาปิดอีกครั้ง")
            return
        event.accept()
