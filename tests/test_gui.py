import os
import time
import json
from pathlib import Path
import pytest

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
import shiboken6
from tbs.gui.main_window import MainWindow
from tbs.gui.preview import projection, decode_image
from tbs.demo import fixture
import numpy as np


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def pump(app,condition,timeout=30):
    deadline=time.monotonic()+timeout
    while not condition() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.005)
    assert condition(),"Qt operation timed out"


def dispose(window,app):
    assert window.stop_services()
    window.dirty=False
    window.close()
    shiboken6.delete(window)
    app.processEvents()


def test_geometry_roundtrip_with_zoom(app,tmp_path):
    path=fixture(tmp_path)
    w=MainWindow()
    w.document.open(path)
    w.populate()
    w.setup_canvas.matrix=np.diag([.1,.1,1])
    w.setup_canvas.set_image(decode_image(tmp_path/"synthetic.mkv"))
    w.setup_canvas.scale(2,2)
    source=QPointF(100,50)
    viewport=w.setup_canvas.mapFromScene(source)
    returned=w.setup_canvas.mapToScene(viewport)
    ground=projection(w.setup_canvas.matrix,[returned.x(),returned.y()])
    assert ground==pytest.approx([10,5],abs=.1)
    w.line_changed("mid",[12,0],[12,12])
    assert w.collect()["road"]["count_lines"][0]["p1"]==[12,0]
    dispose(w,app)


def test_gui_demo_and_result_loading(app,tmp_path):
    w=MainWindow()
    w.output_path.setText(str(tmp_path/"ผลลัพธ์ A"))
    events=[]
    w.job.finished.connect(lambda status,message: events.append(status))
    w.start_demo()
    pump(app,lambda: bool(events))
    assert events==["completed"],w.log.toPlainText()
    pump(app,lambda: w.store is not None and w.counts_table.rowCount()==1)
    assert "50 frames" in w.summary.text()
    assert w.progress.value()==100
    assert w.review_slider.maximum()==49
    dispose(w,app)


def test_qprocess_cancel(app,tmp_path):
    w=MainWindow()
    w.output_path.setText(str(tmp_path/"output"))
    statuses=[]
    w.job.finished.connect(lambda status,message: statuses.append(status))
    w.start_demo()
    w.job.cancel()
    pump(app,lambda: bool(statuses))
    assert statuses==["cancelled"]
    assert w.progress.value()==0
    dispose(w,app)


def test_video_open_seek_and_transfer_without_calibration(app,tmp_path):
    fixture(tmp_path)
    w=MainWindow()
    page=w.video_page
    page.open_video(tmp_path/"synthetic.mkv")
    pump(app,lambda: page.player.ready)
    assert page.player.canvas.matrix is None
    assert page.player.canvas.image.shape == (120,320,3)
    page.player.slider.setValue(2500)
    pump(app,lambda: abs(page.player.position-2.5)<.001)
    page.player.toggle_play()
    pump(app,lambda: page.player.position>2.5)
    page.player.pause()
    assert not page.player.timer.isActive()
    page.model_path.setText(str(tmp_path/"missing.pt"))
    page.start_test()
    assert "ไม่พบ" in page.error_label.text()
    page.model_path.clear()
    page.use_site()
    pump(app,lambda: w.setup_player.ready)
    assert w.setup_canvas.matrix is None
    assert w.collect()["videos"][0]["path"] == str(tmp_path/"synthetic.mkv")
    dispose(w,app)


def test_video_results_show_pixel_overlay(app,tmp_path,monkeypatch):
    from tbs.video_test import run
    from tbs.detection import SyntheticColorDetector
    fixture(tmp_path)
    weights=tmp_path/"test.pt"
    weights.write_bytes(b"test-only adapter")
    config=tmp_path/"video.json"
    config.write_text(json.dumps(dict(video=str(tmp_path/"synthetic.mkv"),detector=str(weights))))
    monkeypatch.setattr("tbs.video_test.make_detector",lambda config:SyntheticColorDetector())
    out,_=run(config,tmp_path/"output")
    w=MainWindow()
    w.load_result(out)
    pump(app,lambda: w.store is not None and bool(w.review_canvas.detections))
    assert w.review_canvas.matrix is None
    assert w.dataset.currentText()=="detections"
    assert w.review_canvas.detections[0]["track_id"] is None
    assert "50 detections" in w.summary.text()
    dispose(w,app)


def test_video_import_times_and_overlap_preflight(app,tmp_path):
    fixture(tmp_path)
    w=MainWindow()
    paths=[str(tmp_path/"synthetic.mkv")]*2
    w.add_videos(paths)
    pump(app,lambda: w.videos.rowCount()==2)
    from tbs.config import timestamp
    starts=[timestamp(w.cell(w.videos,index,1)) for index in [0,1]]
    assert starts[1]-starts[0] >= 4.9
    # Use the fixture's calibration and synthetic model to validate the site.
    w.camera_path.setText(str(tmp_path/"camera.yaml"))
    w.model_path.setText("synthetic_color")
    assert w.validate_site()
    pump(app,lambda: w.validation_label.text().startswith("พร้อม"))
    from PySide6.QtWidgets import QTableWidgetItem
    w.videos.setItem(1,1,QTableWidgetItem(w.cell(w.videos,0,1)))
    assert w.validate_site()
    pump(app,lambda: "ซ้อน" in w.validation_label.text())
    assert not w.job.active
    dispose(w,app)


@pytest.mark.parametrize("options",[dict(confidence=2),dict(confidence=float("nan")),dict(class_ids=[2,2])])
def test_model_options_do_not_silently_clamp_invalid_files(app,options):
    from tbs.gui.widgets import DetectorOptions
    widget=DetectorOptions()
    with pytest.raises(ValueError):
        widget.set_values(options)
    shiboken6.delete(widget)
