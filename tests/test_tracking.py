"""Identity regressions independent of detector weights or graphics."""
import numpy as np
import pytest

from tbs.tracking import Tracker


def det(x, y=0, cls=2):
    return dict(xy=np.array([x, y], dtype=float), class_id=cls)


def test_motion_history_retains_identity_after_jitter_and_occlusion():
    robust = Tracker(max_distance=.8, max_gap=.5)
    short = Tracker(max_distance=.8, max_gap=.5, motion_window=2)
    # Last observation jitters backwards before a three-frame occlusion.
    for t, x in [(0, 0), (.1, .4), (.2, 1), (.3, 1.05)]:
        assert robust.update(t, [det(x)]) == [1]
        assert short.update(t, [det(x)]) == [1]
    assert robust.update(.4, []) == []
    assert robust.update(.6, [det(2.4)]) == [1]
    assert short.update(.6, [det(2.4)]) == [2]


def test_crossing_vehicles_keep_ids_with_reordered_detections():
    tracker = Tracker(max_distance=1.5, max_gap=.5)
    assert tracker.update(0, [det(-2), det(2)]) == [1, 2]
    assert tracker.update(.1, [det(1), det(-1)]) == [2, 1]
    # Same class, same location at the crossing; velocity separates them afterwards.
    assert tracker.update(.2, [det(0), det(0)]) == [1, 2]
    assert tracker.update(.3, [det(-1), det(1)]) == [2, 1]
    assert tracker.update(.4, [det(2), det(-2)]) == [1, 2]


def test_irregular_timestamps_and_missing_detections_preserve_motion():
    tracker = Tracker(max_distance=1, max_gap=1)
    for t in [0, .1, .25, .4]:
        assert tracker.update(t, [det(2*t, -t)]) == [1]
    assert tracker.update(.6, []) == []
    assert tracker.update(.95, [det(1.9, -.95)]) == [1]
    assert len(tracker.active[1]['history']) == 5
    assert tracker.update(2, [det(4, -2)]) == [2]


def test_motion_history_is_bounded_and_does_not_alias_input():
    tracker = Tracker(motion_window=3)
    original = det(0)
    tracker.update(0, [original])
    original['xy'][:] = 100
    assert tracker.active[1]['xy'] == pytest.approx([0, 0])
    for index in range(1, 20):
        assert tracker.update(index * .1, [det(index * .1)]) == [1]
    assert len(tracker.active[1]['history']) == 3


@pytest.mark.parametrize('time', [0, -.1, float('nan'), float('inf')])
def test_invalid_timestamp_rejected_without_changing_tracks(time):
    tracker = Tracker()
    tracker.update(0, [det(0)])
    with pytest.raises(ValueError, match='timestamps'):
        tracker.update(time, [det(2)])
    assert tracker.last_t == 0
    assert tracker.update(.1, [det(.1)]) == [1]


@pytest.mark.parametrize('point', [[float('nan'), 0], [0, float('inf')], [1, 2, 3]])
def test_invalid_position_rejected_before_mutation(point):
    tracker = Tracker()
    tracker.update(0, [det(0)])
    with pytest.raises(ValueError, match='positions'):
        tracker.update(.1, [dict(xy=point, class_id=2)])
    assert tracker.last_t == 0
    assert tracker.update(.1, [det(.1)]) == [1]


@pytest.mark.parametrize('options', [dict(max_gap=0), dict(max_distance=-1),
                                     dict(max_gap=float('nan')), dict(motion_window=1),
                                     dict(motion_window=31), dict(motion_window=2.5)])
def test_invalid_tracking_options(options):
    with pytest.raises(ValueError):
        Tracker(**options)
