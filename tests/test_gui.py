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
    for service in [window.preview_tasks,window.result_tasks,window.export_tasks]:
        assert service.stop()
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
    assert events==["completed"]
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
