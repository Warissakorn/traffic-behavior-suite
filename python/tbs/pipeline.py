"""Resumable site analysis with atomic SQLite checkpoints at clip boundaries."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import time
import uuid
import numpy as np
import yaml
from . import __version__
from .config import load_site
from .detection import make_detector
from .storage import Writer
from .tracking import Tracker
from .trajectory import reconstruct, crossings
from .video import frames
from .events import CancelledError, PausedError
from .models import file_hash, describe_detector
from .spatial import Regions, Passages
from .journal import Journal, RunLock, provenance, atomic_json, runtime_state, restore_runtime


def run(config_path, output_dir, on_progress=None, should_cancel=None, *, resume=None, should_pause=None):
    def check_cancel():
        if should_cancel and should_cancel():
            raise CancelledError('Cancelled by user')

    def check_stop():
        check_cancel()
        if should_pause and should_pause():
            raise PausedError('พักงานแล้ว ทำต่อได้จาก checkpoint ล่าสุด')

    def event(kind, **values):
        if on_progress:
            on_progress(dict(type=kind, **values))

    check_cancel()
    event('stage', stage='validate')
    config = load_site(config_path)
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    detector_path = config['models']['detector']
    model_hashes = dict(detector='synthetic-color-v1' if detector_path == 'synthetic_color' else file_hash(detector_path))
    out = Path(resume).resolve() if resume else Path(output_dir).resolve()/str(uuid.uuid4())
    if resume and not (out/'journal.sqlite').is_file():
        raise ValueError('งานนี้ไม่มี checkpoint ที่รองรับการทำต่อ')
    out.mkdir(parents=True, exist_ok=bool(resume))
    lock = RunLock(out/'run.lock')
    journal = None
    iterator = None
    report = checkpoint = None
    try:
        if resume:
            old = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
            if old.get('status') == 'completed':
                raise ValueError('งานนี้สำเร็จแล้ว ไม่ต้องทำต่อ')
            journal = Journal(out/'journal.sqlite')
            checkpoint = journal.get('checkpoint')
            journal.validate(checkpoint, len(config['videos']))
        event('started', run_id=checkpoint['report']['run_id'] if checkpoint else out.name,
              output=str(out), site_id=config['site_id'], resumable=True)
        event('stage', stage='fingerprint')
        signature = provenance(config, check_cancel, lambda **values: event('progress', stage='fingerprint', **values))
        if resume:
            if journal.get('provenance') != signature:
                raise ValueError('วิดีโอ/เวลา/โมเดล/ROI/calibration หรือ engine เปลี่ยนไป ต้องเริ่มงานใหม่')
            report = deepcopy(checkpoint['report'])
        else:
            metadata = dict(schema_version='1-foundation', run_id=out.name, config_hash=config_hash,
                            engine_version=__version__, epoch=config['epoch'], site_id=config['site_id'])
            warnings = ['Baseline association and Savitzky-Golay smoothing; accuracy not validated on traffic data.',
                        'Lane/headway/vehicle dimensions/quality confidence and clock sync are not implemented.']
            if detector_path == 'synthetic_color':
                warnings.append('Synthetic rectangle detector: for tests only.')
            report = dict(**metadata, status='running', model_hashes=model_hashes, warnings=warnings,
                frames=0, detections=0, tracks=0, crossings=0, point_passages=0, clips_done=0,
                clips=[dict(path=clip['path'], start_time=clip['start_time'], status='pending') for clip in config['videos']],
                started_at=datetime.now(timezone.utc).isoformat())
            source = deepcopy(config)
            source['camera'] = dict(model_file=config['camera']['model_file'])
            (out/'source.yaml').write_text(yaml.safe_dump(source, allow_unicode=True, sort_keys=False), encoding='utf-8')
            (out/'config.resolved.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
            journal = Journal(out/'journal.sqlite', create=True)
            journal.put('provenance', signature)
        metadata = {key: report[key] for key in ('schema_version', 'run_id', 'config_hash', 'engine_version', 'epoch', 'site_id')}
        options = config['options']
        tracker = Tracker(options.get('track_max_distance_m', 3), options.get('track_max_gap_s', .5),
                          options.get('track_motion_window', 5))
        regions = Regions(config.get('image_regions'))
        passages = Passages(regions.config['points'], tracker.max_gap)
        if checkpoint:
            restore_runtime(tracker, passages, checkpoint['runtime'])
            regions.shape = tuple(checkpoint['image_shape']) if checkpoint.get('image_shape') else None
        else:
            checkpoint = dict(next_clip=0, report=deepcopy(report), runtime=runtime_state(tracker, passages), image_shape=None)
            journal.put('checkpoint', checkpoint)
            journal.db.commit()
        report.update(status='running', resumable=True)
        report.pop('error', None)
        atomic_json(out/'manifest.json', report)
        event('progress', stage='resume_checkpoint', frames_done=report['frames'], detections=report['detections'],
              elapsed_s=0., clips_done=checkpoint['next_clip'], clips_total=len(config['videos']))
        detector = None
        if checkpoint['next_clip'] < len(config['videos']):
            check_stop()
            event('stage', stage='load_model')
            detector = make_detector(config)
            card = describe_detector(detector, detector_path, options, config['models'].get('detector_sha256'))
            previous = report.get('detector_model', {}).get('device')
            if previous and card.get('device') and previous != card['device']:
                raise ValueError('อุปกรณ์ประมวลผลเปลี่ยนจาก checkpoint ต้องเลือกอุปกรณ์เดิมหรือเริ่มงานใหม่')
            report['detector_model'] = card
            report['model_hashes']['detector'] = card['sha256']
        report['tracking'] = dict(method='ground_motion_history_v1', motion_window=tracker.motion_window,
                                  max_distance_m=tracker.max_distance, max_gap_s=tracker.max_gap)
        h = np.array(config['camera']['image_to_ground'])
        started = last_update = time.monotonic()
        for clip_index in range(checkpoint['next_clip'], len(config['videos'])):
            check_stop()
            clip = config['videos'][clip_index]
            original = next(row for row in signature['files'] if row['path'] == clip['path'])
            stat = Path(clip['path']).stat()
            if (stat.st_size, stat.st_mtime_ns) != (original['size'], original['mtime_ns']):
                raise ValueError('ไฟล์วิดีโอเปลี่ยนหลังตรวจสอบ fingerprint')
            report['clips'][clip_index]['status'] = 'running'
            atomic_json(out/'manifest.json', report)
            event('stage', stage='decode_track', clip_index=clip_index, clips_total=len(config['videos']), clips_done=clip_index)
            journal.db.execute('BEGIN IMMEDIATE')
            buffers = dict(frames=[], detections=[], point_passages=[])
            count_before = report['frames']
            iterator = frames(config, start_clip=clip_index, stop_clip=clip_index+1,
                              start_index=report['frames'], previous=tracker.last_t)
            for index, current, t_video, t, image in iterator:
                check_stop()
                buffers['frames'].append(dict(frame_index=index, clip_index=current, t_video=t_video, t=t))
                detections = regions.detect(detector, image)
                report['inference_region'] = regions.inference
                report['detector_model'].update(getattr(detector, 'metadata', {}))
                projected = []
                for cls, score, x1, y1, x2, y2 in detections:
                    point = h @ np.array([(x1+x2)/2, y2, 1.])
                    if not np.isfinite(point).all() or abs(point[2]) < 1e-12:
                        raise ValueError('Ground projection is invalid; check camera calibration')
                    projected.append(dict(class_id=cls, score=score, x1=x1, y1=y1, x2=x2, y2=y2, xy=point[:2]/point[2]))
                ids = tracker.update(t, projected)
                passed = passages.update(t, projected, ids, index)
                buffers['point_passages'].extend(passed)
                report['point_passages'] += len(passed)
                for det, key in zip(projected, ids):
                    x, y = map(float, det['xy'])
                    buffers['detections'].append(dict(frame_index=index, t=t, det_id=report['detections'],
                        class_id=det['class_id'], score=det['score'], x1=det['x1'], y1=det['y1'], x2=det['x2'], y2=det['y2'],
                        gx=x, gy=y, ground_method=0, track_id=key))
                    report['detections'] += 1
                report['frames'] += 1
                now = time.monotonic()
                if now-last_update >= .2:
                    event('progress', stage='decode_track', frames_done=report['frames'], detections=report['detections'],
                          elapsed_s=now-started, clip_index=clip_index, clips_done=clip_index, clips_total=len(config['videos']))
                    last_update = now
                if report['frames'] % 128 == 0:
                    for name, rows in buffers.items():
                        journal.write(name, rows)
                        rows.clear()
            if report['frames'] == count_before:
                raise ValueError('No video frames decoded')
            stat = Path(clip['path']).stat()
            if (stat.st_size, stat.st_mtime_ns) != (original['size'], original['mtime_ns']):
                raise ValueError('ไฟล์วิดีโอเปลี่ยนระหว่างประมวลผล')
            for name, rows in buffers.items():
                journal.write(name, rows)
            report['clips'][clip_index]['status'] = 'committed'
            report['clips_done'] = clip_index+1
            next_checkpoint = dict(next_clip=clip_index+1, report=deepcopy(report), runtime=runtime_state(tracker, passages),
                                   image_shape=list(regions.shape) if regions.shape else None)
            journal.put('checkpoint', next_checkpoint)
            journal.db.commit()
            checkpoint = next_checkpoint
            atomic_json(out/'manifest.json', report)
            event('progress', stage='checkpoint', frames_done=report['frames'], detections=report['detections'],
                  elapsed_s=time.monotonic()-started, clips_done=clip_index+1, clips_total=len(config['videos']))
        check_stop()
        _publish(journal, out, config, metadata, report, check_stop, event)
        report.update(status='completed', resumable=False, finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(out/'manifest.json', report)
        event('completed', output=str(out), run_id=report['run_id'], report=report)
        return out, report
    except BaseException as exc:
        if journal:
            journal.db.rollback()
        if report is not None:
            if checkpoint:
                report = deepcopy(checkpoint['report'])
            report.update(status='paused' if isinstance(exc, PausedError) else 'cancelled' if isinstance(exc, CancelledError) else 'failed',
                          resumable=bool(checkpoint), error=f'{type(exc).__name__}: {exc}')
            atomic_json(out/'manifest.json', report)
        elif not resume:
            atomic_json(out/'manifest.json', dict(status='failed', error=str(exc), resumable=False))
        raise
    finally:
        if iterator is not None:
            iterator.close()
        if journal:
            journal.close()
        lock.close()


def _publish(journal, out, config, metadata, report, check_stop, event):
    """Restartable publication: raw data is immutable and derived outputs replace files."""
    temporary = out/'.publishing'
    temporary.mkdir(exist_ok=True)
    for name in ('frames', 'detections', 'point_passages'):
        writer = Writer(temporary/f'{name}.parquet', name, metadata)
        try:
            for rows in journal.batches(name):
                check_stop()
                writer.write(rows)
        finally:
            writer.close()
        (temporary/f'{name}.parquet').replace(out/f'{name}.parquet')
    report['tracks'] = report['crossings'] = 0
    event('stage', stage='reconstruct')
    total = journal.db.execute('SELECT COUNT(DISTINCT track_id) FROM detections').fetchone()[0]
    with ExitStack() as stack:
        writers = {}
        for name in ('trajectories', 'vehicles', 'line_crossings', 'runs'):
            writers[name] = Writer(temporary/f'{name}.parquet', name, metadata)
            stack.callback(writers[name].close)
        query = 'SELECT track_id, MIN(class_id), AVG(score), MIN(t), MAX(t), COUNT(*) FROM detections GROUP BY track_id ORDER BY track_id'
        for key, cls, score, first, last, count in journal.db.execute(query):
            check_stop()
            if count > 100000:
                raise ValueError('Track exceeds reference limit of 100000 samples')
            samples = journal.db.execute('SELECT t,gx,gy FROM detections WHERE track_id=? ORDER BY t', (key,)).fetchall()
            for rows in reconstruct(samples, config['options'].get('resample_dt', .1), config['options'].get('max_interpolation_gap_s', .5)):
                for row in rows:
                    row['vehicle_id'] = key
                writers['trajectories'].write(rows)
                events = list(crossings(rows, config['road']['count_lines']))
                writers['line_crossings'].write(events)
                report['crossings'] += len(events)
            writers['vehicles'].write([dict(vehicle_id=key, class_id=cls, class_conf=score, t_first=first, t_last=last,
                                           flags=0, quality=None)])
            report['tracks'] += 1
            event('progress', stage='reconstruct', vehicles_done=report['tracks'], vehicles_total=total)
        check_stop()
        event('stage', stage='finalize')
        writers['runs'].write([dict(run_id=report['run_id'], site_id=config['site_id'],
            started_at=datetime.fromisoformat(report['started_at']), finished_at=datetime.now(timezone.utc),
            config_hash=report['config_hash'], model_hashes=json.dumps(report['model_hashes'], sort_keys=True),
            engine_version=__version__, clock_offset_s=None, clock_drift_ppm=None)])
    check_stop()
    for name in writers:
        (temporary/f'{name}.parquet').replace(out/f'{name}.parquet')
    temporary.rmdir()
