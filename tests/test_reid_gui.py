import time
import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QLineEdit
import shiboken6

from test_reid import observed_config
from tbs.gui.reid_page import ReIDPage
from tbs.reid import workflow


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    return QApplication.instance() or QApplication([])


def wait(app, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate(), 'Background cross-camera job did not finish'


def test_gui_full_matching_review_routes_and_reload(app, observed_config, tmp_path):
    page = ReIDPage(QLineEdit(str(tmp_path / 'gui-output')))
    page.populate(workflow.validate_config(observed_config))
    page.start()
    assert not page.setup.isEnabled()
    wait(app, lambda: not page.busy())
    assert page.result is not None, page.status.text()
    assert page.pairs.rowCount() == 2
    assert not page.left.pixmap().isNull()
    assert page.routes.rowCount() == 0
    for _ in range(2):
        page.decide('accepted')
        wait(app, lambda: not page.busy())
    assert page.routes.rowCount() == 2
    assert all(pair['status'] == 'accepted' for pair in page.result['candidates'])
    assert len(workflow.load_result(page.directory)['journeys']) == 2
    directory = page.directory
    page.open_result(path=directory)
    wait(app, lambda: not page.busy())
    assert page.routes.rowCount() == 2
    assert page.stop()
    shiboken6.delete(page)


def test_gui_reports_invalid_time_window_without_starting_worker(app, observed_config, tmp_path):
    page = ReIDPage(QLineEdit(str(tmp_path / 'output')))
    page.populate(workflow.validate_config(observed_config))
    page.links.item(0, 2).setText('999')
    page.start()
    assert not page.busy()
    assert 'minimum' in page.status.text()
    assert page.result is None
    assert page.stop()
    shiboken6.delete(page)


def test_gui_can_import_distinct_observations_from_same_site(app, observed_config, tmp_path):
    page = ReIDPage(QLineEdit(str(tmp_path / 'output')))
    for observation in observed_config['observations']:
        page.add_observation(path=observation['run'])
    assert page.observations.rowCount() == 2
    assert page.observations.item(0, 0).text() != page.observations.item(1, 0).text()
    assert page.stop()
    shiboken6.delete(page)


def test_candidate_selection_multi_frame_gallery_and_no_match(app, observed_config, tmp_path):
    page = ReIDPage(QLineEdit(str(tmp_path / 'candidate-review')))
    page.populate(workflow.validate_config(observed_config))
    assert page.identity_mode.currentData() == 'independent'
    page.start()
    wait(app, lambda: not page.busy())
    source = page.result['candidates'][0]['source']
    page.source_filter.setCurrentIndex(page.source_filter.findData(source))
    assert page.pairs.rowCount() == 1
    assert page.left_frame.count() == 3 and page.right_frame.count() == 3
    page.left_frame.setCurrentIndex(2)
    assert not page.left.pixmap().isNull()
    page.no_match()
    wait(app, lambda: not page.busy())
    assert page.result['source_reviews'][source]['decision'] == 'no_match'
    assert page.result['journeys'] == []
    assert workflow.load_result(page.directory)['source_reviews'][source]['decision'] == 'no_match'
    assert page.stop()
    shiboken6.delete(page)


def test_source_without_candidate_can_be_viewed_and_reviewed(app, observed_config, tmp_path):
    observed_config['links'][0]['min_travel_s'] = .1
    observed_config['links'][0]['max_travel_s'] = 1
    page = ReIDPage(QLineEdit(str(tmp_path / 'no-candidates')))
    page.populate(workflow.validate_config(observed_config))
    page.start()
    wait(app, lambda: not page.busy())
    assert page.result['candidates'] == []
    page.source_filter.setCurrentIndex(1)
    source = page.source_filter.currentData()
    assert page.left_frame.count() == 3 and not page.left.pixmap().isNull()
    assert page.right_frame.count() == 0
    page.no_match()
    wait(app, lambda: not page.busy())
    assert page.result['source_reviews'][source]['decision'] == 'no_match'
    page.decide('pending')
    wait(app, lambda: not page.busy())
    assert source not in page.result['source_reviews']
    assert page.stop()
    shiboken6.delete(page)


def test_od_setup_gates_actions_and_restores_skipped_review_position(app, observed_config, tmp_path):
    from PySide6.QtCore import QSettings

    settings_path = str(tmp_path / 'settings.ini')
    settings = QSettings(settings_path, QSettings.Format.IniFormat)
    output = str(tmp_path / 'queue')
    page = ReIDPage(QLineEdit(output), settings=settings)
    assert not page.run_button.isEnabled()
    assert not page.delete_observation.isEnabled()
    assert not page.delete_link.isEnabled()
    page.populate(workflow.validate_config(observed_config))
    assert page.run_button.isEnabled()
    page.links.selectRow(0)
    assert page.delete_link.isEnabled()
    page.start()
    wait(app, lambda: not page.busy())
    first = page.current_pair()['id']
    page.skip_button.click()
    second = page.current_pair()['id']
    assert first != second
    assert all(pair['status'] == 'pending' for pair in page.result['candidates'])
    assert 'ช่วงห่าง' in page.pair_info.text()
    directory = page.directory
    assert page.stop()
    shiboken6.delete(page)
    settings.sync()

    reopened = ReIDPage(QLineEdit(output), settings=QSettings(settings_path, QSettings.Format.IniFormat))
    reopened.open_result(path=directory)
    wait(app, lambda: not reopened.busy())
    assert reopened.current_pair()['id'] == second
    reopened.accept_button.click()
    wait(app, lambda: not reopened.busy())
    assert reopened.current_pair()['id'] == first
    assert reopened.stop()
    shiboken6.delete(reopened)
