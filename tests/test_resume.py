from datetime import datetime, timezone, timedelta
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import av
import numpy as np
import pyarrow.parquet as pq
import pytest
import yaml
from tbs.demo import fixture
from tbs.events import PausedError
from tbs.pipeline import run
from tbs.journal import Journal, RunLock, resumable_runs
from tbs.gui.result_store import ResultStore


def clips_fixture(root, lengths=(25, 25), spacing=None):
    site = fixture(root)
    config = yaml.safe_load(site.read_text())
    config['videos'] = []
    config['image_regions'] = dict(points=[dict(id='A', p1=[128, 20], p2=[128, 100])])
    epoch = datetime(2026, 10, 20, 6, tzinfo=timezone(timedelta(hours=7)))
    config['epoch'] = epoch.isoformat()
    index = 0
    for clip_index, length in enumerate(lengths):
        start = epoch+timedelta(seconds=clip_index*spacing if spacing else index/10)
        path = root/start.strftime('กล้อง_%Y%m%d_%H%M%S')
        path = path.with_name(path.name+f'_{clip_index}.mkv')
        with av.open(str(path), mode='w') as container:
            stream = container.add_stream('ffv1', rate=10)
            stream.width, stream.height, stream.pix_fmt = 320, 120, 'bgr0'
            for local in range(length):
                image = np.zeros((120, 320, 3), np.uint8)
                x = 20+4*(index % 50)
                image[50:70, x:x+20] = (0, 255, 0)
                frame = av.VideoFrame.from_ndarray(image, format='bgr24')
                frame.pts, frame.time_base = local, Fraction(1, 10)
                for packet in stream.encode(frame):
                    container.mux(packet)
                index += 1
            for packet in stream.encode():
                container.mux(packet)
        config['videos'].append(dict(path=str(path), start_time=start.isoformat()))
    site.write_text(yaml.safe_dump(config), encoding='utf-8')
    return site


def compare(first, second):
    for name in ('frames', 'detections', 'point_passages', 'vehicles', 'trajectories', 'line_crossings'):
        assert pq.read_table(first/f'{name}.parquet').to_pylist() == pq.read_table(second/f'{name}.parquet').to_pylist(), name


def paused_run(site, output):
    paused = []
    def progress(event):
        if event.get('stage') == 'checkpoint' and event.get('clips_done') == 1:
            paused.append(True)
    with pytest.raises(PausedError):
        run(site, output, on_progress=progress, should_pause=lambda: bool(paused))
    return next(output.iterdir())


def test_pause_resume_matches_uninterrupted_and_preserves_boundary_passage(tmp_path, monkeypatch):
    site = clips_fixture(tmp_path/'input')
    expected, _ = run(site, tmp_path/'baseline')
    directory = paused_run(site, tmp_path/'paused')
    listed = resumable_runs(tmp_path/'paused')
    assert listed[0]['clips_done'] == 1
    decoded = []
    from tbs.video import frames
    def watching(config, **options):
        decoded.append(options['start_clip'])
        yield from frames(config, **options)
    monkeypatch.setattr('tbs.pipeline.frames', watching)
    actual, report = run(directory/'source.yaml', tmp_path/'paused', resume=directory)
    assert decoded == [1]
    assert report['tracks'] == 1 and report['point_passages'] == 1
    assert report['clips_done'] == 2 and report['frames'] == 50
    assert pq.read_table(actual/'point_passages.parquet').to_pylist()[0]['t'] == pytest.approx(2.45)
    compare(expected, actual)
    ResultStore(actual)
    assert resumable_runs(tmp_path/'paused') == []


def test_mid_clip_pause_discards_uncommitted_rows(tmp_path, monkeypatch):
    site = clips_fixture(tmp_path/'input')
    expected, _ = run(site, tmp_path/'baseline')
    from tbs.detection import SyntheticColorDetector
    calls = []
    class Detector(SyntheticColorDetector):
        def detect(self, image):
            calls.append(1)
            return super().detect(image)
    monkeypatch.setattr('tbs.pipeline.make_detector', lambda config: Detector())
    with pytest.raises(PausedError):
        run(site, tmp_path/'paused', should_pause=lambda: len(calls) >= 35)
    directory = next((tmp_path/'paused').iterdir())
    journal = Journal(directory/'journal.sqlite')
    assert journal.get('checkpoint')['report']['frames'] == 25
    assert journal.db.execute('SELECT COUNT(*) FROM frames').fetchone()[0] == 25
    journal.close()
    actual, _ = run(directory/'source.yaml', tmp_path/'paused', resume=directory)
    compare(expected, actual)


def test_resume_finalization_does_not_run_detector_again(tmp_path, monkeypatch):
    site = clips_fixture(tmp_path/'input')
    expected, _ = run(site, tmp_path/'baseline')
    phases = []
    def progress(event):
        if event.get('stage') == 'reconstruct':
            phases.append(True)
    with pytest.raises(PausedError):
        run(site, tmp_path/'paused', on_progress=progress, should_pause=lambda: bool(phases))
    directory = next((tmp_path/'paused').iterdir())
    monkeypatch.setattr('tbs.pipeline.make_detector', lambda config: pytest.fail('committed clips must not run YOLO again'))
    actual, _ = run(directory/'source.yaml', tmp_path/'paused', resume=directory)
    compare(expected, actual)


@pytest.mark.parametrize('change', ['video', 'camera', 'roi', 'time'])
def test_changed_inputs_refuse_resume_without_modifying_committed_data(tmp_path, change):
    site = clips_fixture(tmp_path/'input')
    directory = paused_run(site, tmp_path/'paused')
    if change == 'video':
        config = yaml.safe_load(site.read_text())
        with Path(config['videos'][0]['path']).open('ab') as handle:
            handle.write(b'changed')
    elif change == 'camera':
        (site.parent/'camera.yaml').write_text(yaml.safe_dump(dict(projection='planar_homography', image_to_ground=[[.2,0,0],[0,.1,0],[0,0,1]])))
    else:
        path = directory/'source.yaml'
        config = yaml.safe_load(path.read_text(encoding='utf-8'))
        if change == 'roi':
            config['image_regions']['roi'] = [[0,0],[300,0],[300,120],[0,120]]
        else:
            config['videos'][1]['start_time'] = '2026-10-20T07:00:00+07:00'
        path.write_text(yaml.safe_dump(config), encoding='utf-8')
    manifest_before = (directory/'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='เปลี่ยน'):
        run(directory/'source.yaml', tmp_path/'paused', resume=directory)
    assert (directory/'manifest.json').read_bytes() == manifest_before


def test_process_exit_inside_uncommitted_sqlite_transaction_is_recoverable(tmp_path):
    site = clips_fixture(tmp_path/'input', lengths=(150, 150))
    expected, _ = run(site, tmp_path/'baseline')
    code = '''import os,sys
from tbs.pipeline import run
from tbs.journal import Journal
original=Journal.write
def write(self,name,rows):
    original(self,name,rows)
    if name=='frames' and rows and rows[-1]['frame_index']>=255:
        os._exit(17)
Journal.write=write
run(sys.argv[1],sys.argv[2])
'''
    result = subprocess.run([sys.executable, '-c', code, str(site), str(tmp_path/'crashed')], timeout=30)
    assert result.returncode == 17
    directory = next((tmp_path/'crashed').iterdir())
    actual, report = run(directory/'source.yaml', tmp_path/'crashed', resume=directory)
    assert report['frames'] == 300
    compare(expected, actual)


def test_same_run_lock_prevents_two_writers(tmp_path):
    first = RunLock(tmp_path/'lock')
    try:
        with pytest.raises(ValueError, match='worker'):
            RunLock(tmp_path/'lock')
    finally:
        first.close()


def test_corrupt_checkpoint_counters_are_refused(tmp_path):
    site = clips_fixture(tmp_path/'input')
    directory = paused_run(site, tmp_path/'paused')
    journal = Journal(directory/'journal.sqlite')
    checkpoint = journal.get('checkpoint')
    checkpoint['report']['frames'] = 999
    journal.put('checkpoint', checkpoint)
    journal.db.commit()
    journal.close()
    with pytest.raises(ValueError, match='Checkpoint counters'):
        run(directory/'source.yaml', tmp_path/'paused', resume=directory)


def test_cli_resume_publishes_existing_run(tmp_path, capsys):
    from tbs.cli import main
    site = clips_fixture(tmp_path/'input')
    directory = paused_run(site, tmp_path/'paused')
    assert main(['resume', str(directory)]) == 0
    assert json.loads(capsys.readouterr().out)['frames'] == 50


def test_96_clips_preserve_gaps_and_global_frame_ids(tmp_path):
    site = clips_fixture(tmp_path/'input', lengths=(2,)*96, spacing=600)
    out, report = run(site, tmp_path/'output')
    assert report['clips_done'] == 96 and report['frames'] == 192
    rows = pq.read_table(out/'frames.parquet').to_pylist()
    assert [row['frame_index'] for row in rows] == list(range(192))
    assert rows[-2]['t'] == 57000
    assert len({row['clip_index'] for row in rows}) == 96
