"""Identity, ambiguity, review, timestamps and observed OD regression tests."""
import copy
import csv
from datetime import datetime, timezone, timedelta
from fractions import Fraction
import json
from pathlib import Path

import av
import cv2
import numpy as np
import pytest
import yaml

from tbs.demo import fixture
from tbs.events import CancelledError
from tbs.pipeline import run as run_site
from tbs.reid import workflow
from tbs.reid.features import Appearance, normalized
from tbs.reid.solver import match, journeys, review


def sighting(key, point, start, end=None, vector=(1., 0.), observation=None, cls=2):
    return dict(id=key, point_id=point, observation_id=observation or point,
                entry_time=start, exit_time=end if end is not None else start,
                class_id=cls, embedding=normalized(vector).tolist())


def link(a, b, low=1, high=100):
    return {'from': a, 'to': b, 'min_travel_s': low, 'max_travel_s': high}


def test_multi_point_paths_and_od_require_review():
    sightings = [sighting('a1', 'A', 0), sighting('a2', 'A', 0, vector=(0, 1)),
                 sighting('b2', 'B', 10, vector=(0, 1)), sighting('b1', 'B', 12),
                 sighting('c1', 'C', 30)]
    pairs = match(sightings, [link('A', 'B'), link('B', 'C')])
    assert {(p['source'], p['target']) for p in pairs if p['suggested']} == {('a1', 'b1'), ('a2', 'b2'), ('b1', 'c1')}
    assert journeys(sightings, pairs) == []
    result = dict(sightings=sightings, candidates=pairs)
    for pair in pairs:
        review(result, pair['id'], 'accepted')
    paths = {tuple(r['points']) for r in result['journeys']}
    assert paths == {('A', 'B', 'C'), ('A', 'B')}
    full = next(r for r in result['journeys'] if r['destination'] == 'C')
    assert full['sightings'] == ['a1', 'b1', 'c1']
    assert full['travel_s'] == 30


def test_same_point_different_observations_and_times():
    sightings = [sighting('one', 'P', 0, observation='morning'),
                 sighting('two', 'P', 100, observation='later'),
                 sighting('othertrack', 'P', 102, observation='morning')]
    pairs = match(sightings, [link('P', 'P', 90, 110)])
    assert [(p['source'], p['target']) for p in pairs] == [('one', 'two')]


def test_time_class_direction_and_overlapping_tracks_gate_candidates():
    sightings = [sighting('a', 'A', 0, end=5), sighting('tooearly', 'B', 4),
                 sighting('wrongclass', 'B', 10, cls=7), sighting('toolate', 'B', 80),
                 sighting('valid', 'B', 15), sighting('wrongway', 'C', 20)]
    pairs = match(sightings, [link('A', 'B', 5, 20)])
    assert [(p['source'], p['target'], p['travel_s']) for p in pairs] == [('a', 'valid', 10)]


def test_identical_vehicles_are_ambiguous_not_automatically_confirmed():
    sightings = [sighting('a1', 'A', 0), sighting('a2', 'A', 0), sighting('b', 'B', 10)]
    pairs = match(sightings, [link('A', 'B')])
    assert len(pairs) == 2
    assert all(p['ambiguous'] and p['status'] == 'pending' for p in pairs)
    assert sum(p['suggested'] for p in pairs) == 1
    result = dict(sightings=sightings, candidates=pairs)
    review(result, pairs[0]['id'], 'accepted')
    with pytest.raises(ValueError, match='predecessor'):
        review(result, pairs[1]['id'], 'accepted')
    assert pairs[1]['status'] == 'pending'
    review(result, pairs[0]['id'], 'rejected')
    review(result, pairs[1]['id'], 'accepted')
    assert len(result['journeys']) == 1


def test_unmatched_is_allowed_and_sparse_matching_is_one_to_one():
    rows = [sighting('a1', 'A', 0), sighting('a2', 'A', 0, vector=(0, 1)),
            sighting('b1', 'B', 10), sighting('b2', 'B', 10, vector=(-1, 0))]
    pairs = match(rows, [link('A', 'B')])
    assert [(p['source'], p['target']) for p in pairs] == [('a1', 'b1')]
    assert match([], [link('A', 'B')]) == []


def test_colour_baseline_distinguishes_colours_but_records_its_limit():
    appearance = Appearance({})
    green = np.full((30, 20, 3), (0, 255, 0), np.uint8)
    red = np.full((30, 20, 3), (0, 0, 255), np.uint8)
    assert np.dot(appearance.extract(green), appearance.extract(green)) == pytest.approx(1)
    assert np.dot(appearance.extract(green), appearance.extract(red)) < .85
    assert appearance.metadata['method'] == 'hsv_histogram_v1'
    assert 'not a trained' in appearance.metadata['warning']


class ColourDetector:
    def detect(self, image):
        result = []
        for channel in [1, 2]:
            mask = ((image[:, :, channel] > 180) & (image[:, :, (channel+1)%3] < 100)).astype(np.uint8)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w*h > 25:
                    result.append((2, .95, x, y, x+w, y+h))
        return sorted(result, key=lambda r: r[2])


def site_result(root, seconds, monkeypatch, reverse=False):
    site = fixture(root / 'fixture')
    video = site.parent / 'synthetic.mkv'
    with av.open(str(video), mode='w') as container:
        stream = container.add_stream('ffv1', rate=10)
        stream.width, stream.height, stream.pix_fmt = 320, 120, 'bgr0'
        for index in range(12):
            image = np.zeros((120, 320, 3), np.uint8)
            colours = [(0, 255, 0), (0, 0, 255)]
            if reverse:
                colours.reverse()
            for vehicle, colour in enumerate(colours):
                x = 10 + 140*vehicle + index*2
                image[30:60, x:x+25] = colour
            frame = av.VideoFrame.from_ndarray(image, format='bgr24')
            frame.pts, frame.time_base = index, Fraction(1, 10)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    config = yaml.safe_load(site.read_text())
    config['videos'][0]['start_time'] = (datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat()
    config['epoch'] = config['videos'][0]['start_time']
    site.write_text(yaml.safe_dump(config))
    monkeypatch.setattr('tbs.pipeline.make_detector', lambda config: ColourDetector())
    return run_site(site, root / 'runs')[0]


@pytest.fixture
def observed_config(tmp_path, monkeypatch):
    a = site_result(tmp_path / 'A', 0, monkeypatch)
    b = site_result(tmp_path / 'B', 20, monkeypatch, reverse=True)
    return dict(schema_version=1, observations=[dict(id='first', point_id='A', run=str(a)),
                dict(id='second', point_id='B', run=str(b))], links=[link('A', 'B', 10, 30)])


def test_completed_runs_crops_review_persistence_and_csv(observed_config, tmp_path):
    directory, result = workflow.run(observed_config, tmp_path / 'match')
    assert len(result['sightings']) == 4
    assert len(result['candidates']) == 2
    by_id = {s['id']: s for s in result['sightings']}
    assert {(by_id[p['source']]['local_vehicle_id'], by_id[p['target']]['local_vehicle_id'])
            for p in result['candidates']} == {(1, 2), (2, 1)}
    assert all(p['travel_s'] == pytest.approx(18.9) for p in result['candidates'])
    assert all((Path(directory) / s['crop']).is_file() and s['samples'] == 3 for s in result['sightings'])
    pending_export = tmp_path / 'pending'
    workflow.export_csv(result, pending_export)
    assert list(csv.DictReader((pending_export / 'od.csv').open(encoding='utf-8-sig'))) == []
    for pair in result['candidates']:
        result = workflow.save_review(directory, result, pair['id'], 'accepted')
    assert len(workflow.load_result(directory)['journeys']) == 2
    workflow.export_csv(result, tmp_path / 'reviewed')
    rows = list(csv.DictReader((tmp_path / 'reviewed' / 'od.csv').open(encoding='utf-8-sig')))
    assert rows == [dict(origin='A', destination='B', class_id='2', vehicles='2')]
    with pytest.raises(ValueError, match='already contains'):
        workflow.export_csv(result, tmp_path / 'reviewed')


def test_clock_offsets_and_same_camera_relocated(observed_config, tmp_path):
    observed_config['observations'][0]['point_id'] = 'ตำแหน่ง 1'
    observed_config['observations'][1]['point_id'] = 'ตำแหน่ง 2'
    observed_config['links'] = [link('ตำแหน่ง 1', 'ตำแหน่ง 2', 10, 30)]
    observed_config['observations'][1]['clock_offset_s'] = 100
    _, result = workflow.run(observed_config, tmp_path / 'badclock')
    assert result['candidates'] == []
    observed_config['observations'][1]['clock_offset_s'] = 0
    _, corrected = workflow.run(observed_config, tmp_path / 'corrected')
    assert len(corrected['candidates']) == 2


def test_cancel_marks_manifest_and_does_not_publish_results(observed_config, tmp_path):
    messages = []
    with pytest.raises(CancelledError):
        workflow.run(observed_config, tmp_path / 'cancel', on_progress=messages.append,
                     should_cancel=lambda: bool(messages))
    directory = next((tmp_path / 'cancel').iterdir())
    assert json.loads((directory / 'manifest.json').read_text())['status'] == 'cancelled'
    assert not (directory / 'result.json').exists()
    with pytest.raises(ValueError, match='completed'):
        workflow.load_result(directory)


@pytest.mark.parametrize('change', ['duplicate', 'badwindow', 'badpoint', 'nan', 'size'])
def test_invalid_configs(observed_config, change):
    config = copy.deepcopy(observed_config)
    if change == 'duplicate':
        config['observations'][1]['run'] = config['observations'][0]['run']
    elif change == 'badwindow':
        config['links'][0]['min_travel_s'] = 40
    elif change == 'badpoint':
        config['links'][0]['to'] = 'unknown'
    elif change == 'nan':
        config['observations'][0]['clock_offset_s'] = float('nan')
    else:
        config['options'] = dict(input_size=[0, 256])
    with pytest.raises(ValueError):
        workflow.validate_config(config)


def test_cli_run_review_and_export(observed_config, tmp_path):
    import subprocess
    import sys
    config = tmp_path / 'od.json'
    config.write_text(json.dumps(observed_config), encoding='utf-8')
    def cli(*args):
        process = subprocess.run([sys.executable, '-m', 'tbs', 'reid', *args],
                                 capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)
    first = cli('run', str(config), '--output', str(tmp_path / 'cli-output'))
    directory = first['output']
    assert first['candidate_pairs'] == 2 and first['reviewed_journeys'] == 0
    pair = workflow.load_result(directory)['candidates'][0]
    updated = cli('review', directory, '--pair', pair['id'], '--decision', 'accepted')
    assert updated['reviewed_journeys'] == 1
    cli('export', directory, '--output', str(tmp_path / 'cli-csv'))
    rows = list(csv.DictReader((tmp_path / 'cli-csv' / 'od.csv').open(encoding='utf-8-sig')))
    assert rows[0]['vehicles'] == '1'


def test_partial_detection_and_duplicate_source_runs_are_rejected(observed_config, tmp_path):
    first = Path(observed_config['observations'][0]['run'])
    manifest_path = first / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['run_mode'] = 'video_test'
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='completed site'):
        workflow.run(observed_config, tmp_path / 'invalid-mode')
    manifest.pop('run_mode')
    manifest_path.write_text(json.dumps(manifest))
    import shutil
    copied = tmp_path / 'copied'
    shutil.copytree(first, copied)
    observed_config['observations'][1]['run'] = str(copied)
    with pytest.raises(ValueError, match='Duplicate source run'):
        workflow.run(observed_config, tmp_path / 'duplicate')


def test_missing_source_video_has_failed_manifest(observed_config, tmp_path):
    first = Path(observed_config['observations'][0]['run'])
    config = json.loads((first / 'config.resolved.json').read_text())
    Path(config['videos'][0]['path']).unlink()
    with pytest.raises(ValueError, match='วิดีโอ'):
        workflow.run(observed_config, tmp_path / 'missing')
    manifest = json.loads(next((tmp_path / 'missing').glob('*/manifest.json')).read_text())
    assert manifest['status'] == 'failed'


def test_onnx_adapter_rgb_normalization_and_embedding_contract(tmp_path, monkeypatch):
    checkpoint = tmp_path / 'vehicle.onnx'
    checkpoint.write_bytes(b'adapter fixture, network supplied below')
    class Net:
        def setInput(self, value):
            self.input = value
        def forward(self):
            return np.ones((1, 32), np.float32)
    net = Net()
    monkeypatch.setattr(cv2.dnn, 'readNetFromONNX', lambda path: net)
    appearance = Appearance(dict(reid_model=str(checkpoint), input_size=[32, 64]))
    vector = appearance.extract(np.full((10, 20, 3), (0, 0, 255), np.uint8))
    assert vector.shape == (32,) and np.linalg.norm(vector) == pytest.approx(1)
    assert net.input.shape == (1, 3, 64, 32)
    assert net.input[0, :, 0, 0] == pytest.approx([(1-.485)/.229, -.456/.224, -.406/.225])
    assert appearance.metadata['method'] == 'onnx_vehicle_reid'
    monkeypatch.setattr(net, 'forward', lambda: np.ones((1, 3, 16, 16)))
    with pytest.raises(ValueError, match='pooled'):
        appearance.extract(np.ones((10, 10, 3), np.uint8))


def test_saved_result_rejects_invalid_decisions_and_crop_paths(observed_config, tmp_path):
    directory, result = workflow.run(observed_config, tmp_path / 'checked')
    path = Path(directory) / 'result.json'
    invalid = copy.deepcopy(result)
    invalid['candidates'][0]['status'] = 'silently-approved'
    workflow.atomic_json(path, invalid)
    with pytest.raises(ValueError, match='review status'):
        workflow.load_result(directory)
    invalid = copy.deepcopy(result)
    invalid['sightings'][0]['crop'] = '../../outside.jpg'
    workflow.atomic_json(path, invalid)
    with pytest.raises(ValueError, match='outside'):
        workflow.load_result(directory)


def test_failed_review_save_preserves_current_result(observed_config, tmp_path, monkeypatch):
    directory, result = workflow.run(observed_config, tmp_path / 'persistence')
    def disk_error(*args):
        raise OSError('disk full')
    monkeypatch.setattr(workflow, 'atomic_json', disk_error)
    with pytest.raises(OSError, match='disk full'):
        workflow.save_review(directory, result, result['candidates'][0]['id'], 'accepted')
    assert result['candidates'][0]['status'] == 'pending'
    assert workflow.load_result(directory)['journeys'] == []


def test_independent_candidates_can_have_different_ids_minutes_apart_in_same_run():
    a = dict(sighting('a', 'A', 0), run_id='one-video', local_vehicle_id=1)
    b = dict(sighting('b', 'B', 300), run_id='one-video', local_vehicle_id=99)
    alternate = dict(sighting('other', 'B', 310, vector=(.95, .1)), run_id='one-video', local_vehicle_id=100)
    links = [link('A', 'B', 60, 600)]
    pairs = match([a, b, alternate], links)
    assert len(pairs) == 2
    assert all(p['identity_method'] == 'appearance' and p['status'] == 'pending' for p in pairs)
    assert {p['rank'] for p in pairs} == {1, 2}
    assert next(p for p in pairs if p['rank'] == 1)['target'] == 'b'
    assert journeys([a, b, alternate], pairs) == []
    assert match([a, b, alternate], links, identity_mode='shared_track') == []


def test_no_match_is_explicit_persisted_and_does_not_add_od(observed_config, tmp_path):
    directory, result = workflow.run(observed_config, tmp_path / 'review-none')
    source = result['candidates'][0]['source']
    result = workflow.save_no_match(directory, result, source)
    loaded = workflow.load_result(directory)
    assert loaded['source_reviews'][source]['decision'] == 'no_match'
    assert all(p['status'] == 'rejected' for p in loaded['candidates'] if p['source'] == source)
    assert loaded['journeys'] == []
    workflow.export_csv(loaded, tmp_path / 'none-csv')
    sightings = list(csv.DictReader((tmp_path / 'none-csv' / 'sightings.csv').open(encoding='utf-8-sig')))
    assert next(s for s in sightings if s['id'] == source)['successor_review'] == 'no_match'
    pair = next(p for p in result['candidates'] if p['source'] == source)
    accepted = workflow.save_review(directory, result, pair['id'], 'accepted')
    assert source not in accepted['source_reviews']
    with pytest.raises(ValueError, match='ถอนคู่'):
        workflow.save_no_match(directory, accepted, source)


def test_all_representative_frames_are_available_for_human_review(observed_config, tmp_path):
    directory, result = workflow.run(observed_config, tmp_path / 'frames')
    assert result['config']['options']['identity_mode'] == 'independent'
    for sighting_row in result['sightings']:
        assert len(sighting_row['crops']) == 3
        assert len({c['frame_index'] for c in sighting_row['crops']}) == 3
        assert all((Path(directory) / c['path']).is_file() for c in sighting_row['crops'])
        assert sighting_row['crop'] == sighting_row['crops'][0]['path']
    workflow.load_result(directory)


def test_legacy_config_and_single_crop_result_still_load(observed_config, tmp_path):
    directory, result = workflow.run(observed_config, tmp_path / 'legacy')
    manifest_path = Path(directory) / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    result['config']['options'].pop('identity_mode')
    manifest['config']['options'].pop('identity_mode')
    for sighting_row in result['sightings']:
        sighting_row.pop('crops')
    workflow.atomic_json(manifest_path, manifest)
    workflow.atomic_json(Path(directory) / 'result.json', result)
    assert len(workflow.load_result(directory)['sightings']) == 4
