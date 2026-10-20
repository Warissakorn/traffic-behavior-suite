"""Reviewable clip timing: observed timestamps never silently fill missing footage."""
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import re
from .config import timestamp
from .video import probe_video

VIDEO_SUFFIXES = {'.mp4', '.mkv', '.avi', '.mov', '.m4v', '.webm', '.ts'}
STAMP = re.compile(r'(?<!\d)(20\d{2})[-_.]?([01]\d)[-_.]?([0-3]\d)[T _-]?([0-2]\d)[:_.-]?([0-5]\d)[:_.-]?([0-5]\d)(?!\d)')


def natural_key(path):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r'(\d+)', str(path)))


def filename_time(path, reference, pattern=''):
    """Dates in filenames are local camera wall times in the supplied timezone."""
    reference = datetime.fromisoformat(reference.replace('Z', '+00:00'))
    if reference.tzinfo is None:
        raise ValueError('เวลาอ้างอิงต้องมี timezone เช่น +07:00')
    name = Path(path).stem
    if pattern:
        value = datetime.strptime(name, pattern)
    else:
        matches = list(STAMP.finditer(name))
        if len(matches) != 1:
            raise ValueError('ชื่อไฟล์ต้องมีวัน–เวลาชุดเดียว หรือระบุรูปแบบชื่อไฟล์ให้ตรง')
        value = datetime(*map(int, matches[0].groups()))
    return value.replace(tzinfo=reference.tzinfo) if value.tzinfo is None else value


class ProbeCache:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        try:
            self.entries = json.loads(self.path.read_text(encoding='utf-8')) if self.path else {}
            if not isinstance(self.entries, dict):
                self.entries = {}
        except (OSError, ValueError):
            self.entries = {}

    def probe(self, path):
        path = Path(path).resolve()
        stat = path.stat()
        key = f'{path}:{stat.st_size}:{stat.st_mtime_ns}'
        info = self.entries.get(key)
        if not isinstance(info, dict) or not {'width', 'height', 'duration_s', 'last_time_s'} <= info.keys():
            info = probe_video(path)
            self.entries[key] = info
        return dict(info)

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(list(self.entries.items())[-2000:])), encoding='utf-8')
            temporary.replace(self.path)


def timeline(rows, tolerance=.25):
    """Coverage ends at duration when known, otherwise at the last observed PTS."""
    result = []
    previous_end = previous_last = None
    dimensions = None
    for row in rows:
        item = dict(row, gap_s=0., overlap=False)
        if not row.get('error'):
            start = timestamp(row['start_time'])
            info = row['info']
            size = (info['width'], info['height'])
            item['resolution_changed'] = dimensions is not None and dimensions != size
            dimensions = size
            observed = info['duration_s'] if info['duration_s'] is not None else info['last_time_s']
            end = start + observed if observed is not None else None
            last = start + (info['last_time_s'] or 0)
            item.update(end_time=datetime.fromtimestamp(end, datetime.fromisoformat(row['start_time']).tzinfo).isoformat() if end is not None else '',
                        end_known=info['duration_s'] is not None, end_observed=end is not None)
            if previous_end is not None:
                item['gap_s'] = max(0., start-previous_end) if start-previous_end > tolerance else 0.
                item['overlap'] = start <= previous_last + 1e-6
            previous_end = max(previous_end, end) if previous_end is not None and end is not None else end
            previous_last = max(previous_last or last, last)
        result.append(item)
    return result


def inspect_clips(paths, reference, *, mode='filename', pattern='', interval_s=600, cache=None, check_cancel=lambda: None):
    if mode not in {'filename', 'interval'}:
        raise ValueError('Unknown clip timing mode')
    timestamp(reference)
    if not 0 < interval_s <= 86400:
        raise ValueError('ช่วงห่างคลิปต้องมากกว่า 0 และไม่เกิน 24 ชั่วโมง')
    cache = cache or ProbeCache()
    rows, seen, groups = [], set(), {}
    for index, path in enumerate(sorted(map(lambda p: Path(p).resolve(), paths), key=natural_key)):
        check_cancel()
        row = dict(path=str(path), time_source=mode, error='', duplicate_of=None)
        try:
            if str(path) in seen:
                raise ValueError('เลือกไฟล์เดิมซ้ำ')
            seen.add(str(path))
            start = (filename_time(path, reference, pattern) if mode == 'filename' else
                     datetime.fromisoformat(reference.replace('Z', '+00:00')) + timedelta(seconds=index*interval_s))
            row.update(start_time=start.isoformat(), info=cache.probe(path))
            if mode == 'filename':
                row['time_format'] = pattern or 'auto'
            else:
                row['interval_s'] = interval_s
            groups.setdefault(path.stat().st_size, []).append(row)
        except Exception as exc:
            # Includes bounded decoder errors; the remaining files remain reviewable.
            row['error'] = str(exc)
        rows.append(row)
    # Hash only equal-size groups, not every large video during a quick import.
    for group in groups.values():
        if len(group) > 1:
            hashes = {}
            for row in group:
                try:
                    digest = hashlib.sha256()
                    with Path(row['path']).open('rb') as handle:
                        while block := handle.read(4*1024*1024):
                            check_cancel()
                            digest.update(block)
                    value = digest.hexdigest()
                    row['duplicate_of'] = hashes.get(value)
                    hashes.setdefault(value, row['path'])
                except OSError as exc:
                    row['error'] = str(exc)
    rows.sort(key=lambda r: (bool(r.get('error')), timestamp(r['start_time']) if not r.get('error') else 0, natural_key(r['path'])))
    check_cancel()
    cache.save()
    return timeline(rows)
