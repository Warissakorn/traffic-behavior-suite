import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
import yaml
pytest.importorskip('PySide6')
import shiboken6
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QTableWidgetItem
from tbs.gui.camera_dialog import CameraDialog
from tbs.gui.main_window import MainWindow
from tbs.camera_calibration import camera_matrix, project_points
from tbs.config import load_site
from tbs.demo import fixture
from test_gui import pump, dispose


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def rectangle(dialog):
    dialog.width.setText('30')
    dialog.length.setText('10')
    for point in [[10, 10], [310, 10], [310, 110], [10, 110]]:
        dialog.add_point(point)


def test_rectangle_clicks_use_original_pixels_after_zoom_and_can_move_point(app, tmp_path):
    dialog = CameraDialog(np.zeros((120, 320, 3), np.uint8))
    dialog.show()
    app.processEvents()
    dialog.width.setText('30')
    dialog.length.setText('10')
    dialog.canvas.scale(1.2, 1.2)
    for point in [[10, 10], [310, 10], [310, 110], [10, 110]]:
        QTest.mouseClick(dialog.canvas.viewport(), Qt.MouseButton.LeftButton,
                         pos=dialog.canvas.mapFromScene(QPointF(*point)))
    result = dialog.calculate()
    assert result is not None, dialog.status.text()
    np.testing.assert_allclose(result['calibration']['image_points'], [[10, 10], [310, 10], [310, 110], [10, 110]], atol=.6)
    dialog.points.selectRow(0)
    dialog.begin_repick()
    QTest.mouseClick(dialog.canvas.viewport(), Qt.MouseButton.LeftButton,
                     pos=dialog.canvas.mapFromScene(QPointF(12, 12)))
    assert dialog.points.rowCount() == 4
    assert float(dialog.points.item(0, 1).text()) == pytest.approx(12, abs=.6)
    assert dialog.repick_row is None
    dialog.save_to(tmp_path/'กล้อง.yaml')
    saved = yaml.safe_load((tmp_path/'กล้อง.yaml').read_text())
    assert saved['image_size'] == [320, 120]
    assert saved['calibration']['width_m'] == 30
    shiboken6.delete(dialog)


def test_reference_image_accepts_thai_path_and_padded_rgb_rows(app, tmp_path, monkeypatch):
    path = tmp_path/'ภาพอ้างอิง.png'
    image = QImage(321, 121, QImage.Format.Format_RGB888)
    image.fill(QColor(11, 22, 33))
    assert image.save(str(path))
    dialog = CameraDialog()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), 'Images'))
    dialog.choose_image()
    assert dialog.canvas.image.shape == (121, 321, 3)
    assert dialog.canvas.image[-1, -1].tolist() == [11, 22, 33]
    shiboken6.delete(dialog)


def test_invalid_edit_cannot_save_previous_calibration(app, tmp_path):
    dialog = CameraDialog(np.zeros((120, 320, 3), np.uint8))
    rectangle(dialog)
    assert dialog.calculate() is not None
    dialog.width.setText('')
    with pytest.raises(ValueError):
        dialog.save_to(tmp_path/'invalid.yaml')
    assert not (tmp_path/'invalid.yaml').exists()
    dialog.width.setText('60')
    dialog.save_to(tmp_path/'updated.yaml')
    updated = yaml.safe_load((tmp_path/'updated.yaml').read_text())
    assert project_points(camera_matrix(updated), [[160, 60]])[0] == pytest.approx([30, 5])
    shiboken6.delete(dialog)


def test_free_ground_points_support_more_than_four_and_reject_missing_values(app):
    dialog = CameraDialog(np.zeros((120, 320, 3), np.uint8))
    dialog.mode.setCurrentIndex(1)
    for pixel in [[10, 10], [310, 10], [310, 110], [10, 110], [160, 60], [200, 80]]:
        dialog.add_point(pixel)
    assert dialog.calculate() is None
    for row in range(dialog.points.rowCount()):
        for column in (3, 4):
            pixel = float(dialog.points.item(row, column-2).text())
            dialog.points.setItem(row, column, QTableWidgetItem(str(pixel/10)))
    result = dialog.calculate()
    assert result is not None, dialog.status.text()
    assert len(result['calibration']['ground_points']) == 6
    assert result['calibration']['rmse_m'] < 1e-10
    shiboken6.delete(dialog)


def test_main_window_creates_selects_and_validates_camera_without_yaml_editing(app, tmp_path, monkeypatch):
    site = fixture(tmp_path)
    window = MainWindow()
    window.document.open(site)
    window.populate()
    window.load_preview()
    pump(app, lambda: window.setup_player.ready)
    camera = tmp_path/'กล้องใหม่.yaml'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(camera), 'YAML'))
    def fill_and_save(dialog):
        assert dialog.canvas.image.shape == (120, 320, 3)
        rectangle(dialog)
        dialog.save()
        assert dialog.result() == QDialog.DialogCode.Accepted
        return dialog.result()
    monkeypatch.setattr(CameraDialog, 'exec', fill_and_save)
    window.create_camera_button.click()
    assert window.camera_path.text() == str(camera)
    assert window.dirty
    assert window.setup_canvas.matrix is not None
    np.testing.assert_allclose(project_points(window.setup_canvas.matrix, [[160, 60]]), [[15, 5]], atol=1e-10)
    assert 'สร้าง Camera YAML' in window.validation_label.text()
    window.document.config = window.collect()
    saved_site = tmp_path/'site-new.yaml'
    window.document.save(saved_site)
    config = load_site(saved_site)
    assert config['camera']['model_file'] == str(camera)
    dispose(window, app)


def test_cancel_camera_dialog_preserves_selected_camera(app, monkeypatch):
    window = MainWindow()
    window.camera_path.setText('original.yaml')
    window.dirty = False
    monkeypatch.setattr(CameraDialog, 'exec', lambda self: QDialog.DialogCode.Rejected)
    window.create_camera()
    assert window.camera_path.text() == 'original.yaml'
    assert not window.dirty
    dispose(window, app)


def test_wrong_reference_resolution_clears_previous_matrix_in_preview(app, tmp_path):
    site = fixture(tmp_path)
    window = MainWindow()
    window.document.open(site)
    window.populate()
    window.load_preview()
    pump(app, lambda: window.setup_player.ready)
    assert window.setup_canvas.matrix is not None
    dialog = CameraDialog(np.zeros((480, 640, 3), np.uint8))
    rectangle(dialog)
    camera = tmp_path/'wrong-size.yaml'
    dialog.save_to(camera)
    window.camera_path.setText(str(camera))
    assert not window.apply_camera_preview()
    assert window.setup_canvas.matrix is None
    assert 'ไม่ตรง' in window.validation_label.text()
    shiboken6.delete(dialog)
    dispose(window, app)
