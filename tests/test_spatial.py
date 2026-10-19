"""ROI filtering, finite point crossings and within-camera OD identity."""
import csv
import json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
import pytest
import yaml

from test_reid import site_result
from tbs.pipeline import run as run_site
from tbs.spatial import Regions, Passages, validate_regions
from tbs.gui.result_store import ResultStore
from tbs.reid import workflow
from tbs.reid.solver import match


def gate(key='A', x=5, direction=0):
    return dict(id=key, p1=[x, 0], p2=[x, 10], direction=direction)


def pixel(x, y=5):
    return dict(x1=x-1, x2=x+1, y1=y-2, y2=y)


def test_roi_uses_bottom_centre_and_includes_boundary():
    regions = Regions(dict(roi=[[10, 10], [20, 10], [20, 20], [10, 20]]))
    detections = [(2, .9, 8, 0, 12, 10), (2, .9, 19, 10, 23, 15), (2, .9, 12, 12, 18, 18)]
    assert regions.filter(detections, np.zeros((30, 30, 3), np.uint8)) == [detections[0], detections[2]]
    with pytest.raises(ValueError, match='outside|resolution'):
        regions.check_image(np.zeros((15, 15, 3), np.uint8))


def test_passages_finite_line_exact_sample_direction_and_repeated_visits():
    passages = Passages([gate()], max_gap=.5)
    assert passages.update(0, [pixel(1)], [1], 0) == []
    assert passages.update(.1, [pixel(5)], [1], 1) == []
    event = passages.update(.2, [pixel(9)], [1], 2)[0]
    assert event['t'] == pytest.approx(.1)
    assert event['direction'] == -1
    assert event['vehicle_id'] == 1
    other = passages.update(.3, [pixel(1)], [1], 3)[0]
    assert other['direction'] == 1 and other['passage_id'] != event['passage_id']
    # Crossing the extended line beyond its endpoints is not a point visit.
    assert Passages([gate()]).update(0, [pixel(1, 20)], [1], 0) == []
    finite = Passages([gate()])
    finite.update(0, [pixel(1, 20)], [1], 0)
    assert finite.update(.1, [pixel(9, 20)], [1], 1) == []
    directed = Passages([gate(direction=1)])
    directed.update(0, [pixel(1)], [1], 0)
    assert directed.update(.1, [pixel(9)], [1], 1) == []
    assert directed.update(.2, [pixel(1)], [1], 2)[0]['direction'] == 1


def test_passages_do_not_bridge_missing_tracks_beyond_max_gap():
    passages = Passages([gate()], max_gap=.5)
    passages.update(0, [pixel(1)], [1], 0)
    assert passages.update(1, [pixel(9)], [1], 1) == []


@pytest.mark.parametrize('regions', [dict(roi=[[0, 0], [10, 0], [10, 0], [0, 0]]),
    dict(roi=[[0, 0], [10, 0], [10, 10]]), dict(points=[gate(), gate()]),
    dict(points=[dict(id='A', p1=[1, 1], p2=[1, 1])]), dict(points=[gate(direction=2)]),
    dict(roi=[[0, 0], [float('nan'), 0], [10, 10], [0, 10]])])
def test_invalid_regions(regions):
    with pytest.raises(ValueError):
        validate_regions(regions)


@pytest.fixture
def point_run(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    site_result(root, 0, monkeypatch)
    site = root / 'fixture' / 'site.yaml'
    config = yaml.safe_load(site.read_text())
    config['image_regions'] = dict(roi=[], points=[
        dict(id='A', p1=[30, 20], p2=[30, 80]),
        dict(id='B', p1=[40, 20], p2=[40, 80]),
        dict(id='C', p1=[100, 20], p2=[100, 80])])
    site.write_text(yaml.safe_dump(config))
    directory, report = run_site(site, root / 'points')
    return directory, report, site


def test_site_point_events_filtering_and_selected_exports(point_run, tmp_path):
    directory, report, _ = point_run
    assert report['tracks'] == 2 and report['point_passages'] == 2
    events = pq.read_table(directory / 'point_passages.parquet').to_pylist()
    assert [event['point_id'] for event in events] == ['A', 'B']
    assert [event['t'] for event in events] == pytest.approx([.375, .875])
    assert {event['vehicle_id'] for event in events} == {1}
    store = ResultStore(directory)
    chosen = store.with_point('A')
    assert len(store.page('vehicles')) == 2  # filter creates an independent view
    assert [row['vehicle_id'] for row in chosen.page('vehicles')] == [1]
    assert {row['track_id'] for row in chosen.frame_detections(0)} == {1}
    assert len(chosen.page('point_passages')) == 1
    assert chosen.page('point_passages')[0]['point_id'] == 'A'
    assert store.with_point('C').page('vehicles') == []
    chosen.export_csv(tmp_path / 'selected')
    rows = list(csv.DictReader((tmp_path / 'selected' / 'vehicles.csv').open(encoding='utf-8-sig')))
    assert [r['vehicle_id'] for r in rows] == ['1']
    assert json.loads((tmp_path / 'selected' / 'selection.json').read_text())['point_id'] == 'A'


def test_pipeline_roi_excludes_outside_vehicle(point_run, tmp_path):
    _, _, site = point_run
    config = yaml.safe_load(site.read_text())
    config['image_regions']['roi'] = [[0, 0], [120, 0], [120, 120], [0, 120]]
    site.write_text(yaml.safe_dump(config))
    directory, report = run_site(site, tmp_path / 'roi')
    assert report['tracks'] == 1 and report['detections'] == 12
    assert report['point_passages'] == 2
    assert all(row['x2'] < 120 for row in pq.read_table(directory / 'detections.parquet').to_pylist())


def within_camera_config(directory):
    return dict(schema_version=1, observations=[
        dict(id='entry', point_id='A', run=str(directory), passage_point='A'),
        dict(id='exit', point_id='B', run=str(directory), passage_point='B')],
        links=[{'from': 'A', 'to': 'B', 'min_travel_s': .1, 'max_travel_s': 2}],
        options=dict(identity_mode='shared_track'))


def test_same_run_point_matching_uses_shared_vehicle_id(point_run, tmp_path):
    directory, _, _ = point_run
    output, result = workflow.run(within_camera_config(directory), tmp_path / 'od')
    assert len(result['sightings']) == 2  # only vehicle 1 passed A/B
    assert {s['local_vehicle_id'] for s in result['sightings']} == {1}
    assert {s['passage_point'] for s in result['sightings']} == {'A', 'B'}
    assert len(result['candidates']) == 1
    pair = result['candidates'][0]
    assert pair['identity_method'] == 'shared_track'
    assert pair['travel_s'] == pytest.approx(.5)
    result = workflow.save_review(output, result, pair['id'], 'accepted')
    assert result['journeys'][0]['points'] == ['A', 'B']
    assert len(workflow.load_result(output)['journeys']) == 1
    # Appearance changes do not override known identity; another track cannot
    # replace the same vehicle even if its colour happens to match exactly.
    a, b = result['sightings']
    a['embedding'] = [1., 0.]
    b['embedding'] = [-1., 0.]
    other = dict(b, id='other', local_vehicle_id=2, embedding=[1., 0.])
    pairs = match([a, b, other], result['config']['links'], identity_mode='shared_track')
    assert len(pairs) == 1 and pairs[0]['identity_method'] == 'shared_track'
    assert pairs[0]['similarity'] == pytest.approx(-1)


def test_same_run_selector_and_clock_validation(point_run):
    directory, _, _ = point_run
    config = within_camera_config(directory)
    config['observations'][1]['passage_point'] = 'A'
    with pytest.raises(ValueError, match='distinct'):
        workflow.validate_config(config)
    config = within_camera_config(directory)
    config['observations'][1]['clock_offset_s'] = 10
    with pytest.raises(ValueError, match='same clock'):
        workflow.validate_config(config)


def test_video_test_roi_filters_detections_without_calibration(tmp_path, monkeypatch):
    from tbs.demo import fixture
    from tbs.detection import SyntheticColorDetector
    from tbs.video_test import run, validate_config
    site = fixture(tmp_path / 'video')
    weights = tmp_path / 'fixture.pt'
    weights.write_bytes(b'detector fixture boundary')
    config = dict(video=str(site.parent / 'synthetic.mkv'), detector=str(weights),
                  image_regions=dict(roi=[[0, 0], [100, 0], [100, 120], [0, 120]]))
    path = tmp_path / 'video.json'
    path.write_text(json.dumps(config))
    monkeypatch.setattr('tbs.video_test.make_detector', lambda config: SyntheticColorDetector())
    directory, report = run(path, tmp_path / 'video-output')
    assert report['frames'] == 50 and report['detections'] == 18
    store = ResultStore(directory)
    assert store.config['image_regions']['roi'][1] == [100, 0]
    config['image_regions']['points'] = [gate()]
    with pytest.raises(ValueError, match='site tracking'):
        validate_config(config)
