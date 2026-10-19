"""Cross-point observations, pair review and reviewed OD exports."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QFileDialog, QDoubleSpinBox,
    QSpinBox, QTabWidget, QAbstractItemView, QHeaderView, QScrollArea, QComboBox)

from ..reid import workflow
from .preview import TaskService
from .widgets import file_field


def grid(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    return widget


def add_row(widget, values):
    row = widget.rowCount()
    widget.insertRow(row)
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setToolTip(str(value))
        widget.setItem(row, column, item)


class ReIDPage(QWidget):
    progress_message = Signal(str)

    def __init__(self, output_field, parent=None):
        super().__init__(parent)
        self.output_field = output_field
        self.tasks = TaskService(self)
        self.tasks.result.connect(self.finished)
        self.cancelled = threading.Event()
        self.result = None
        self.directory = None
        self.offset = 0
        self.page_size = 100
        box = QVBoxLayout(self)
        title = QLabel('จับคู่รถข้ามจุด / ต้นทาง–ปลายทาง')
        title.setObjectName('sectionTitle')
        box.addWidget(title)
        note = QLabel('นำเข้าผลวิเคราะห์จุดสำรวจที่มี track ID · กล้องเดียวที่ย้ายตำแหน่งให้ระบุคนละจุด\n'
                      'OD คือจุดแรก–สุดท้ายที่พบในข้อมูล · ยืนยันคู่รถก่อนนับ · สีใกล้กันอาจเป็นรถคนละคัน')
        note.setWordWrap(True)
        box.addWidget(note)
        self.tabs = QTabWidget()
        box.addWidget(self.tabs, 1)
        self.setup = QWidget()
        setup_box = QVBoxLayout(self.setup)
        self.observations = grid(['ช่วงสำรวจ ID', 'จุดสังเกต', 'โฟลเดอร์ผลวิเคราะห์', 'ชดเชยนาฬิกา (วินาที)', 'เฉพาะจุดผ่านในผล'])
        for column in (0, 1):
            self.observations.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.observations.setColumnWidth(column, 140)
        self.observations.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        setup_box.addWidget(self.observations, 2)
        row = QHBoxLayout()
        self.add_button(row, 'เพิ่มผลวิเคราะห์จุดสำรวจ', self.add_observation)
        self.add_button(row, 'ลบช่วงสำรวจ', lambda: self.observations.removeRow(self.observations.currentRow()))
        setup_box.addLayout(row)
        self.links = grid(['จากจุด', 'ไปจุด', 'เวลาเดินทางต่ำสุด (วินาที)', 'สูงสุด (วินาที)'])
        setup_box.addWidget(self.links, 1)
        row = QHBoxLayout()
        self.add_button(row, 'เพิ่มเส้นทาง', self.add_link)
        self.add_button(row, 'ลบเส้นทาง', lambda: self.links.removeRow(self.links.currentRow()))
        setup_box.addLayout(row)
        form = QFormLayout()
        self.identity_mode = QComboBox()
        self.identity_mode.addItem('ภาพ + เวลา · ไม่ต้องมี Track ID ต่อเนื่อง', 'independent')
        self.identity_mode.addItem('ใช้ Track ID เดียวกันภายใน run (เมื่อมั่นใจว่าต่อเนื่อง)', 'shared_track')
        form.addRow('หลักการเสนอคู่', self.identity_mode)
        self.model = QLineEdit()
        self.model.setPlaceholderText('เว้นว่างเพื่อใช้สีเสนอคู่ให้ตรวจ')
        form.addRow('Vehicle Re-ID ONNX (ถ้ามี)', file_field(self.model, 'เลือกโมเดล Vehicle Re-ID', 'ONNX (*.onnx)'))
        self.reid_device = QComboBox()
        self.reid_device.addItems(['cpu', 'auto', '0', 'cuda:0'])
        self.reid_device.setEditable(True)
        self.reid_device.setToolTip('ONNX Re-ID: auto เลือก CUDA ถ้าพร้อม หรือใช้ CPU; ต้องมี onnxruntime-gpu สำหรับ CUDA')
        form.addRow('อุปกรณ์ Re-ID ONNX', self.reid_device)
        dimensions = QHBoxLayout()
        self.width, self.height = QSpinBox(), QSpinBox()
        for widget, value in [(self.width, 128), (self.height, 256)]:
            widget.setRange(16, 2048)
            widget.setValue(value)
        dimensions.addWidget(QLabel('กว้าง'))
        dimensions.addWidget(self.width)
        dimensions.addWidget(QLabel('สูง'))
        dimensions.addWidget(self.height)
        form.addRow('ขนาดภาพเข้าโมเดล', dimensions)
        self.similarity, self.margin = QDoubleSpinBox(), QDoubleSpinBox()
        self.similarity.setRange(.01, .99)
        self.similarity.setSingleStep(.01)
        self.similarity.setValue(.85)
        self.margin.setRange(0, 1)
        self.margin.setSingleStep(.01)
        self.margin.setValue(.05)
        form.addRow('ความคล้ายขั้นต่ำ (ไม่ใช่ความน่าจะเป็น)', self.similarity)
        form.addRow('ระยะห่างคะแนนคู่ที่กำกวม', self.margin)
        self.destination = QLineEdit(output_field.text())
        self.destination.textChanged.connect(output_field.setText)
        output_field.textChanged.connect(self.destination.setText)
        form.addRow('โฟลเดอร์ผลลัพธ์', file_field(self.destination, 'เลือกโฟลเดอร์ผลจับคู่', '', directory=True))
        setup_box.addLayout(form)
        row = QHBoxLayout()
        self.add_button(row, 'เปิดค่าตั้งค่า', self.open_config)
        self.add_button(row, 'บันทึกค่าตั้งค่า', self.save_config)
        self.add_button(row, 'เปิดผลจับคู่เดิม', self.open_result)
        setup_box.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.setup)
        self.tabs.addTab(scroll, 'จุดสำรวจ / เวลาเดินทาง')
        self.review_panel = QWidget()
        review_box = QVBoxLayout(self.review_panel)
        self.source_filter = QComboBox()
        self.source_filter.addItem('รถต้นทางทั้งหมด', None)
        self.source_filter.currentIndexChanged.connect(self.source_changed)
        review_box.addWidget(self.source_filter)
        self.pairs = grid(['คู่ ID', 'จากจุด / รถ', 'ไปจุด / รถ', 'คล้าย', 'เวลา (วินาที)', 'ข้อเสนอ', 'กำกวม', 'ตรวจแล้ว'])
        self.pairs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pairs.itemSelectionChanged.connect(self.preview_pair)
        review_box.addWidget(self.pairs, 2)
        previews = QHBoxLayout()
        self.left, self.right = QLabel('รถต้นทาง'), QLabel('รถปลายทาง')
        self.left_frame, self.right_frame = QComboBox(), QComboBox()
        self.left_frame.currentIndexChanged.connect(self.show_frames)
        self.right_frame.currentIndexChanged.connect(self.show_frames)
        for label, selector in ((self.left, self.left_frame), (self.right, self.right_frame)):
            label.setMinimumSize(160, 110)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column = QVBoxLayout()
            column.addWidget(label)
            column.addWidget(selector)
            previews.addLayout(column)
        review_box.addLayout(previews)
        self.pair_info = QLabel('เลือกคู่เพื่อเปรียบเทียบภาพ')
        self.pair_info.setWordWrap(True)
        review_box.addWidget(self.pair_info)
        row = QHBoxLayout()
        self.add_button(row, 'ยืนยันว่าเป็นคันเดียวกัน', lambda: self.decide('accepted'))
        self.add_button(row, 'คนละคัน', lambda: self.decide('rejected'))
        self.add_button(row, 'รอตรวจใหม่', lambda: self.decide('pending'))
        self.add_button(row, 'ไม่พบคู่ใน Candidate', self.no_match)
        self.add_button(row, 'ก่อนหน้า', lambda: self.change_page(-1))
        self.add_button(row, 'ถัดไป', lambda: self.change_page(1))
        review_box.addLayout(row)
        self.summary = QLabel('ยังไม่มีผลจับคู่')
        review_box.addWidget(self.summary)
        self.add_button(review_box, 'ส่งออก CSV เส้นทางรถ / OD ที่ยืนยันแล้ว', self.export)
        self.tabs.addTab(self.review_panel, 'ตรวจคู่รถ / ส่งออก OD')
        self.routes_panel = QWidget()
        routes_box = QVBoxLayout(self.routes_panel)
        self.routes = grid(['เส้นทาง ID', 'ต้นทาง', 'ปลายทาง', 'จุดที่พบตามลำดับ', 'ประเภทรถ', 'ออกจากต้นทาง', 'ถึงปลายทาง', 'เวลาเดินทาง (วินาที)'])
        self.routes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        routes_box.addWidget(self.routes, 1)
        routes_box.addWidget(QLabel('เฉพาะคู่ที่ยืนยันแล้ว · จุดแรก–สุดท้ายที่พบ ไม่ใช่จุดเริ่ม–จบทริปจริง · เวลา UTC+07:00'))
        self.route_page = QSpinBox()
        self.route_page.setMinimum(1)
        self.route_page.valueChanged.connect(self.refresh_routes)
        routes_box.addWidget(self.route_page)
        self.add_button(routes_box, 'ส่งออก CSV เส้นทางรถ / OD ที่ยืนยันแล้ว', self.export)
        self.tabs.addTab(self.routes_panel, 'เส้นทางที่ยืนยันแล้ว / OD')
        row = QHBoxLayout()
        self.run_button = self.add_button(row, 'จับคู่รถข้ามจุด', self.start)
        self.run_button.setObjectName('primary')
        self.cancel_button = self.add_button(row, 'ยกเลิก', self.cancelled.set)
        self.cancel_button.setEnabled(False)
        box.addLayout(row)
        self.status = QLabel('พร้อม · เวลาแก้ไข = เวลาในผลวิเคราะห์ + ค่าชดเชยนาฬิกา')
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.progress_message.connect(self.status.setText)

    def add_button(self, layout, text, function):
        button = QPushButton(text)
        button.clicked.connect(function)
        layout.addWidget(button)
        return button

    def busy(self):
        return self.tasks.task is not None or self.tasks.pending is not None

    def add_observation(self, checked=False, path=None):
        path = path or QFileDialog.getExistingDirectory(self, 'เลือกผลวิเคราะห์ที่มี manifest.json และ vehicles.parquet')
        if not path:
            return
        try:
            manifest = json.loads((Path(path) / 'manifest.json').read_text(encoding='utf-8'))
            if manifest.get('status') != 'completed' or manifest.get('run_mode', 'site') != 'site':
                raise ValueError('เลือกผลวิเคราะห์จุดสำรวจที่เสร็จแล้ว ไม่ใช่ detection test')
            point = manifest['site_id']
            gates = self.gate_choices(path)
            used = {self.cell(self.observations, row, 4) for row in range(self.observations.rowCount())
                    if self.cell(self.observations, row, 2) == path}
            selected = next((gate for gate in gates if gate not in used), None)
            point = selected or point
            add_row(self.observations, [f"{point}_{self.observations.rowCount()+1}", point, path, 0, ''])
            self.add_point_selector(self.observations.rowCount()-1, path, selected)
            self.status.setText('แก้ชื่อจุดให้ตรงตำแหน่งจริง และระบุเส้นทางกับเวลาเดินทาง')
        except (ValueError, OSError, KeyError) as exc:
            self.status.setText(str(exc))

    def cell(self, widget, row, column):
        selector = widget.cellWidget(row, column)
        if isinstance(selector, QComboBox):
            return selector.currentData() or ''
        item = widget.item(row, column)
        return item.text().strip() if item else ''

    def gate_choices(self, path):
        try:
            config = json.loads((Path(path)/'config.resolved.json').read_text(encoding='utf-8'))
            return [g['id'] for g in config.get('image_regions', {}).get('points', [])]
        except (ValueError, OSError):
            return []

    def add_point_selector(self, row, path, selected=None):
        selector = QComboBox()
        selector.addItem('ทั้งช่วงสำรวจ', None)
        choices = self.gate_choices(path)
        if selected and selected not in choices:
            choices.append(selected)
        for gate in choices:
            selector.addItem(gate, gate)
        selector.setCurrentIndex(max(0, selector.findData(selected)))
        self.observations.setCellWidget(row, 4, selector)

    def add_link(self):
        points = [self.cell(self.observations, row, 1) for row in range(self.observations.rowCount())]
        add_row(self.links, [points[0] if points else 'A', points[1] if len(points) > 1 else 'B', 1, 300])

    def config(self):
        observations = [dict(id=self.cell(self.observations, row, 0), point_id=self.cell(self.observations, row, 1),
                             run=self.cell(self.observations, row, 2), clock_offset_s=float(self.cell(self.observations, row, 3)))
                        for row in range(self.observations.rowCount())]
        for row, observation in enumerate(observations):
            selected = self.cell(self.observations, row, 4)
            if selected:
                observation['passage_point'] = selected
        links = [dict(zip(['from', 'to', 'min_travel_s', 'max_travel_s'],
                          [self.cell(self.links, row, 0), self.cell(self.links, row, 1),
                           float(self.cell(self.links, row, 2)), float(self.cell(self.links, row, 3))]))
                 for row in range(self.links.rowCount())]
        options = dict(min_similarity=self.similarity.value(), ambiguity_margin=self.margin.value(),
                       identity_mode=self.identity_mode.currentData(),
                       reid_device=self.reid_device.currentText().strip(),
                       input_size=[self.width.value(), self.height.value()])
        if self.model.text().strip():
            options['reid_model'] = self.model.text().strip()
        return workflow.validate_config(dict(schema_version=1, observations=observations, links=links, options=options))

    def populate(self, config):
        self.observations.setRowCount(0)
        self.links.setRowCount(0)
        for observation in config['observations']:
            add_row(self.observations, [observation[key] for key in ['id', 'point_id', 'run', 'clock_offset_s']])
            self.add_point_selector(self.observations.rowCount()-1, observation['run'], observation.get('passage_point'))
        for link in config['links']:
            add_row(self.links, [link[key] for key in ['from', 'to', 'min_travel_s', 'max_travel_s']])
        options = config['options']
        self.identity_mode.setCurrentIndex(max(0, self.identity_mode.findData(options.get('identity_mode', 'independent'))))
        self.reid_device.setCurrentText(options.get('reid_device', 'cpu'))
        self.model.setText(options.get('reid_model', ''))
        self.similarity.setValue(options['min_similarity'])
        self.margin.setValue(options['ambiguity_margin'])
        self.width.setValue(options['input_size'][0])
        self.height.setValue(options['input_size'][1])

    def open_config(self):
        path, _ = QFileDialog.getOpenFileName(self, 'เปิดค่าจับคู่', '', 'YAML / JSON (*.yaml *.yml *.json)')
        if path:
            try:
                self.populate(workflow.load_config(path))
            except (ValueError, OSError, KeyError) as exc:
                self.status.setText(str(exc))

    def save_config(self):
        try:
            config = self.config()
            path, _ = QFileDialog.getSaveFileName(self, 'บันทึกค่าจับคู่', 'od-config.json', 'JSON (*.json)')
            if path:
                workflow.atomic_json(path, config)
                self.status.setText('บันทึกค่าตั้งค่าแล้ว')
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def begin(self, function, cancel=False):
        if self.busy():
            return
        self.setup.setEnabled(False)
        self.review_panel.setEnabled(False)
        self.routes_panel.setEnabled(False)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(cancel)
        self.tasks.request(function)

    def start(self):
        if self.busy():
            return
        try:
            config, output = self.config(), self.output_field.text().strip()
            if not output:
                raise ValueError('เลือกโฟลเดอร์ผลลัพธ์ก่อน')
            self.cancelled.clear()
            def work():
                directory, result = workflow.run(config, output, should_cancel=self.cancelled.is_set,
                                                  on_progress=self.progress_message.emit)
                return 'load', directory, result
            self.begin(work, cancel=True)
            self.status.setText('กำลังอ่านผลวิเคราะห์และเตรียมภาพรถ…')
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def open_result(self, checked=False, path=None):
        path = path or QFileDialog.getExistingDirectory(self, 'เปิดผลจับคู่ข้ามจุด')
        if path:
            self.begin(lambda: ('load', path, workflow.load_result(path)))

    def finished(self, payload, error):
        self.setup.setEnabled(True)
        self.review_panel.setEnabled(True)
        self.routes_panel.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if error:
            self.status.setText(error)
            return
        kind, directory, result = payload
        if kind in {'load', 'review'}:
            self.directory, self.result = directory, result
            if kind == 'load':
                self.offset = 0
                self.populate(result['config'])
                self.source_filter.blockSignals(True)
                self.source_filter.clear()
                self.source_filter.addItem('รถต้นทางทั้งหมด', None)
                source_points = {link['from'] for link in result['config']['links']}
                for sighting in result['sightings']:
                    if sighting['point_id'] in source_points:
                        self.source_filter.addItem(f"{sighting['point_id']} · ID ภายใน {sighting['local_vehicle_id']} · "
                                                   f"{self.time_text(sighting['entry_time'])}", sighting['id'])
                self.source_filter.blockSignals(False)
            self.refresh()
            self.tabs.setCurrentWidget(self.review_panel)
            method = result['appearance']['method']
            self.status.setText(f'ผลลัพธ์: {directory} · {method} · ต้องยืนยันคู่ก่อนนับ OD')
        else:
            self.status.setText(f'ส่งออก CSV ที่ยืนยันแล้ว: {directory}')

    def refresh(self):
        self.pairs.setRowCount(0)
        lookup = {s['id']: s for s in self.result['sightings']}
        for pair in self.filtered_candidates()[self.offset:self.offset+self.page_size]:
            a, b = lookup[pair['source']], lookup[pair['target']]
            add_row(self.pairs, [f"{pair.get('rank', '—')} · {pair['id']}", f"{a['point_id']} / {a['local_vehicle_id']}",
                                f"{b['point_id']} / {b['local_vehicle_id']}", f"{pair['similarity']:.3f}",
                                f"{pair['travel_s']:.2f}", ('ID เดียวกัน' if pair.get('identity_method') == 'shared_track'
                                else 'เสนอ') if pair['suggested'] else 'ทางเลือก',
                                'กำกวม' if pair['ambiguous'] else '',
                                {'pending': 'รอตรวจ', 'accepted': 'ยืนยัน', 'rejected': 'คนละคัน'}[pair['status']]])
        accepted = sum(c['status'] == 'accepted' for c in self.result['candidates'])
        self.summary.setText(f"รายการรถที่พบ {len(lookup)} · คู่เสนอ/ทางเลือกทั้งหมด {len(self.result['candidates'])} · "
                             f"ยืนยัน {accepted} คู่ · เส้นทางยืนยัน {len(self.result['journeys'])} · "
                             f"ระบุไม่พบคู่ {len(self.result.get('source_reviews', {}))} รายการ · "
                             f'หน้าที่ {self.offset//self.page_size+1}')
        self.route_page.setMaximum(max(1, (len(self.result['journeys']) + self.page_size - 1) // self.page_size))
        self.refresh_routes()
        if self.pairs.rowCount():
            visible = self.filtered_candidates()[self.offset:self.offset+self.page_size]
            pending = next((i for i, pair in enumerate(visible) if pair['status'] == 'pending'), 0)
            self.pairs.selectRow(pending)
        else:
            self.left.clear()
            self.right.clear()
            self.pair_info.setText('ไม่พบคู่ตามช่วงเวลาและความคล้ายที่ตั้งไว้ · ตรวจนาฬิกาและเส้นทาง')
            self.left_frame.clear()
            self.right_frame.clear()
            source = lookup.get(self.source_filter.currentData())
            if source:
                self.set_gallery(self.left_frame, source)
                self.show_frames()

    def filtered_candidates(self):
        if not self.result:
            return []
        source = self.source_filter.currentData()
        if source:
            return sorted([c for c in self.result['candidates'] if c['source'] == source],
                          key=lambda c: (-c['similarity'], c['travel_s'], c['id']))
        return self.result['candidates']

    def source_changed(self):
        self.offset = 0
        if self.result:
            self.refresh()

    def current_pair(self):
        index = self.pairs.currentRow()
        if not self.result or index < 0:
            return None
        candidates = self.filtered_candidates()
        return candidates[self.offset + index] if self.offset + index < len(candidates) else None

    def preview_pair(self):
        pair = self.current_pair()
        if pair is None:
            return
        lookup = {s['id']: s for s in self.result['sightings']}
        descriptions = []
        for key, selector in [('source', self.left_frame), ('target', self.right_frame)]:
            sighting = lookup[pair[key]]
            self.set_gallery(selector, sighting)
            time = self.time_text(sighting['entry_time'])
            descriptions.append(f"{sighting['observation_id']} · รถ {sighting['local_vehicle_id']} · {time}")
        self.pair_info.setText(' → '.join(descriptions) + '\nความคล้ายเป็นคะแนนเปรียบเทียบ ไม่ใช่ความน่าจะเป็นว่าเป็นคันเดียวกัน')
        self.show_frames()

    def set_gallery(self, selector, sighting):
        selector.blockSignals(True)
        selector.clear()
        crops = sighting.get('crops') or [dict(path=sighting['crop'], time=sighting['entry_time'])]
        for index, crop in enumerate(crops, 1):
            selector.addItem(f"ภาพ {index} · {self.time_text(crop['time'])}", crop['path'])
        selector.blockSignals(False)

    def show_frames(self):
        for label, selector in ((self.left, self.left_frame), (self.right, self.right_frame)):
            path = selector.currentData()
            if path and self.directory:
                pixmap = QPixmap(str(Path(self.directory) / path))
                label.setPixmap(pixmap.scaled(300, 180, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
            else:
                label.clear()

    def time_text(self, value):
        return datetime.fromtimestamp(value, timezone(timedelta(hours=7))).isoformat(timespec='seconds')

    def refresh_routes(self):
        self.routes.setRowCount(0)
        if self.result:
            offset = (self.route_page.value() - 1) * self.page_size
            for route in self.result['journeys'][offset:offset+self.page_size]:
                add_row(self.routes, [route['journey_id'], route['origin'], route['destination'],
                                      ' → '.join(route['points']), route['class_id'],
                                      self.time_text(route['departure_time']), self.time_text(route['arrival_time']),
                                      f"{route['travel_s']:.2f}"])

    def decide(self, decision):
        pair = self.current_pair()
        if pair and not self.busy():
            directory, result, pair_id = self.directory, self.result, pair['id']
            self.begin(lambda: ('review', directory, workflow.save_review(directory, result, pair_id, decision)))
        elif decision == 'pending' and self.result and not self.busy():
            source = self.source_filter.currentData()
            if source:
                directory, result = self.directory, self.result
                self.begin(lambda: ('review', directory, workflow.clear_no_match(directory, result, source)))

    def change_page(self, delta):
        if self.result:
            last = max(0, (len(self.filtered_candidates()) - 1) // self.page_size) * self.page_size
            self.offset = min(last, max(0, self.offset + delta*self.page_size))
            self.refresh()

    def no_match(self):
        pair = self.current_pair()
        source = self.source_filter.currentData() or (pair['source'] if pair else None)
        if source and self.result and not self.busy():
            directory, result = self.directory, self.result
            self.begin(lambda: ('review', directory, workflow.save_no_match(directory, result, source)))

    def export(self):
        if not self.result or self.busy():
            return
        directory = QFileDialog.getExistingDirectory(self, 'เลือกโฟลเดอร์ CSV ว่าง')
        if directory:
            result = self.result
            def work():
                workflow.export_csv(result, directory)
                return 'export', directory, None
            self.begin(work)

    def stop(self):
        self.cancelled.set()
        return self.tasks.stop()
