import time
import numpy as np
import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit
import shiboken6

from test_spatial import point_run, within_camera_config
from tbs.gui.preview import Canvas
from tbs.gui.spatial_editor import SpatialEditor
from tbs.gui.main_window import MainWindow
from tbs.gui.reid_page import ReIDPage
from tbs.reid import workflow


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    return QApplication.instance() or QApplication([])


def pump(app, predicate):
    deadline = time.monotonic()+20
    while not predicate() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def test_roi_and_point_drawing_work_in_pixels_without_calibration(app):
    canvas = Canvas()
    canvas.resize(640, 400)
    canvas.show()
    canvas.set_image(np.zeros((120, 320, 3), np.uint8))
    editor = SpatialEditor(canvas)
    app.processEvents()
    canvas.scale(1.5, 1.5)
    def click(x, y):
        QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton,
                         pos=canvas.mapFromScene(QPointF(x, y)))
    editor.begin('roi')
    click(10, 10)
    click(200, 100)
    assert np.allclose(editor.values()['roi'], [[10, 10], [200, 10], [200, 100], [10, 100]], atol=.6)
    editor.point_name.setText('A')
    editor.begin('point')
    click(50, 20)
    click(50, 100)
    assert editor.values()['points'][0]['id'] == 'A'
    assert np.allclose(editor.values()['points'][0]['p1'], [50, 20], atol=.6)
    assert canvas.matrix is None
    editor.begin('roi')
    click(20, 20)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.image_draw is None and canvas.image_first is None
    editor.clear_roi()
    assert editor.values()['roi'] == []
    shiboken6.delete(editor)
    shiboken6.delete(canvas)


def test_site_geometry_roundtrips_collect_and_results_filter(app, point_run):
    directory, _, _ = point_run
    window = MainWindow()
    import json
    config = json.loads((directory / 'config.resolved.json').read_text())
    window.document.config = config
    window.populate()
    assert window.collect()['image_regions'] == config['image_regions']
    window.load_result(directory)
    pump(app, lambda: window.store is not None and window.result_tasks.task is None)
    window.point_filter.setCurrentIndex(window.point_filter.findData('A'))
    pump(app, lambda: window.store.point_filter == 'A' and window.result_tasks.task is None)
    assert [v['vehicle_id'] for v in window.store.page('vehicles')] == [1]
    assert len(window.review_canvas.point_gates) == 3
    assert window.stop_services()
    window.dirty = False
    window.close()
    shiboken6.delete(window)


def test_same_run_gui_import_selects_different_point_gates_and_matches(app, point_run, tmp_path):
    directory, _, _ = point_run
    page = ReIDPage(QLineEdit(str(tmp_path / 'matches')))
    page.add_observation(path=str(directory))
    page.add_observation(path=str(directory))
    assert page.cell(page.observations, 0, 4) == 'A'
    assert page.cell(page.observations, 1, 4) == 'B'
    assert page.cell(page.observations, 0, 1) == 'A'
    assert page.cell(page.observations, 1, 1) == 'B'
    page.populate(workflow.validate_config(within_camera_config(directory)))
    page.start()
    pump(app, lambda: not page.busy())
    assert page.result is not None, page.status.text()
    assert len(page.result['candidates']) == 1
    assert page.result['candidates'][0]['identity_method'] == 'shared_track'
    assert 'ID เดียวกัน' in page.pairs.item(0, 5).text()
    assert page.stop()
    shiboken6.delete(page)
