"""Transactional clip checkpoints; Parquet is published from committed rows."""
from collections import deque
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import sys
import numpy as np
import pyarrow as pa
from . import __version__
from .storage import SCHEMAS

JOURNAL_VERSION = 1
RAW_TABLES = ('frames', 'detections', 'point_passages')


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class RunLock:
    def __init__(self, path):
        self.handle = Path(path).open('a+b')
        if self.handle.tell() == 0:
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise ValueError('งานนี้กำลังถูกใช้งานโดย worker อื่น') from exc

    def close(self):
        if not self.handle.closed:
            if sys.platform == 'win32':
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            self.handle.close()


def provenance(config, check_cancel=lambda: None, progress=lambda **values: None):
    files = []
    paths = [clip['path'] for clip in config['videos']]
    paths.append(config['camera']['model_file'])
    if config['models']['detector'] != 'synthetic_color':
        paths.append(config['models']['detector'])
    for index, value in enumerate(dict.fromkeys(paths)):
        path = Path(value)
        progress(file_index=index+1, file_count=len(set(paths)), filename=path.name)
        before = path.stat()
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            while block := handle.read(4*1024*1024):
                check_cancel()
                digest.update(block)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f'ไฟล์เปลี่ยนขณะตรวจสอบ: {path.name}')
        files.append(dict(path=str(path), size=after.st_size, mtime_ns=after.st_mtime_ns, sha256=digest.hexdigest()))
    packages = {}
    for package in ('numpy', 'scipy', 'av', 'pyarrow', 'opencv-python', 'torch', 'ultralytics'):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    engine = hashlib.sha256()
    root = Path(__file__).parent
    if getattr(sys, 'frozen', False):
        build_info = Path(sys.executable).parent/'build-info.json'
        engine.update(build_info.read_bytes())
    else:
        for name in ('pipeline', 'journal', 'tracking', 'spatial', 'video', 'trajectory', 'detection', 'storage'):
            engine.update((root/f'{name}.py').read_bytes())
    return dict(journal_version=JOURNAL_VERSION, config=config, files=files, engine=__version__,
                engine_digest=engine.hexdigest(), python=list(sys.version_info[:2]), platform=sys.platform, packages=packages)


class Journal:
    def __init__(self, path, create=False):
        path = Path(path)
        self.db = sqlite3.connect(path if create else path.resolve().as_uri()+'?mode=rw', uri=not create)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        if create:
            self.db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            for name in RAW_TABLES:
                columns = ', '.join(f'{field.name} {"INTEGER" if pa.types.is_integer(field.type) else "REAL" if pa.types.is_floating(field.type) else "TEXT"}' for field in SCHEMAS[name])
                primary = {'frames': 'frame_index', 'detections': 'det_id', 'point_passages': 'passage_id'}[name]
                self.db.execute(f'CREATE TABLE {name} ({columns}, PRIMARY KEY ({primary}))')
            self.db.execute('CREATE INDEX vehicle_time ON detections(track_id,t)')
            self.db.commit()

    def get(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        if row is None:
            raise ValueError('ไม่มี checkpoint ที่สมบูรณ์สำหรับทำต่อ')
        return json.loads(row[0])

    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)',
                        (key, json.dumps(value, allow_nan=False, ensure_ascii=False)))

    def write(self, name, rows):
        if rows:
            columns = SCHEMAS[name].names
            marks = ','.join('?' for _ in columns)
            self.db.executemany(f'INSERT INTO {name} VALUES ({marks})',
                               [tuple(row.get(column) for column in columns) for row in rows])

    def batches(self, name):
        if name not in RAW_TABLES:
            raise ValueError('Unknown checkpoint dataset')
        cursor = self.db.execute(f'SELECT * FROM {name} ORDER BY rowid')
        while rows := cursor.fetchmany(1024):
            yield [dict(zip(SCHEMAS[name].names, row)) for row in rows]

    def close(self):
        self.db.close()

    def validate(self, checkpoint, clip_count):
        if type(checkpoint.get('next_clip')) is not int or not 0 <= checkpoint['next_clip'] <= clip_count:
            raise ValueError('Checkpoint clip cursor ไม่ถูกต้อง')
        if self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Checkpoint database เสียหาย')
        report = checkpoint['report']
        for table, counter, column in (('frames', 'frames', 'frame_index'), ('detections', 'detections', 'det_id')):
            count, maximum = self.db.execute(f'SELECT COUNT(*), MAX({column}) FROM {table}').fetchone()
            if count != report[counter] or (maximum is not None and maximum != count-1):
                raise ValueError('Checkpoint counters ไม่ตรงกับข้อมูลที่บันทึก')
        count = self.db.execute('SELECT COUNT(*) FROM point_passages').fetchone()[0]
        if count != report['point_passages'] or checkpoint['runtime']['passage_next_id'] != count+1:
            raise ValueError('Checkpoint passage IDs ไม่ตรงกัน')
        last = self.db.execute('SELECT t FROM frames ORDER BY frame_index DESC LIMIT 1').fetchone()
        if (last[0] if last else None) != checkpoint['runtime']['last_t']:
            raise ValueError('Checkpoint timestamp ไม่ตรงกับเฟรมล่าสุด')


def runtime_state(tracker, passages):
    return dict(next_id=tracker.next_id, last_t=tracker.last_t,
        tracks={str(key): dict(t=value['t'], xy=value['xy'].tolist(), velocity=value['velocity'].tolist(),
                class_id=value['class_id'], history=[[t, xy.tolist()] for t, xy in value['history']])
                for key, value in tracker.active.items()},
        passage_next_id=passages.next_id,
        passages={str(key): dict(last_t=value['last_t'], sides={point: [t, pixel.tolist(), float(side)]
                  for point, (t, pixel, side) in value['sides'].items()}) for key, value in passages.active.items()})


def restore_runtime(tracker, passages, state):
    # The state is data, not executable Python. Reject corrupt/nonfinite records.
    encoded = json.dumps(state, allow_nan=False)
    if len(encoded) > 64*1024*1024 or not isinstance(state, dict):
        raise ValueError('Checkpoint state ไม่ถูกต้อง')
    tracker.next_id, tracker.last_t = int(state['next_id']), state['last_t']
    if tracker.next_id < 1 or (tracker.last_t is not None and not np.isfinite(tracker.last_t)):
        raise ValueError('Checkpoint tracker cursor ไม่ถูกต้อง')
    tracker.active = {}
    for key, value in state['tracks'].items():
        history = deque(((float(t), np.array(xy, float)) for t, xy in value['history']), maxlen=tracker.motion_window)
        xy, velocity = np.array(value['xy'], float), np.array(value['velocity'], float)
        if xy.shape != (2,) or velocity.shape != (2,) or any(p.shape != (2,) for _, p in history):
            raise ValueError('Checkpoint track shape ไม่ถูกต้อง')
        if int(key) <= 0 or int(key) >= tracker.next_id or not history:
            raise ValueError('Checkpoint track ID ไม่ถูกต้อง')
        if (len(value['history']) > tracker.motion_window or not np.isfinite(xy).all() or not np.isfinite(velocity).all()
                or any(not np.isfinite(p).all() or not np.isfinite(t) for t, p in history)):
            raise ValueError('Checkpoint track history ไม่ถูกต้อง')
        tracker.active[int(key)] = dict(t=float(value['t']), xy=xy, velocity=velocity,
                                       class_id=int(value['class_id']), history=history)
    passages.next_id = int(state['passage_next_id'])
    if passages.next_id < 1:
        raise ValueError('Checkpoint passage cursor ไม่ถูกต้อง')
    passages.active = {int(key): dict(last_t=float(value['last_t']), sides={point: (float(t), np.array(pixel, float), float(side))
                       for point, (t, pixel, side) in value['sides'].items()}) for key, value in state['passages'].items()}


def resumable_runs(root):
    rows = []
    for manifest in Path(root).glob('*/manifest.json'):
        try:
            value = json.loads(manifest.read_text(encoding='utf-8'))
            path = manifest.parent
            if value.get('status') != 'completed' and (path/'journal.sqlite').is_file() and (path/'source.yaml').is_file():
                journal = Journal(path/'journal.sqlite')
                try:
                    checkpoint = journal.get('checkpoint')
                finally:
                    journal.close()
                rows.append(dict(path=str(path), site_id=value.get('site_id'), status=value['status'],
                                 clips_done=checkpoint['next_clip'], clips_total=len(checkpoint['report']['clips']),
                                 started_at=value.get('started_at', '')))
        except (OSError, ValueError, KeyError, sqlite3.Error):
            continue
    return sorted(rows, key=lambda row: row['started_at'], reverse=True)
