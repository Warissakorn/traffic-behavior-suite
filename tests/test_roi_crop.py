"""ROI inference must keep every downstream coordinate in the full frame."""
import json
import csv
import numpy as np
import pyarrow.parquet as pq
import pytest
import yaml

from tbs.spatial import Regions, validate_regions
from tbs.pipeline import run as run_site
from tbs.video_test import run as run_video
from tbs.gui.result_store import ResultStore
from tbs.video import VideoReader
from test_spatial import point_run
from test_video_test import config_fixture


def region(crop=True):
    return dict(roi=[[20, 10], [90, 10], [90, 70], [20, 70]], crop_before_detect=crop)


@pytest.mark.parametrize('crop', [False, True])
def test_detector_receives_selected_area_but_returns_full_frame_coordinates(crop):
    image = np.arange(100*120*3, dtype=np.uint8).reshape(100, 120, 3)
    original = image.copy()
    class Detector:
        def detect(self, source):
            expected = image[10:70, 20:90] if crop else image
            np.testing.assert_array_equal(source, expected)
            assert source.flags.c_contiguous
            return [(2, .95, 5, 6, 25, 30)] if crop else [(2, .95, 25, 16, 45, 40)]
    regions = Regions(region(crop))
    assert regions.detect(Detector(), image) == [(2, .95, 25, 16, 45, 40)]
    assert regions.inference['detector_input_size'] == ([70, 60] if crop else [120, 100])
    assert regions.inference['coordinate_space'] == 'full_frame'
    np.testing.assert_array_equal(image, original)
    json.dumps(regions.inference)


def test_fractional_roi_rounds_outward_then_filters_in_full_frame():
    regions = Regions(dict(roi=[[20.8, 10.2], [90.1, 10.2], [90.1, 70.8], [20.8, 70.8]], crop_before_detect=True))
    class Detector:
        def detect(self, image):
            assert image.shape == (61, 71, 3)
            return [(2, .9, 0, 0, 1, 2), (2, .8, 1, 1, 21, 31)]
    assert regions.detect(Detector(), np.zeros((100, 120, 3), np.uint8)) == [(2, .8, 21., 11., 41., 41.)]
    assert regions.inference['crop_box_xyxy'] == [20, 10, 91, 71]


def test_roi_on_frame_edge_and_empty_predictions():
    regions = Regions(dict(roi=[[119, 99], [120, 99], [120, 100], [119, 100]], crop_before_detect=True))
    class Detector:
        def detect(self, source):
            assert source.shape == (1, 1, 3)
            return []
    assert regions.detect(Detector(), np.zeros((100, 120, 3), np.uint8)) == []


@pytest.mark.parametrize('value', ['true', 1, None, []])
def test_crop_flag_requires_boolean(value):
    with pytest.raises(ValueError, match='boolean'):
        validate_regions(dict(region(), crop_before_detect=value))


def test_no_roi_and_out_of_frame_do_not_run_detector():
    with pytest.raises(ValueError, match='requires an ROI'):
        Regions(dict(crop_before_detect=True))
    class Detector:
        def detect(self, source):
            pytest.fail('Invalid ROI must fail before inference')
    with pytest.raises(ValueError, match='outside'):
        Regions(region()).detect(Detector(), np.zeros((50, 50, 3), np.uint8))


def test_old_configs_still_infer_on_full_frame():
    regions = Regions(dict(roi=region()['roi']))
    class Detector:
        def detect(self, source):
            assert source.shape == (100, 120, 3)
            return [(2, .9, 25, 15, 45, 40), (2, .8, 100, 80, 110, 90)]
    assert len(regions.detect(Detector(), np.zeros((100, 120, 3), np.uint8))) == 1
    assert regions.inference['mode'] == 'full_frame'


def test_site_crop_preserves_tracking_ground_points_and_passages(point_run, tmp_path):
    _, _, site = point_run
    config = yaml.safe_load(site.read_text())
    config['image_regions']['roi'] = [[10, 10], [120, 10], [120, 110], [10, 110]]
    outputs = []
    for crop in (False, True):
        config['image_regions']['crop_before_detect'] = crop
        site.write_text(yaml.safe_dump(config))
        directory, report = run_site(site, tmp_path/str(crop))
        assert report['tracks'] == 1 and report['point_passages'] == 2
        assert report['inference_region']['detector_input_size'] == ([110, 100] if crop else [320, 120])
        outputs.append(directory)
    for name in ['detections', 'trajectories', 'vehicles', 'point_passages']:
        assert pq.read_table(outputs[0]/f'{name}.parquet').to_pylist() == pq.read_table(outputs[1]/f'{name}.parquet').to_pylist()
    # Re-ID uses the stored full-frame detections and original video path.
    store = ResultStore(outputs[1])
    assert store.config['videos'][0]['path'] == str(site.parent/'synthetic.mkv')


@pytest.fixture
def cropped_video(tmp_path, monkeypatch):
    from tbs.detection import SyntheticColorDetector
    path, config = config_fixture(tmp_path/'input')
    config['image_regions'] = dict(roi=[[30, 20], [180, 20], [180, 100], [30, 100]], crop_before_detect=True)
    path.write_text(json.dumps(config))
    class Detector(SyntheticColorDetector):
        def detect(self, image):
            assert image.shape == (80, 150, 3)
            return super().detect(image)
    monkeypatch.setattr('tbs.video_test.make_detector', lambda config: Detector())
    return run_video(path, tmp_path/'output')[0]


def test_video_crop_results_csv_and_playback_use_original_image(cropped_video, tmp_path):
    store = ResultStore(cropped_video)
    assert store.manifest['inference_region']['mode'] == 'roi_crop'
    rows = store.frame_detections(25)
    assert len(rows) == 1
    box = rows[0]
    assert [box[key] for key in ['x1', 'y1', 'x2', 'y2']] == [120, 50, 140, 70]
    reader = VideoReader()
    try:
        original = reader.read(store.config['videos'][0]['path'], 2.5)['image']
        assert original.shape == (120, 320, 3)
        assert original[55, 130].tolist() == [0, 255, 0]
    finally:
        reader.close()
    store.export_csv(tmp_path/'csv')
    with (tmp_path/'csv/detections.csv').open(encoding='utf-8-sig') as handle:
        row = next(row for row in csv.DictReader(handle) if row['frame_index'] == '25')
    assert float(row['x1_px']) == 120 and float(row['y1_px']) == 50
