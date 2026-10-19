"""Two-click image ROI and point-gate editor shared with video previews."""
from copy import deepcopy
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox)
from ..spatial import validate_regions


class SpatialEditor(QWidget):
    changed = Signal()
    drawing_started = Signal()

    def __init__(self, canvas, allow_points=True, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.allow_points = allow_points
        self.regions = dict(roi=[], points=[])
        box = QVBoxLayout(self)
        row = QHBoxLayout()
        self.roi_button = QPushButton('วาดกรอบพื้นที่ ROI')
        self.roi_button.clicked.connect(lambda: self.begin('roi'))
        row.addWidget(self.roi_button)
        clear = QPushButton('ใช้ทั้งภาพ')
        clear.clicked.connect(self.clear_roi)
        row.addWidget(clear)
        box.addLayout(row)
        hint = QLabel('กรอบ ROI: คลิกมุมตรงข้าม 2 จุด · เก็บรถเมื่อจุดกึ่งกลางล่างของกรอบรถอยู่ใน ROI · Esc ยกเลิก')
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.point_name = QLineEdit()
        self.point_name.setPlaceholderText('ชื่อจุด เช่น A หรือ B')
        self.direction = QComboBox()
        self.direction.addItem('ทั้งสองทิศ', 0)
        self.direction.addItem('ทิศบวก (+)', 1)
        self.direction.addItem('ทิศลบ (−)', -1)
        self.saved = QComboBox()
        self.saved.currentIndexChanged.connect(self.select)
        self.direction.currentIndexChanged.connect(self.change_direction)
        if allow_points:
            box.addWidget(QLabel('จุดผ่านในภาพ (พิกเซล ไม่ต้องแปลงพิกัดเพื่อวาด)'))
            box.addWidget(self.saved)
            box.addWidget(self.point_name)
            box.addWidget(self.direction)
            row = QHBoxLayout()
            self.point_button = QPushButton('วาดเส้นผ่านจุด 2 คลิก')
            self.point_button.clicked.connect(lambda: self.begin('point'))
            row.addWidget(self.point_button)
            remove = QPushButton('ลบจุดที่เลือก')
            remove.clicked.connect(self.remove_point)
            row.addWidget(remove)
            box.addLayout(row)
            note = QLabel('รถต้องข้ามเส้นจริง จึงบันทึกเวลาผ่านจุด · ทิศ + คือข้ามจากด้านลบไปด้านบวกของเส้น p1→p2')
            note.setWordWrap(True)
            box.addWidget(note)
        self.status = QLabel('ยังไม่จำกัดพื้นที่')
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        box.addStretch()
        canvas.roi_changed.connect(self.roi_drawn)
        canvas.point_changed.connect(self.point_drawn)

    def set_regions(self, regions):
        self.canvas.image_draw = self.canvas.image_first = None
        self.regions = deepcopy(validate_regions(regions))
        self.sync()

    def values(self):
        return deepcopy(validate_regions(self.regions))

    def sync(self):
        selected = self.saved.currentData()
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem('จุดใหม่', None)
        for gate in self.regions['points']:
            self.saved.addItem(gate['id'], gate['id'])
        self.saved.setCurrentIndex(max(0, self.saved.findData(selected)))
        self.saved.blockSignals(False)
        self.canvas.roi = deepcopy(self.regions['roi'])
        self.canvas.point_gates = deepcopy(self.regions['points'])
        self.canvas.redraw()
        self.status.setText(('จำกัดพื้นที่ ROI' if self.regions['roi'] else 'ใช้ทั้งภาพ') +
                            f" · {len(self.regions['points'])} จุดผ่าน")

    def begin(self, mode):
        if self.canvas.image is None:
            self.status.setText('เปิดวิดีโอในภาพตัวอย่างก่อนวาด')
            return
        key = self.point_name.text().strip()
        if mode == 'point' and not key:
            self.status.setText('ตั้งชื่อจุดก่อนวาด')
            return
        self.drawing_started.emit()
        self.canvas.drawing = False
        self.canvas.first = None
        self.canvas.image_draw = (mode, key)
        self.canvas.image_first = None
        self.canvas.setFocus()
        self.status.setText('คลิกมุมตรงข้ามของกรอบ 2 จุด' if mode == 'roi' else 'คลิกปลายเส้น p1 แล้ว p2')

    def roi_drawn(self, corners):
        self.regions['roi'] = corners
        self.sync()
        self.changed.emit()

    def clear_roi(self):
        self.canvas.image_draw = self.canvas.image_first = None
        self.regions['roi'] = []
        self.sync()
        self.changed.emit()

    def point_drawn(self, key, p1, p2):
        self.regions['points'] = [g for g in self.regions['points'] if g['id'] != key]
        self.regions['points'].append(dict(id=key, p1=p1, p2=p2, direction=self.direction.currentData()))
        self.sync()
        self.saved.setCurrentIndex(self.saved.findData(key))
        self.changed.emit()

    def select(self):
        key = self.saved.currentData()
        gate = next((g for g in self.regions['points'] if g['id'] == key), None)
        self.point_name.setText(key or '')
        self.direction.blockSignals(True)
        self.direction.setCurrentIndex(self.direction.findData(gate.get('direction', 0) if gate else 0))
        self.direction.blockSignals(False)

    def change_direction(self):
        gate = next((g for g in self.regions['points'] if g['id'] == self.saved.currentData()), None)
        if gate:
            gate['direction'] = self.direction.currentData()
            self.sync()
            self.changed.emit()

    def remove_point(self):
        self.regions['points'] = [g for g in self.regions['points'] if g['id'] != self.saved.currentData()]
        self.sync()
        self.select()
        self.changed.emit()
