from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QFileDialog)
from ..journal import resumable_runs
from .preview import TaskService


class ResumeDialog(QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.setWindowTitle('งานที่พักไว้ / ทำต่อจาก checkpoint')
        self.resize(950, 450)
        self.selected_path = None
        self.root = str(root)
        self.rows = []
        self.tasks = TaskService(self)
        self.tasks.result.connect(self.loaded)
        box = QVBoxLayout(self)
        self.status = QLabel('กำลังอ่านรายการงาน…')
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        note = QLabel('ใช้วิดีโอและค่าตั้งค่าของงานเดิม การแก้ฟอร์มปัจจุบันไม่เปลี่ยนงานที่พักไว้')
        note.setWordWrap(True)
        box.addWidget(note)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Site', 'สถานะ', 'คลิปบันทึกแล้ว', 'เริ่มงาน', 'โฟลเดอร์'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(lambda _: self.select())
        box.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, callback in [('เปลี่ยนโฟลเดอร์ผลลัพธ์…', self.browse_root), ('เลือก run โดยตรง…', self.browse_run),
                               ('ทำงานที่เลือกต่อ', self.select), ('ปิด', self.reject)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        box.addLayout(row)
        self.refresh()

    def refresh(self):
        root = self.root
        self.tasks.request(lambda: resumable_runs(root))

    def loaded(self, rows, error):
        self.rows = rows or []
        self.status.setText(error or f'{self.root} · {len(self.rows)} งาน · ทำซ้ำเฉพาะคลิปที่ยังไม่ commit')
        self.table.setRowCount(len(self.rows))
        for index, value in enumerate(self.rows):
            status = {'paused':'พักงาน', 'cancelled':'ยกเลิก', 'interrupted':'หยุดกลางทาง',
                      'failed':'ไม่สำเร็จ', 'running':'กำลังทำ / อาจหยุดกลางทาง'}.get(value['status'], value['status'])
            for column, text in enumerate([value['site_id'], status, f"{value['clips_done']}/{value['clips_total']}",
                                           value['started_at'], value['path']]):
                self.table.setItem(index, column, QTableWidgetItem(str(text)))

    def browse_root(self):
        root = QFileDialog.getExistingDirectory(self, 'เลือกโฟลเดอร์ผลลัพธ์', self.root)
        if root:
            self.root = root
            self.refresh()

    def browse_run(self):
        path = QFileDialog.getExistingDirectory(self, 'เลือก run ที่มี journal.sqlite และ source.yaml', self.root)
        if path and (Path(path)/'source.yaml').is_file() and (Path(path)/'journal.sqlite').is_file():
            self.selected_path = path
            self.accept()

    def select(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.rows):
            self.selected_path = self.rows[index]['path']
            self.accept()

    def reject(self):
        if self.tasks.task is None or not self.tasks.task.isRunning():
            super().reject()

    def accept(self):
        if self.tasks.task is None or not self.tasks.task.isRunning():
            super().accept()

    def closeEvent(self, event):
        if self.tasks.task is not None and self.tasks.task.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
