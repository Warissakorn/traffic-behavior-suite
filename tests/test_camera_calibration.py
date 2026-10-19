import numpy as np
import pytest
import yaml
from tbs.camera_calibration import calibrate_camera, camera_matrix, project_points, rectangle_points, road_points
from tbs.config import load_site
from tbs.demo import fixture
from tbs.video import check_playlist, frames


PIXELS = [[20, 20], [250, 30], [280, 100], [10, 110]]


def test_perspective_mapping_predicts_unseen_ground_points():
    expected = np.array([[.08, .01, -2], [-.02, .12, 1], [.001, -.002, 1]])
    controls = np.array([[20, 20], [250, 30], [280, 100], [10, 110], [140, 80], [90, 45]])
    result = calibrate_camera(controls, project_points(expected, controls), [320, 120])
    unseen = [[60, 70], [150, 50]]
    np.testing.assert_allclose(project_points(camera_matrix(result), unseen), project_points(expected, unseen), atol=1e-10)
    assert result['calibration']['rmse_m'] < 1e-10
    assert result['calibration']['rmse_px'] < 1e-10


def test_four_point_rectangle_and_yaml_are_accepted_by_pipeline(tmp_path):
    site = fixture(tmp_path)
    pixels = [[0, 0], [300, 0], [300, 110], [0, 110]]
    result = calibrate_camera(pixels, rectangle_points(30, 11), [320, 120])
    (tmp_path/'camera.yaml').write_text(yaml.safe_dump(result))
    config = load_site(site)
    np.testing.assert_allclose(project_points(np.array(config['camera']['image_to_ground']), [[130, 50]]), [[13, 5]], atol=1e-10)
    assert result['image_size'] == [320, 120]
    from tbs.pipeline import run
    _, report = run(site, tmp_path/'output')
    assert (report['frames'], report['tracks'], report['crossings']) == (50, 1, 1)


def test_different_video_resolution_fails_preflight_and_frame_processing(tmp_path):
    site = fixture(tmp_path)
    result = calibrate_camera(PIXELS, rectangle_points(10, 20), [640, 480])
    (tmp_path/'camera.yaml').write_text(yaml.safe_dump(result))
    config = load_site(site)
    assert config['camera']['image_size'] == [640, 480]
    with pytest.raises(ValueError, match='Camera YAML'):
        check_playlist(config)
    with pytest.raises(ValueError, match='Camera YAML'):
        next(frames(config))


def test_overdetermined_fit_keeps_all_points_and_reports_measurement_residual():
    pixels = np.array([[u, v] for u in [20, 140, 290] for v in [10, 50, 110]])
    ground = pixels * .1
    ground[4] += [.2, -.1]
    result = calibrate_camera(pixels, ground, [320, 120])
    assert len(result['calibration']['image_points']) == 9
    assert .01 < result['calibration']['rmse_m'] < .2
    assert result['calibration']['max_error_m'] > result['calibration']['rmse_m']


def test_road_reference_recovers_unseen_distances_and_speed_despite_perspective():
    from tbs.trajectory import reconstruct
    ground_to_image = np.array([[18., 4., 100.], [0., -8., 400.], [0., .03, 1.]])
    controls = road_points(6, 30)
    assert controls == [[0, 0], [0, 30], [6, 30], [6, 0]]
    pixels = project_points(ground_to_image, controls)
    camera = calibrate_camera(pixels, controls, [320, 480])
    # Independent points along the vehicle's path, not used to fit the camera.
    actual = np.array([[3., 5.], [3., 15.], [3., 25.]])
    observations = project_points(ground_to_image, actual)
    raw_pixel_distances = np.linalg.norm(np.diff(observations, axis=0), axis=1)
    assert raw_pixel_distances[0] > raw_pixel_distances[1] * 1.2
    measured = project_points(camera_matrix(camera), observations)
    np.testing.assert_allclose(measured, actual, atol=1e-10)
    samples = np.column_stack(([0., 1., 2.], measured))
    trajectory = next(reconstruct(samples, max_gap=1.5))
    np.testing.assert_allclose([row['v'] for row in trajectory], 10, atol=1e-8)


@pytest.mark.parametrize('pixels,ground,size', [
    (PIXELS[:3], rectangle_points(10, 20)[:3], [320, 120]),
    (PIXELS, rectangle_points(10, 20)[:3], [320, 120]),
    ([[10, 10], [20, 20], [30, 30], [40, 40]], rectangle_points(10, 20), [320, 120]),
    (PIXELS, [[1, 1], [2, 2], [3, 3], [4, 4]], [320, 120]),
    ([PIXELS[0], PIXELS[0], *PIXELS[2:]], rectangle_points(10, 20), [320, 120]),
    (PIXELS, [[0, 0], [0, 0], [10, 10], [0, 10]], [320, 120]),
    ([[float('nan'), 20], *PIXELS[1:]], rectangle_points(10, 20), [320, 120]),
    (PIXELS, [[float('inf'), 0], *rectangle_points(10, 20)[1:]], [320, 120]),
    ([[-1, 20], *PIXELS[1:]], rectangle_points(10, 20), [320, 120]),
    (PIXELS, rectangle_points(10, 20), [200, 120]),
    (PIXELS, rectangle_points(10, 20), [320, 0]),
    (PIXELS, rectangle_points(10, 20), [320.5, 120]),
    ([PIXELS[0], PIXELS[2], PIXELS[1], PIXELS[3]], rectangle_points(10, 20), [320, 120]),
    ([[1, 1], [2, 1], [3, 1], [5, 5]], rectangle_points(10, 20), [320, 120]),
])
def test_invalid_correspondences_cannot_produce_camera(pixels, ground, size):
    with pytest.raises(ValueError):
        calibrate_camera(pixels, ground, size)


@pytest.mark.parametrize('width,length', [(0, 10), (-1, 10), (10, float('nan')), (float('inf'), 10)])
def test_rectangle_requires_positive_measured_dimensions(width, length):
    with pytest.raises(ValueError):
        rectangle_points(width, length)
