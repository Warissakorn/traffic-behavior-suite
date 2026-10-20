"""Preview filename/interval timing and coverage before adding a clip set."""
from pathlib import Path
import threading
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QFileDialog, QDialogButtonBox, QHeaderView)
from ..app_paths import data_dir
from ..events import CancelledError
from ..playlist import inspect_clips, timeline, ProbeCache, VIDEO_SUFFIXES
from .preview import TaskService
from .widgets import VIDEO_FILTER
from .wheel_guard import install_wheel_guard


class ClipImportDialog(QDialog):
    def __init__(self, reference, parent=None):
        super().__init__(parent)
        install_wheel_guard()
        self.setWindowTitle('นำเข้าชุดคลิปและตรวจเวลาจริง')
        self.resize(1050, 650)
        self.paths, self.rows, self.selected_rows = [], [], []
        self.cancelled = threading.Event()
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.setInterval(30)
        self.close_timer.timeout.connect(self.reject)
        self.tasks = TaskService(self)
        self.tasks.result.connect(self.inspected)
        box = QVBoxLayout(self)
        row = QHBoxLayout()
        files = QPushButton('เลือกหลายไฟล์…')
        files.clicked.connect(self.choose_files)
        folder = QPushButton('เลือกโฟลเดอร์…')
        folder.clicked.connect(self.choose_folder)
        row.addWidget(files)
        row.addWidget(folder)
        self.recursive = QCheckBox('รวมโฟลเดอร์ย่อย')
        row.addWidget(self.recursive)
        box.addLayout(row)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem('วัน–เวลาจากชื่อไฟล์', 'filename')
        self.mode.addItem('เวลาเริ่ม + ช่วงห่างที่กำหนด (ต้องตรวจทาน)', 'interval')
        self.reference = QLineEdit(reference)
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText('อัตโนมัติ: 20261020_060000 หรือ 2026-10-20_06-00-00')
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setValue(10)
        form.addRow('แหล่งเวลา', self.mode)
        form.addRow('เวลาเริ่ม / timezone', self.reference)
        form.addRow('รูปแบบชื่อไฟล์ (ไม่รวม .นามสกุล)', self.pattern)
        form.addRow('ช่วงห่างนาที (โหมดกำหนดเอง)', self.interval)
        box.addLayout(form)
        note = QLabel('ชื่อไฟล์หลาย timestamp ให้ระบุรูปแบบ datetime.strptime เช่น CAM_%Y%m%d_%H%M%S\n'
                      'โหมดช่วงห่างเป็นข้อสมมุติ ไม่สามารถตรวจคลิปหายจากชื่อที่ไม่มีเวลาได้แน่นอน '
                      'ไฟล์ที่ไม่เลือกจะไม่เลื่อนเวลาของคลิปอื่น')
        note.setWordWrap(True)
        box.addWidget(note)
        self.inspect_button = QPushButton('ตรวจรายการและเวลาใหม่')
        self.inspect_button.clicked.connect(self.inspect)
        box.addWidget(self.inspect_button)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['ใช้', 'ไฟล์', 'เริ่มถ่าย', 'ปลายคลิป', 'ขนาดภาพ', 'ผลตรวจ'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.selection_changed)
        box.addWidget(self.table, 1)
        self.summary = QLabel('เลือกชุดวิดีโอก่อนตรวจ')
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.summary)
        self.replace = QCheckBox('แทนรายการวิดีโอเดิมทั้งหมดในจุดสำรวจ')
        self.acknowledge = QCheckBox('ตรวจทานช่องว่าง / ไฟล์เหมือนกัน / ข้อสมมุติเวลาแล้ว')
        self.acknowledge.toggled.connect(self.selection_changed)
        box.addWidget(self.replace)
        box.addWidget(self.acknowledge)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.accept_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.accept_button.setText('เพิ่มคลิปที่เลือก')
        self.accept_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        for field in (self.reference, self.pattern):
            field.textChanged.connect(self.invalidate)
        self.mode.currentIndexChanged.connect(self.invalidate)
        self.interval.valueChanged.connect(self.invalidate)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'เลือกวิดีโอ', '', VIDEO_FILTER)
        if paths:
            self.paths = paths
            self.inspect()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'เลือกโฟลเดอร์วิดีโอ')
        if folder:
            iterator = Path(folder).rglob('*') if self.recursive.isChecked() else Path(folder).iterdir()
            self.paths = [str(path) for path in iterator if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES]
            self.inspect()

    def invalidate(self, *args):
        self.cancelled.set()
        self.tasks.token += 1
        self.tasks.pending = None
        self.rows = []
        self.selected_rows = []
        self.accept_button.setEnabled(False)
        self.summary.setText('ค่าตั้งต้นเปลี่ยนแล้ว กดตรวจรายการและเวลาใหม่ก่อนนำเข้า')

    def inspect(self):
        if not self.paths:
            self.summary.setText('ไม่พบไฟล์วิดีโอ เลือกหลายไฟล์หรือโฟลเดอร์ก่อน')
            return
        paths, reference = list(self.paths), self.reference.text().strip()
        self.cancelled.set()
        self.cancelled = threading.Event()
        cancelled = self.cancelled
        def check_cancel():
            if cancelled.is_set():
                raise CancelledError('ยกเลิกการตรวจชุดคลิป')
        mode, pattern, interval = self.mode.currentData(), self.pattern.text().strip(), self.interval.value()*60
        self.rows = []
        self.accept_button.setEnabled(False)
        self.acknowledge.setChecked(False)
        self.summary.setText(f'กำลังตรวจ {len(paths)} ไฟล์…')
        self.tasks.request(lambda: inspect_clips(paths, reference, mode=mode, pattern=pattern,
                            interval_s=interval, cache=ProbeCache(data_dir()/'clip-probes.json'), check_cancel=check_cancel))

    def inspected(self, rows, error):
        if error:
            self.rows = []
            self.summary.setText(error)
            return
        self.rows = rows
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            info = row.get('info', {})
            values = ['', Path(row['path']).name, row.get('start_time', ''), row.get('end_time', ''),
                      f"{info.get('width', '—')}×{info.get('height', '—')}", row.get('error', '')]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 1:
                    item.setToolTip(row['path'])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 0:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked if row.get('error') or row.get('overlap') else Qt.CheckState.Checked)
                self.table.setItem(index, column, item)
        self.table.blockSignals(False)
        self.selection_changed()

    def selection_changed(self, *args):
        selected = [row for index, row in enumerate(self.rows) if index < self.table.rowCount() and
                    self.table.item(index, 0).checkState() == Qt.CheckState.Checked]
        valid = bool(selected) and not any(row.get('error') for row in selected)
        reviewed = timeline(selected) if valid else []
        warnings = 0
        for row in reviewed:
            warnings += bool(row.get('gap_s') or row.get('duplicate_of') or row.get('resolution_changed') or
                             not row.get('end_known') or row['time_source'] == 'interval')
        self.table.blockSignals(True)
        by_path = {row['path']: row for row in reviewed}
        for index, original in enumerate(self.rows):
            row = by_path.get(original['path'], original)
            notices = [row.get('error', '')]
            if row.get('gap_s'):
                notices.append(f"ช่องว่าง {row['gap_s']:.2f} วินาที")
            if row.get('overlap'):
                notices.append('เวลาซ้อน')
            if row.get('duplicate_of'):
                notices.append('เนื้อหาไฟล์เหมือนกัน: ' + Path(row['duplicate_of']).name)
            if row.get('resolution_changed'):
                notices.append('ความละเอียดเปลี่ยน')
            if row.get('info') and not row.get('end_known'):
                notices.append('ปลายคลิปอ้างอิง PTS เฟรมท้าย' if row.get('end_observed') else 'ไม่ทราบปลายคลิป ตรวจเวลาด้วยตนเอง')
            self.table.item(index, 5).setText(' · '.join(filter(None, notices)) or 'พร้อม')
        self.table.blockSignals(False)
        self.selected_rows = reviewed
        self.accept_button.setEnabled(valid and not any(r.get('overlap') for r in reviewed) and
                                      (not warnings or self.acknowledge.isChecked()) and self.tasks.pending is None)
        self.summary.setText(f'เลือก {len(selected)}/{len(self.rows)} คลิป · มีคำเตือน {warnings} รายการ · '
                             'เวลาของคลิปที่ไม่เลือกยังคงเป็นช่องว่างตามจริง')

    def accept(self):
        if (self.accept_button.isEnabled() and self.selected_rows and
                (self.tasks.task is None or not self.tasks.task.isRunning())):
            super().accept()

    def reject(self):
        if self.tasks.task is not None and self.tasks.task.isRunning():
            self.cancelled.set()
            self.summary.setText('กำลังยกเลิกการอ่านไฟล์…')
            self.close_timer.start()
            return
        self.close_timer.stop()
        super().reject()

    def closeEvent(self, event):
        if self.tasks.task is None or not self.tasks.task.isRunning():
            super().closeEvent(event)
        else:
            self.reject()
            event.ignore()
