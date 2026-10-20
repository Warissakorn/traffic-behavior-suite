import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import json
import pytest
pytest.importorskip('PySide6')
import shiboken6
from PySide6.QtCore import Qt
from tbs.gui.clip_import import ClipImportDialog
from tbs.gui.main_window import MainWindow
from tbs.gui.resume_dialog import ResumeDialog
from tbs.gui.site_document import SiteDocument
from tbs.config import load_site
from tbs.demo import fixture
from test_gui import app, pump, dispose
from test_resume import clips_fixture, paused_run


def test_import_preview_preserves_real_gap_and_saves_timing_source(app, tmp_path):
    site = clips_fixture(tmp_path/'input', lengths=(2, 2, 2), spacing=600)
    config = load_site(site)
    dialog = ClipImportDialog(config['epoch'])
    dialog.paths = [config['videos'][index]['path'] for index in (2, 0)]
    dialog.inspect()
    pump(app, lambda: dialog.tasks.task is None)
    assert len(dialog.rows) == 2
    assert dialog.selected_rows[1]['gap_s'] > 1199
    assert not dialog.accept_button.isEnabled()
    dialog.acknowledge.setChecked(True)
    assert dialog.accept_button.isEnabled()
    window = MainWindow()
    window.document.open(site)
    window.populate()
    assert window.apply_clip_import(dialog.selected_rows, replace=True)
    result = window.collect()['videos']
    assert result[1]['start_time'].endswith('06:20:00+07:00')
    assert result[0]['time_source'] == 'filename'
    window.document.config = window.collect()
    path = tmp_path/'saved.yaml'
    window.document.save(path)
    assert load_site(path)['videos'][0]['time_source'] == 'filename'
    window.videos.item(1, 1).setText('2026-10-20T06:30:00+07:00')
    assert window.collect()['videos'][1]['time_source'] == 'manual'
    dispose(window, app)
    shiboken6.delete(dialog)


def test_import_changed_options_cannot_accept_old_results(app, tmp_path):
    site = clips_fixture(tmp_path/'input', lengths=(2, 2), spacing=600)
    config = load_site(site)
    dialog = ClipImportDialog(config['epoch'])
    dialog.paths = [clip['path'] for clip in config['videos']]
    dialog.inspect()
    pump(app, lambda: dialog.tasks.task is None)
    dialog.acknowledge.setChecked(True)
    assert dialog.accept_button.isEnabled()
    dialog.reference.setText('2026-10-21T06:00:00+07:00')
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    assert not dialog.accept_button.isEnabled()
    assert dialog.selected_rows == []
    shiboken6.delete(dialog)


def test_closing_import_cancels_background_work_before_disposal(app, tmp_path, monkeypatch):
    import threading
    import time
    entered = threading.Event()
    def inspect(*args, check_cancel, **kwargs):
        entered.set()
        while True:
            check_cancel()
            time.sleep(.001)
    monkeypatch.setattr('tbs.gui.clip_import.inspect_clips', inspect)
    dialog = ClipImportDialog('2026-10-20T06:00:00+07:00')
    dialog.paths = ['fixture.mkv']
    rejected = []
    dialog.rejected.connect(lambda: rejected.append(True))
    dialog.inspect()
    pump(app, entered.is_set)
    dialog.reject()
    dialog.reject()
    pump(app, lambda: bool(rejected) and dialog.tasks.task is None)
    shiboken6.delete(dialog)


def test_unchecking_clip_keeps_gap_without_shifting_other_start_times(app, tmp_path):
    site = clips_fixture(tmp_path/'input', lengths=(2, 2, 2), spacing=600)
    config = load_site(site)
    dialog = ClipImportDialog(config['epoch'])
    dialog.paths = [clip['path'] for clip in config['videos']]
    dialog.inspect()
    pump(app, lambda: dialog.tasks.task is None)
    expected = dialog.rows[2]['start_time']
    dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.selected_rows[1]['start_time'] == expected
    assert dialog.selected_rows[1]['gap_s'] > 1199
    shiboken6.delete(dialog)


def test_resume_dialog_lists_committed_clip_progress(app, tmp_path):
    site = clips_fixture(tmp_path/'input')
    directory = paused_run(site, tmp_path/'output')
    dialog = ResumeDialog(tmp_path/'output')
    pump(app, lambda: dialog.tasks.task is None)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == '1/2'
    dialog.table.setCurrentCell(0, 0)
    dialog.select()
    assert dialog.selected_path == str(directory)
    shiboken6.delete(dialog)


def test_gui_worker_pause_and_resume_preserve_results(app, tmp_path, monkeypatch):
    site = clips_fixture(tmp_path/'input', lengths=(30, 30))
    hooks = tmp_path/'hooks'
    hooks.mkdir()
    (hooks/'sitecustomize.py').write_text(
        'import time\nfrom tbs.detection import SyntheticColorDetector\n'
        'original=SyntheticColorDetector.detect\n'
        'def detect(self,image):\n    time.sleep(.02)\n    return original(self,image)\n'
        'SyntheticColorDetector.detect=detect\n')
    monkeypatch.setenv('PYTHONPATH', str(hooks)+os.pathsep+os.environ.get('PYTHONPATH', ''))
    window = MainWindow()
    window.output_path.setText(str(tmp_path/'output'))
    statuses, requested = [], []
    window.job.finished.connect(lambda status, message: statuses.append(status))
    def progress(event):
        if event.get('stage') == 'checkpoint' and event.get('clips_done') == 1 and not requested:
            requested.append(True)
            window.pause_job()
    window.job.event.connect(progress)
    assert window.prepare_run()
    window.job.start(window.output_path.text(), config=site)
    pump(app, lambda: statuses == ['paused'])
    directory = Path(window.job.output)
    assert json.loads((directory/'manifest.json').read_text(encoding='utf-8'))['clips_done'] == 1
    window.resume_job(path=directory)
    pump(app, lambda: len(statuses) == 2)
    assert statuses == ['paused', 'completed'], window.log.toPlainText()
    pump(app, lambda: window.store is not None)
    assert window.store.manifest['frames'] == 60
    assert window.clip_jobs.item(1, 2).text() == 'บันทึกแล้ว'
    dispose(window, app)
