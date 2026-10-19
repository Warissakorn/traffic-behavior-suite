"""Bounded background requests and an image-coordinate geometry canvas."""
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Qt, QPointF
from PySide6.QtGui import QImage, QPixmap, QPen, QColor, QPolygonF, QBrush
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QLabel, QGraphicsItem
from ..video import VideoReader


class Task(QThread):
    result = Signal(int, object, str)

    def __init__(self, token, function, parent=None):
        super().__init__(parent)
        self.token, self.function = token, function

    def run(self):
        try:
            self.result.emit(self.token, self.function(), "")
        except Exception as exc:
            self.result.emit(self.token, None, f"{type(exc).__name__}: {exc}")


class TaskService(QObject):
    result = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.pending = None
        self.token = 0

    def request(self, function):
        self.token += 1
        self.pending = (self.token, function)
        if self.task is None:
            self._next()

    def _next(self):
        if self.pending is None:
            return
        token, function = self.pending
        self.pending = None
        self.task = Task(token, function, self)
        self.task.result.connect(self._result)
        self.task.finished.connect(self._done)
        self.task.start()

    def _result(self, token, payload, error):
        if token == self.token:
            self.result.emit(payload, error)

    def _done(self):
        self.task.deleteLater()
        self.task = None
        self._next()

    def stop(self):
        self.pending = None
        self.token += 1
        return self.task is None or self.task.wait(5000)


def decode_image(path, t_video=0.0):
    reader = VideoReader()
    try:
        return reader.read(path, t_video)["image"]
    finally:
        reader.close()


def projection(matrix, point):
    value = np.asarray(matrix, dtype=float) @ [point[0], point[1], 1.0]
    if not np.isfinite(value).all() or abs(value[2]) < 1e-12:
        raise ValueError("จุดอยู่นอกบริเวณที่ฉายลงพื้นได้")
    return value[:2]/value[2]


class Canvas(QGraphicsView):
    line_changed = Signal(str, object, object)
    roi_changed = Signal(object)
    point_changed = Signal(str, object, object)
    problem = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setMinimumSize(160, 180)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.matrix = None
        self.lines = []
        self.detections = []
        self.image = None
        self.selected = None
        self.drawing = False
        self.first = None
        self.drag = None
        self.auto_fit = True
        self.roi = []
        self.point_gates = []
        self.image_draw = None
        self.image_first = None
        self.setBackgroundBrush(QColor("#111c2e"))
        self.placeholder = QLabel("ยังไม่มีภาพวิดีโอ\nเลือกไฟล์วิดีโอเพื่อเริ่ม", self.viewport())
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("color:#b7c5d9;background:transparent;font-size:16px;")
        self.placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_image(self, image, fit=True):
        self.image = np.ascontiguousarray(image)
        self.redraw()
        if fit:
            self.fit_image()

    def fit_image(self):
        self.auto_fit = True
        if self.image is not None:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.placeholder.setGeometry(self.viewport().rect())
        if self.auto_fit and self.image is not None:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def redraw(self):
        self.scene().clear()
        self.placeholder.setVisible(self.image is None)
        if self.image is None:
            return
        height, width, _ = self.image.shape
        qimage = QImage(self.image.data, width, height, self.image.strides[0], QImage.Format.Format_RGB888).copy()
        self.scene().addPixmap(QPixmap.fromImage(qimage))
        self.setSceneRect(0, 0, width, height)
        roi_pen = QPen(QColor('#ffaf45'), 2)
        roi_pen.setCosmetic(True)
        if self.roi:
            self.scene().addPolygon(QPolygonF([QPointF(*p) for p in self.roi]), roi_pen,
                                    QBrush(QColor(255, 175, 69, 30)))
        for gate in self.point_gates:
            pen = QPen(QColor('#dd88ff'), 2)
            pen.setCosmetic(True)
            self.scene().addLine(*gate['p1'], *gate['p2'], pen)
            label = self.scene().addText(gate['id'] + ' p1→p2')
            label.setDefaultTextColor(pen.color())
            label.setPos(*gate['p1'])
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        if self.image_first is not None:
            marker = self.scene().addEllipse(-4, -4, 8, 8, roi_pen)
            marker.setPos(*self.image_first)
            marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        if self.matrix is not None:
            inverse = np.linalg.inv(self.matrix)
            for line in self.lines:
                try:
                    a, b = projection(inverse, line["p1"]), projection(inverse, line["p2"])
                except ValueError:
                    continue
                pen = QPen(QColor("#ffca45" if line["id"] == self.selected else "#38dfbf"), 2)
                pen.setCosmetic(True)
                self.scene().addLine(*a, *b, pen)
                for point in (a,b):
                    marker = self.scene().addEllipse(-4, -4, 8, 8, pen)
                    marker.setPos(*point)
                    marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                label = self.scene().addText(line["id"]+"  p1→p2")
                label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                label.setDefaultTextColor(pen.color())
                label.setPos(*a)
        pen = QPen(QColor("#65b7ff"), 2)
        pen.setCosmetic(True)
        for row in self.detections:
            self.scene().addRect(row["x1"], row["y1"], row["x2"]-row["x1"], row["y2"]-row["y1"], pen)
            identity = f"ID {row['track_id']} · " if row.get("track_id") is not None else ""
            label = self.scene().addText(f"{identity}class {row['class_id']} · {row['score']:.0%}")
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            label.setDefaultTextColor(QColor("#ffffff"))
            label.setPos(row["x1"], row["y1"])
        if self.first is not None:
            marker = self.scene().addEllipse(-4,-4,8,8,pen)
            marker.setPos(*self.first)
            marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)

    def wheelEvent(self, event):
        self.auto_fit = False
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        if 0.02 < self.transform().m11()*factor < 30:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        pixel = np.array([point.x(), point.y()])
        if self.image_draw and event.button() == Qt.MouseButton.LeftButton and self.image is not None:
            if not (0 <= pixel[0] <= self.image.shape[1] and 0 <= pixel[1] <= self.image.shape[0]):
                event.accept()
                return
            if self.image_first is None:
                self.image_first = pixel.tolist()
            else:
                first, second = np.array(self.image_first), pixel
                if np.linalg.norm(first-second) < 1:
                    self.problem.emit('เลือกสองจุดที่ต่างกันอย่างน้อย 1 พิกเซล')
                    event.accept()
                    return
                mode, key = self.image_draw
                if mode == 'roi':
                    x1, y1 = np.minimum(first, second)
                    x2, y2 = np.maximum(first, second)
                    if x2-x1 < 1 or y2-y1 < 1:
                        self.problem.emit('กรอบ ROI ต้องมีความกว้างและความสูง')
                        event.accept()
                        return
                    self.roi_changed.emit(np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]]).tolist())
                else:
                    self.point_changed.emit(key, first.tolist(), second.tolist())
                self.image_draw, self.image_first = None, None
            self.redraw()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.matrix is not None and self.image is not None:
            if self.drawing:
                if not (0 <= pixel[0] <= self.image.shape[1] and 0 <= pixel[1] <= self.image.shape[0]):
                    return
                try:
                    ground = projection(self.matrix, pixel)
                    if self.first is None:
                        self.first = pixel
                        self.redraw()
                    else:
                        a = projection(self.matrix, self.first)
                        if np.linalg.norm(a-ground) < 1e-6:
                            raise ValueError("เส้นนับต้องมีสองจุดต่างกัน")
                        self.line_changed.emit(self.selected or "line", a.tolist(), ground.tolist())
                        self.first, self.drawing = None, False
                        self.redraw()
                except ValueError as exc:
                    self.problem.emit(str(exc))
                event.accept()
                return
            inverse = np.linalg.inv(self.matrix)
            for line in self.lines:
                if line["id"] == self.selected:
                    for key in ("p1", "p2"):
                        if np.linalg.norm(projection(inverse,line[key])-pixel) < 12/max(self.transform().m11(), .01):
                            self.drag = (line,key)
                            event.accept()
                            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.image_draw:
            self.image_draw = self.image_first = None
            self.redraw()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            point = self.mapToScene(event.position().toPoint())
            try:
                ground = projection(self.matrix, [point.x(),point.y()])
                line,key = self.drag
                line[key] = ground.tolist()
                self.line_changed.emit(line["id"],line["p1"],line["p2"])
                self.redraw()
            except ValueError as exc:
                self.problem.emit(str(exc))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag is not None:
            self.drag = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
