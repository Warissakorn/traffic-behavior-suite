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
from test_roi_crop import cropped_video


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


def test_crop_choice_roundtrips_and_is_cleared_with_roi(app, tmp_path):
    from tbs.gui.site_document import SiteDocument
    canvas = Canvas()
    editor = SpatialEditor(canvas)
    assert not editor.crop_before_detect.isEnabled()
    editor.roi_drawn([[10, 10], [200, 10], [200, 100], [10, 100]])
    editor.crop_before_detect.setChecked(True)
    assert editor.values()['crop_before_detect'] is True
    document = SiteDocument()
    document.config['image_regions'] = editor.values()
    path = tmp_path/'site.yaml'
    document.save(path)
    restored = SiteDocument()
    restored.open(path)
    editor.set_regions(restored.config['image_regions'])
    assert editor.crop_before_detect.isChecked()
    assert editor.values()['roi'] == [[10, 10], [200, 10], [200, 100], [10, 100]]
    editor.clear_roi()
    assert not editor.crop_before_detect.isChecked() and not editor.crop_before_detect.isEnabled()
    assert not editor.values().get('crop_before_detect', False)
    shiboken6.delete(editor)
    shiboken6.delete(canvas)


def test_cropped_run_overlay_stays_on_full_video_frame(app, cropped_video):
    window = MainWindow()
    window.load_result(cropped_video)
    pump(app, lambda: window.store is not None and window.review_canvas.image is not None)
    window.review_slider.setValue(25)
    window.request_review()
    pump(app, lambda: bool(window.review_canvas.detections) and window.review_canvas.detections[0]['frame_index'] == 25)
    assert window.review_canvas.image.shape == (120, 320, 3)
    box = window.review_canvas.detections[0]
    assert [box[key] for key in ['x1', 'y1', 'x2', 'y2']] == [120, 50, 140, 70]
    assert window.review_canvas.roi == [[30, 20], [180, 20], [180, 100], [30, 100]]
    assert window.stop_services()
    window.dirty = False
    window.close()
    shiboken6.delete(window)


def test_model_preview_and_site_transfer_keep_full_image_and_crop_choice(app, tmp_path, monkeypatch):
    from tbs.demo import fixture
    from tbs.detection import SyntheticColorDetector
    fixture(tmp_path)
    model = tmp_path/'local.pt'
    model.write_bytes(b'fixture weights')
    window = MainWindow()
    page = window.video_page
    page.open_video(tmp_path/'synthetic.mkv')
    pump(app, lambda: page.player.ready)
    page.model_path.setText(str(model))
    page.spatial_editor.roi_drawn([[10, 20], [100, 20], [100, 100], [10, 100]])
    page.spatial_editor.crop_before_detect.setChecked(True)
    shapes = []
    class Detector(SyntheticColorDetector):
        def detect(self, image):
            shapes.append(image.shape)
            return super().detect(image)
    monkeypatch.setattr('tbs.detection.make_detector', lambda config: Detector())
    page.model_selector.check_current()
    pump(app, lambda: not page.model_selector.busy())
    assert shapes == [(80, 90, 3)]
    assert page.player.canvas.image.shape == (120, 320, 3)
    box = page.player.canvas.detections[0]
    assert [box[key] for key in ['x1', 'y1', 'x2', 'y2']] == [20, 50, 40, 70]
    emitted = []
    page.run_requested.disconnect(window.start_video_test)
    page.run_requested.connect(emitted.append)
    page.start_test()
    assert emitted[-1]['image_regions']['crop_before_detect'] is True
    page.use_site()
    pump(app, lambda: window.setup_player.ready)
    assert window.spatial_editor.crop_before_detect.isChecked()
    assert window.collect()['image_regions']['crop_before_detect'] is True
    assert window.stop_services()
    window.dirty = False
    window.close()
    shiboken6.delete(window)


def test_roi_changed_during_model_check_discards_previous_preview(app, tmp_path, monkeypatch):
    import threading
    from tbs.gui.model_selector import ModelSelector
    from tbs.models import ModelRegistry, file_hash
    model = tmp_path/'model.pt'
    model.write_bytes(b'fixture weights')
    selector = ModelSelector(registry=ModelRegistry(tmp_path/'models.json'))
    selector.path.setText(str(model))
    canvas = Canvas()
    editor = SpatialEditor(canvas, allow_points=False)
    editor.roi_drawn([[10, 10], [50, 10], [50, 50], [10, 50]])
    editor.crop_before_detect.setChecked(True)
    selector.regions_provider = editor.values
    selector.image_provider = lambda: np.zeros((100, 100, 3), np.uint8)
    entered, release = threading.Event(), threading.Event()
    checked = []
    def check(path, options, image, expected, image_regions):
        entered.set()
        assert release.wait(5)
        return dict(model=dict(filename=model.name, format='pt', sha256=file_hash(model)), detections=[])
    monkeypatch.setattr('tbs.gui.model_selector.check_model', check)
    selector.checked.connect(checked.append)
    selector.check_current()
    try:
        pump(app, entered.is_set)
        editor.crop_before_detect.setChecked(False)
    finally:
        release.set()
    pump(app, lambda: not selector.busy())
    assert checked == []
    assert 'ROI เปลี่ยน' in selector.info.text()
    assert selector.stop()
    shiboken6.delete(selector)
    shiboken6.delete(editor)
    shiboken6.delete(canvas)
