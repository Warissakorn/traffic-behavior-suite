"""Create and inspect a planar camera calibration without hand-editing YAML."""
from pathlib import Path
import numpy as np
import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
                              QPushButton, QComboBox, QLineEdit, QTableWidget,
                              QTableWidgetItem, QHeaderView, QAbstractItemView,
                              QDialogButtonBox, QFileDialog, QMessageBox, QSplitter,
                              QWidget, QGraphicsItem, QScrollArea)
from ..camera_calibration import calibrate_camera, rectangle_points, road_points
from .preview import Canvas
from .site_document import atomic_text
from .wheel_guard import install_wheel_guard


class CalibrationCanvas(Canvas):
    picked = Signal(object)

    def __init__(self, parent=None):
        self.control_points = []
        self.selected_point = -1
        self.capture = True
        self.road_outline = False
        super().__init__(parent)

    def redraw(self):
        super().redraw()
        if self.image is None:
            return
        if self.road_outline and len(self.control_points) == 4 and all(
                0 <= p[0] < self.image.shape[1] and 0 <= p[1] < self.image.shape[0]
                for p in self.control_points):
            pen = QPen(QColor('#65b7ff'), 2)
            pen.setCosmetic(True)
            for first, second in ((0, 1), (1, 2), (2, 3), (3, 0)):
                self.scene().addLine(*self.control_points[first], *self.control_points[second], pen)
            for first, second, text in ((0, 1, 'P1→P2 ตามถนน'), (0, 3, 'P1→P4 ขวางถนน')):
                position = (np.array(self.control_points[first]) + self.control_points[second]) / 2
                label = self.scene().addText(text)
                label.setDefaultTextColor(pen.color())
                label.setPos(*position)
                label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        for index, point in enumerate(self.control_points):
            pen = QPen(QColor('#ffca45' if index == self.selected_point else '#38dfbf'), 2)
            pen.setCosmetic(True)
            marker = self.scene().addEllipse(-5, -5, 10, 10, pen)
            marker.setPos(*point)
            marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            label = self.scene().addText(f'P{index + 1}')
            label.setDefaultTextColor(pen.color())
            label.setPos(*point)
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)

    def mousePressEvent(self, event):
        if self.capture and event.button() == Qt.MouseButton.LeftButton and self.image is not None:
            point = self.mapToScene(event.position().toPoint())
            if 0 <= point.x() <= self.image.shape[1] - 1 and 0 <= point.y() <= self.image.shape[0] - 1:
                self.picked.emit([point.x(), point.y()])
            event.accept()
            return
        super().mousePressEvent(event)


class CameraDialog(QDialog):
    def __init__(self, image=None, parent=None, suggested_path=None):
        super().__init__(parent)
        install_wheel_guard()
        self.setWindowTitle('สร้าง Camera YAML จากภาพ')
        self.resize(1120, 740)
        self.saved_path = None
        self.suggested_path = str(suggested_path or 'camera.yaml')
        self.repick_row = None
        box = QVBoxLayout(self)
        intro = QLabel('ใช้จุดบนพื้นถนนระนาบเดียวกันที่ทราบระยะจริง ภาพต้องผ่านการแก้เลนส์บิดเบี้ยวแล้ว '
                       'และใช้มุมกล้อง / ความละเอียดเดียวกับวิดีโอที่จะวิเคราะห์')
        intro.setWordWrap(True)
        box.addWidget(intro)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = CalibrationCanvas()
        self.canvas.picked.connect(self.add_point)
        left = QWidget()
        left_box = QVBoxLayout(left)
        row = QHBoxLayout()
        open_image = QPushButton('เปิดภาพอ้างอิง…')
        open_image.clicked.connect(self.choose_image)
        row.addWidget(open_image)
        fit = QPushButton('พอดีภาพ')
        fit.clicked.connect(self.canvas.fit_image)
        row.addWidget(fit)
        self.capture = QPushButton('คลิกเลือกจุด')
        self.capture.setCheckable(True)
        self.capture.setChecked(True)
        self.capture.toggled.connect(self.capture_changed)
        row.addWidget(self.capture)
        left_box.addLayout(row)
        left_box.addWidget(self.canvas, 1)
        self.image_label = QLabel('ใช้เฟรมวิดีโอปัจจุบัน หรือเปิดภาพอ้างอิงจากกล้องเดียวกัน')
        self.image_label.setWordWrap(True)
        left_box.addWidget(self.image_label)
        split.addWidget(left)
        controls = QWidget()
        form = QVBoxLayout(controls)
        self.mode = QComboBox()
        self.mode.addItem('สี่เหลี่ยมที่ทราบกว้าง × ยาว (4 จุด)', 'rectangle')
        self.mode.addItem('พิกัดพื้นอิสระ (4 จุดขึ้นไป)', 'control')
        self.mode.addItem('ระยะตามแนวถนน: ต้นช่วง → ปลายช่วง (4 จุด)', 'road')
        form.addWidget(self.mode)
        dimensions = QFormLayout()
        self.dimension_form = dimensions
        self.width, self.length = QLineEdit(), QLineEdit()
        self.width.setPlaceholderText('ระยะ P1 → P2 ที่วัดจริง')
        self.length.setPlaceholderText('ระยะ P2 → P3 ที่วัดจริง')
        dimensions.addRow('กว้าง X (เมตร)', self.width)
        dimensions.addRow('ยาว Y (เมตร)', self.length)
        form.addLayout(dimensions)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        form.addWidget(self.hint)
        self.points = QTableWidget(0, 5)
        self.points.setHorizontalHeaderLabels(['จุด', 'ภาพ u (px)', 'ภาพ v (px)', 'พื้น X (ม.)', 'พื้น Y (ม.)'])
        self.points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.points.horizontalHeader().setStretchLastSection(True)
        self.points.verticalHeader().hide()
        self.points.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points.setMinimumHeight(170)
        form.addWidget(self.points, 1)
        row = QHBoxLayout()
        self.move_button = QPushButton('ย้ายจุดที่เลือก')
        self.move_button.clicked.connect(self.begin_repick)
        row.addWidget(self.move_button)
        remove = QPushButton('ลบจุด')
        remove.clicked.connect(self.remove_point)
        row.addWidget(remove)
        clear = QPushButton('เริ่มจุดใหม่')
        clear.clicked.connect(self.clear_points)
        row.addWidget(clear)
        form.addLayout(row)
        calculate = QPushButton('คำนวณและตรวจจุดอ้างอิง')
        calculate.clicked.connect(self.calculate)
        form.addWidget(calculate)
        self.status = QLabel('เลือกภาพ แล้วคลิกจุดอ้างอิงบนพื้นถนน')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        form.addWidget(self.status)
        note = QLabel('4 จุดอาจได้ค่าคลาดเคลื่อนใกล้ศูนย์แม้วัดระยะผิด จึงควรตรวจด้วยระยะอีกชุดหนึ่ง '
                      'พิกัดอิสระควรใช้ 6 จุดขึ้นไป กระจายทั่วพื้นที่ที่ต้องการวัด '
                      'ค่า RMSE เป็นความพอดีกับจุดที่กรอก ไม่ใช่การรับรองความแม่นยำภาคสนาม')
        note.setWordWrap(True)
        form.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(controls)
        scroll.setMinimumWidth(340)
        split.addWidget(scroll)
        split.setSizes([640, 460])
        box.addWidget(split, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('บันทึก Camera YAML และใช้')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('ยกเลิก')
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        box.addWidget(self.buttons)
        self.points.itemChanged.connect(self.changed)
        self.points.itemSelectionChanged.connect(self.selection_changed)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.width.textChanged.connect(self.dimensions_changed)
        self.length.textChanged.connect(self.dimensions_changed)
        self.mode.setCurrentIndex(self.mode.findData('road'))
        self.mode_changed()
        if image is not None:
            self.set_reference_image(image)

    def set_reference_image(self, image):
        self.canvas.set_image(image.copy())
        height, width = image.shape[:2]
        self.image_label.setText(f'ภาพอ้างอิง {width} × {height} px · ล้อเมาส์ซูม · ปิด “คลิกเลือกจุด” เพื่อลากภาพ')

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, 'เปิดภาพอ้างอิง', '', 'Images (*.png *.jpg *.jpeg *.bmp)')
        if not path:
            return
        image = QImage(path).convertToFormat(QImage.Format.Format_RGB888)
        if image.isNull():
            self.status.setText('อ่านภาพไม่ได้ กรุณาเลือกภาพ PNG / JPEG / BMP')
            return
        if self.points.rowCount() and QMessageBox.question(self, 'เปลี่ยนภาพอ้างอิง',
                'การเปลี่ยนภาพจะล้างจุดอ้างอิงเดิม ต้องการเปลี่ยนภาพหรือไม่?') != QMessageBox.StandardButton.Yes:
            return
        array = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
        rgb = array[:, :image.width()*3].reshape(image.height(), image.width(), 3).copy()
        self.clear_points()
        self.set_reference_image(rgb)

    def capture_changed(self, checked):
        self.canvas.capture = checked
        if not checked:
            self.repick_row = None

    def mode_changed(self):
        mode = self.mode.currentData()
        structured = mode in {'rectangle', 'road'}
        self.width.setEnabled(structured)
        self.length.setEnabled(structured)
        self.canvas.road_outline = mode == 'road'
        self.dimension_form.labelForField(self.width).setText('กว้างขวางถนน P1→P4 (ม.)' if mode == 'road' else 'กว้าง X (เมตร)')
        self.dimension_form.labelForField(self.length).setText('ระยะตามถนน P1→P2 (ม.)' if mode == 'road' else 'ยาว Y (เมตร)')
        self.width.setPlaceholderText('ระยะตั้งฉากขวางถนนที่วัดจริง' if mode == 'road' else 'ระยะ P1 → P2 ที่วัดจริง')
        self.length.setPlaceholderText('ระยะต้นช่วงถึงปลายช่วงตามถนนที่วัดจริง' if mode == 'road' else 'ระยะ P2 → P3 ที่วัดจริง')
        self.points.setHorizontalHeaderLabels(['จุด', 'ภาพ u (px)', 'ภาพ v (px)',
            'ขวาง X (ม.)' if mode == 'road' else 'พื้น X (ม.)', 'ตามถนน Y (ม.)' if mode == 'road' else 'พื้น Y (ม.)'])
        if mode == 'road':
            self.hint.setText('ถนนตรงและพื้นระนาบเดียว: คลิก P1 ต้นช่วง → P2 ปลายช่วง บนขอบเดียวกัน '
                              'แล้ว P3 ปลายช่วง → P4 ต้นช่วง บนอีกขอบหนึ่ง\n'
                              'P1→P2 คือระยะตามรถวิ่ง · P1→P4 คือความกว้างตั้งฉากขวางถนน\n'
                              'ใช้ระยะจริงที่วัดบนพื้นถนน ไม่ใช้ระยะ 2 จุดเป็นสเกลพิกเซลคงที่ทั้งภาพ')
        else:
            self.hint.setText('คลิกมุมของสี่เหลี่ยมจริงเรียงรอบขอบ P1 → P2 → P3 → P4\n'
                          'P1=(0,0), P2=(กว้าง,0), P3=(กว้าง,ยาว), P4=(0,ยาว)'
                          if mode == 'rectangle' else 'คลิกจุดบนภาพ แล้วกรอกพิกัด X,Y จริงเป็นเมตรทุกแถว '
                          'เลือกจุดกำเนิดและทิศแกนร่วมกัน จุดต้องไม่เรียงเป็นเส้นตรง')
        self.dimensions_changed()

    def dimensions_changed(self):
        mode = self.mode.currentData()
        structured = mode in {'rectangle', 'road'}
        try:
            generator = road_points if mode == 'road' else rectangle_points
            coordinates = generator(self.width.text(), self.length.text()) if structured else []
        except ValueError:
            coordinates = []
        self.points.blockSignals(True)
        for row in range(self.points.rowCount()):
            for column in (3, 4):
                item = self.points.item(row, column)
                if structured:
                    item.setText(f'{coordinates[row][column-3]:.10g}' if row < len(coordinates) else '')
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.points.blockSignals(False)
        self.changed()

    def add_point(self, pixel):
        if self.repick_row is not None:
            row = self.repick_row
            self.repick_row = None
            self.points.blockSignals(True)
            for column in (1, 2):
                self.points.item(row, column).setText(f'{pixel[column-1]:.10g}')
            self.points.blockSignals(False)
            self.changed()
            return
        if self.mode.currentData() in {'rectangle', 'road'} and self.points.rowCount() >= 4:
            self.status.setText('โหมดนี้ใช้ 4 จุด เลือกแถวแล้วกด “ย้ายจุดที่เลือก” เพื่อแก้ หรือใช้พิกัดพื้นอิสระ')
            return
        row = self.points.rowCount()
        self.points.blockSignals(True)
        self.points.insertRow(row)
        for column, value in enumerate([f'P{row+1}', f'{pixel[0]:.10g}', f'{pixel[1]:.10g}', '', '']):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.points.setItem(row, column, item)
        self.points.blockSignals(False)
        self.points.selectRow(row)
        self.dimensions_changed()

    def begin_repick(self):
        row = self.points.currentRow()
        if row < 0:
            self.status.setText('เลือกแถวของจุดที่ต้องการย้ายก่อน')
            return
        self.capture.setChecked(True)
        self.repick_row = row
        self.status.setText(f'คลิกตำแหน่งใหม่ของ P{row+1} บนภาพ')

    def remove_point(self):
        row = self.points.currentRow()
        if row >= 0:
            self.repick_row = None
            self.points.removeRow(row)
            for index in range(self.points.rowCount()):
                self.points.item(index, 0).setText(f'P{index+1}')
            self.dimensions_changed()

    def clear_points(self):
        self.repick_row = None
        self.points.setRowCount(0)
        self.changed()

    def selection_changed(self):
        self.repick_row = None
        self.canvas.selected_point = self.points.currentRow()
        self.canvas.redraw()

    def changed(self):
        markers = []
        for row in range(self.points.rowCount()):
            try:
                point = [float(self.points.item(row, column).text()) for column in (1, 2)]
                markers.append(point if np.isfinite(point).all() else [-100., -100.])
            except (ValueError, AttributeError):
                markers.append([-100., -100.])
        self.canvas.control_points = markers
        self.canvas.redraw()
        self.status.setText(f'{self.points.rowCount()} จุด · กรอกพิกัด / ระยะจริง แล้วกดคำนวณเพื่อตรวจอีกครั้ง')

    def calibration(self):
        if self.canvas.image is None:
            raise ValueError('เปิดภาพอ้างอิง หรือเปิดวิดีโอในหน้าจุดสำรวจก่อน')
        mode = self.mode.currentData()
        structured = mode in {'rectangle', 'road'}
        if structured and self.points.rowCount() != 4:
            raise ValueError('โหมดตามแนวถนน / สี่เหลี่ยมต้องเลือกมุมเรียงรอบขอบให้ครบ 4 จุด')
        try:
            pixels = [[float(self.points.item(row, column).text()) for column in (1, 2)]
                      for row in range(self.points.rowCount())]
            generator = road_points if mode == 'road' else rectangle_points
            ground = (generator(self.width.text(), self.length.text()) if structured else
                      [[float(self.points.item(row, column).text()) for column in (3, 4)]
                       for row in range(self.points.rowCount())])
        except (ValueError, AttributeError) as exc:
            raise ValueError('กรอกพิกัดทุกจุดและระยะจริงเป็นตัวเลขให้ครบ') from exc
        height, width = self.canvas.image.shape[:2]
        result = calibrate_camera(pixels, ground, [width, height])
        result['calibration']['mode'] = self.mode.currentData()
        if structured:
            result['calibration'].update(width_m=float(self.width.text()), length_m=float(self.length.text()))
        if mode == 'road':
            result['calibration']['axes'] = dict(x='across_road', y='along_road')
        return result

    def calculate(self):
        try:
            result = self.calibration()
        except ValueError as exc:
            self.status.setText(str(exc))
            return None
        values = result['calibration']
        self.status.setText(f"คำนวณได้ {len(values['image_points'])} จุด · RMSE {values['rmse_m']:.4g} ม. "
                            f"· สูงสุด {values['max_error_m']:.4g} ม. · ย้อนกลับ {values['rmse_px']:.4g} px\n"
                            'ตรวจระยะจริงด้วยจุดอื่นก่อนใช้ผลความเร็ว')
        return result

    def save_to(self, path):
        result = self.calibration()  # Recalculate after every edit, never save a stale fit.
        atomic_text(path, '# Planar mapping: already-undistorted image pixels -> ground metres.\n' +
                    yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
        self.saved_path = str(Path(path).resolve())

    def save(self):
        if self.calculate() is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'บันทึก Camera YAML', self.suggested_path, 'YAML (*.yaml *.yml)')
        if not path:
            return
        if not Path(path).suffix:
            path += '.yaml'
        try:
            self.save_to(path)
        except (ValueError, OSError) as exc:
            self.status.setText(f'บันทึกไม่ได้: {exc}')
            return
        self.accept()
