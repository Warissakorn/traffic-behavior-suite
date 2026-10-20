from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil
import pytest
from tbs.playlist import inspect_clips, filename_time, ProbeCache

INFO = dict(width=320, height=120, duration_s=600., last_time_s=599.9)
REFERENCE = '2026-10-20T06:00:00+07:00'


class Cache:
    def probe(self, path):
        return dict(INFO)
    def save(self):
        pass


def files(tmp_path, names):
    paths = []
    for index, name in enumerate(names):
        path = tmp_path/name
        path.write_bytes(bytes([index])*20)
        paths.append(path)
    return paths


def test_96_timestamped_files_sorted_with_exact_wall_times(tmp_path):
    start = datetime.fromisoformat(REFERENCE)
    names = [(start+timedelta(minutes=10*i)).strftime('กล้อง_%Y%m%d_%H%M%S.mkv') for i in range(96)]
    paths = files(tmp_path, names)
    rows = inspect_clips(paths[::-1], REFERENCE, cache=Cache())
    assert len(rows) == 96 and all(not row['error'] for row in rows)
    assert rows[0]['start_time'] == REFERENCE
    assert rows[-1]['start_time'] == '2026-10-20T21:50:00+07:00'
    assert rows[-1]['end_time'] == '2026-10-20T22:00:00+07:00'
    assert all(not row['gap_s'] and not row['overlap'] for row in rows)


def test_gap_overlap_duplicate_and_resolution_change_are_visible(tmp_path):
    paths = files(tmp_path, ['A_20261020_060000.mkv', 'B_20261020_062000.mkv', 'C_20261020_062500.mkv'])
    shutil.copyfile(paths[0], paths[1])
    rows = inspect_clips(paths, REFERENCE, cache=Cache())
    assert rows[1]['gap_s'] == 600 and rows[1]['duplicate_of'] == str(paths[0])
    assert rows[2]['overlap']
    assert rows[1]['start_time'] == '2026-10-20T06:20:00+07:00'


def test_interval_mode_natural_sort_is_explicitly_an_assumption(tmp_path):
    paths = files(tmp_path, ['clip10.mkv', 'clip2.mkv', 'clip1.mkv'])
    rows = inspect_clips(paths, REFERENCE, mode='interval', cache=Cache())
    assert [Path(row['path']).name for row in rows] == ['clip1.mkv', 'clip2.mkv', 'clip10.mkv']
    assert {row['time_source'] for row in rows} == {'interval'}
    assert rows[1]['interval_s'] == 600
    assert rows[1]['start_time'].endswith('06:10:00+07:00')


def test_unknown_or_multiple_filename_dates_are_not_guessed(tmp_path):
    paths = files(tmp_path, ['no-time.mkv', '20261020_060000_20261020_061000.mkv'])
    rows = inspect_clips(paths, REFERENCE, cache=Cache())
    assert all(row['error'] for row in rows)
    value = filename_time('CAM_20261020_060000.mkv', REFERENCE, 'CAM_%Y%m%d_%H%M%S')
    assert value.isoformat() == REFERENCE


def test_probe_cache_invalidates_changed_files_and_recovers_corrupt_json(tmp_path, monkeypatch):
    path = files(tmp_path, ['test.mkv'])[0]
    calls = []
    monkeypatch.setattr('tbs.playlist.probe_video', lambda value: calls.append(value) or dict(INFO))
    cache_file = tmp_path/'probes.json'
    cache_file.write_text('broken')
    cache = ProbeCache(cache_file)
    cache.probe(path)
    cache.save()
    ProbeCache(cache_file).probe(path)
    assert len(calls) == 1
    path.write_bytes(b'changed file')
    ProbeCache(cache_file).probe(path)
    assert len(calls) == 2


def test_cancellation_interrupts_duplicate_hashing(tmp_path):
    from tbs.events import CancelledError
    paths = files(tmp_path, ['A_20261020_060000.mkv', 'B_20261020_061000.mkv'])
    calls = []
    def cancel():
        calls.append(1)
        if len(calls) > 2:
            raise CancelledError('stop')
    with pytest.raises(CancelledError):
        inspect_clips(paths, REFERENCE, cache=Cache(), check_cancel=cancel)


def test_unknown_clip_end_does_not_invent_a_gap(tmp_path):
    class UnknownCache(Cache):
        def probe(self, path):
            return dict(INFO, duration_s=None, last_time_s=None)
    paths = files(tmp_path, ['A_20261020_060000.mkv', 'B_20261020_061000.mkv'])
    rows = inspect_clips(paths, REFERENCE, cache=UnknownCache())
    assert not rows[0]['end_observed']
    assert rows[0]['end_time'] == ''
    assert rows[1]['gap_s'] == 0
