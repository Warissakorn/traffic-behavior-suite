"""Paged Foundation result access and streamed CSV exports."""
from collections import Counter
import csv
import json
from pathlib import Path
import shutil
import bisect
from copy import copy
import pyarrow.parquet as pq


class ResultStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.manifest = json.loads((self.path/"manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("schema_version") != "1-foundation":
            raise ValueError("Unsupported result schema")
        if self.manifest.get("status") != "completed":
            raise ValueError(f"ผลบางส่วน: {self.manifest.get('status')}")
        self.mode = self.manifest.get("run_mode", "site")
        if self.mode not in {"site", "video_test"}:
            raise ValueError("Unsupported result mode")
        self.datasets = ["detections", "frames"] if self.mode == "video_test" else ["vehicles", "trajectories", "line_crossings", "detections"]
        self.point_filter = None
        self.vehicle_filter = None
        if (self.path/'point_passages.parquet').is_file():
            self.datasets.append('point_passages')
        for name in ["frames", "detections", "trajectories", "vehicles", "line_crossings", "runs"]:
            schema = pq.read_schema(self.path/f"{name}.parquet")
            if not schema.metadata or schema.metadata.get(b"run_id", b"").decode() != self.manifest["run_id"]:
                raise ValueError(f"Result metadata mismatch: {name}")
        self.config = json.loads((self.path/"config.resolved.json").read_text(encoding="utf-8"))
        if 'point_passages' in self.datasets:
            metadata = pq.read_schema(self.path/'point_passages.parquet').metadata or {}
            if metadata.get(b'run_id', b'').decode() != self.manifest['run_id']:
                raise ValueError('Result metadata mismatch: point_passages')
        self.frame_ends = []
        self.time_ends = []
        total = 0
        with pq.ParquetFile(self.path/"frames.parquet") as file:
            for group in range(file.num_row_groups):
                total += file.metadata.row_group(group).num_rows
                self.frame_ends.append(total)
                column = file.schema.names.index("t")
                stats = file.metadata.row_group(group).column(column).statistics
                self.time_ends.append(stats.max if stats and stats.has_min_max else file.read_row_group(group, columns=["t"])["t"][-1].as_py())

    def page(self, name, offset=0, limit=200, columns=None):
        remaining = limit
        result = []
        for rows in self.batches(name):
            if offset >= len(rows):
                offset -= len(rows)
                continue
            selected = rows[offset:offset+remaining]
            result.extend([{k: row[k] for k in columns} if columns else row for row in selected])
            remaining -= len(selected)
            offset = 0
            if not remaining:
                break
        return result

    def with_point(self, point_id):
        result = copy(self)
        result.point_filter = point_id or None
        result.vehicle_filter = None
        if point_id:
            available = {g['id'] for g in self.config.get('image_regions', {}).get('points', [])}
            if point_id not in available or 'point_passages' not in self.datasets:
                raise ValueError('Unknown or unavailable point gate')
            result.vehicle_filter = set()
            with pq.ParquetFile(self.path/'point_passages.parquet') as file:
                for batch in file.iter_batches(columns=['point_id', 'vehicle_id']):
                    result.vehicle_filter.update(r['vehicle_id'] for r in batch.to_pylist() if r['point_id'] == point_id)
        return result

    def includes(self, name, row):
        if self.vehicle_filter is None or name == 'frames':
            return True
        key = 'track_id' if name == 'detections' else 'vehicle_id'
        return (row.get(key) in self.vehicle_filter and
                (name != 'point_passages' or row['point_id'] == self.point_filter))

    def batches(self, name):
        with pq.ParquetFile(self.path/f'{name}.parquet') as file:
            for batch in file.iter_batches(batch_size=1024):
                yield [row for row in batch.to_pylist() if self.includes(name, row)]

    def counts(self):
        if self.mode == "video_test":
            totals = Counter()
            with pq.ParquetFile(self.path/"detections.parquet") as file:
                for batch in file.iter_batches(columns=["class_id"]):
                    totals.update(batch.column(0).to_pylist())
            return [dict(class_id=key, detections=value) for key, value in sorted(totals.items())]
        classes = {}
        with pq.ParquetFile(self.path/"vehicles.parquet") as file:
            for batch in file.iter_batches(columns=["vehicle_id", "class_id"]):
                classes.update({r["vehicle_id"]: r["class_id"] for r in batch.to_pylist()})
        if self.point_filter:
            totals = Counter()
            for rows in self.batches('point_passages'):
                for row in rows:
                    totals[(row['point_id'], row['direction'], classes.get(row['vehicle_id'], -1))] += 1
            return [dict(point_id=k[0], direction=k[1], class_id=k[2], events=v) for k, v in sorted(totals.items())]
        totals = Counter()
        with pq.ParquetFile(self.path/"line_crossings.parquet") as file:
            for batch in file.iter_batches():
                for row in batch.to_pylist():
                    if not self.includes('line_crossings', row):
                        continue
                    totals[(row["line_id"], row["direction"], classes.get(row["vehicle_id"], -1))] += 1
        return [dict(line_id=k[0], direction=k[1], class_id=k[2], events=v) for k, v in sorted(totals.items())]

    def frame(self, index):
        group = bisect.bisect_right(self.frame_ends,index)
        if index < 0 or group >= len(self.frame_ends):
            raise ValueError("Frame index outside run")
        # Independent immutable row-group reads avoid sharing mutable caches
        # between the playback timer and the background preview thread.
        with pq.ParquetFile(self.path/"frames.parquet") as file:
            rows = file.read_row_group(group).to_pylist()
        start = self.frame_ends[group-1] if group else 0
        return rows[index-start]

    def frame_at(self, t):
        """Find a playback frame by decoded time, skipping late display frames."""
        if not self.frame_ends:
            raise ValueError("Run has no frames")
        group = min(bisect.bisect_left(self.time_ends, t), len(self.time_ends)-1)
        with pq.ParquetFile(self.path/"frames.parquet") as file:
            rows = file.read_row_group(group).to_pylist()
            index = bisect.bisect_right([row["t"] for row in rows], t)-1
            if index < 0 and group > 0:
                return file.read_row_group(group-1).to_pylist()[-1]
        return rows[max(0, index)]

    def frame_detections(self, index):
        result = []
        # Row-group statistics skip groups outside the requested frame.
        with pq.ParquetFile(self.path/"detections.parquet") as file:
            column = file.schema.names.index("frame_index")
            for group in range(file.num_row_groups):
                stats = file.metadata.row_group(group).column(column).statistics
                if stats and stats.has_min_max and not stats.min <= index <= stats.max:
                    continue
                for row in file.read_row_group(group).to_pylist():
                    if row["frame_index"] == index and self.includes('detections', row):
                        result.append(row)
        return result

    def export_csv(self, directory):
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        datasets = ["counts", "detections", "frames"] if self.mode == "video_test" else ["counts", "vehicles", "trajectories"]
        if 'point_passages' in self.datasets:
            datasets.append('point_passages')
        targets = [destination/f"{name}.csv" for name in datasets]+[destination/"manifest.json", destination/'selection.json']
        if any(path.exists() for path in targets):
            raise ValueError("ปลายทางมีไฟล์ผลลัพธ์อยู่แล้ว กรุณาเลือกโฟลเดอร์ใหม่")
        prefix = {"site_id": self.manifest["site_id"], "run_id": self.manifest["run_id"], "epoch": self.manifest["epoch"]}
        for name in datasets:
            count_names = ["class_id", "detections"] if self.mode == "video_test" else ["line_id", "direction", "class_id", "events"]
            if self.point_filter:
                count_names = ['point_id', 'direction', 'class_id', 'events']
            names = count_names if name == "counts" else pq.read_schema(self.path/f"{name}.parquet").names
            units = {"t":"t_s", "t_video":"t_video_s", "t_first":"t_first_s", "t_last":"t_last_s", "x":"x_m", "y":"y_m", "v":"v_m_s", "a":"a_m_s2", "heading":"heading_rad", "s":"s_m", "d":"d_m", "space_headway":"space_headway_m", "time_headway":"time_headway_s", "x1":"x1_px", "y1":"y1_px", "x2":"x2_px", "y2":"y2_px"}
            temp = destination/f"{name}.csv.tmp"
            with temp.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([*prefix, *(units.get(key,key) for key in names)])
                def batches_from_file():
                    yield from self.batches(name)
                batches = [self.counts()] if name == "counts" else batches_from_file()
                for rows in batches:
                    for row in rows:
                        writer.writerow([*prefix.values(), *(row.get(key) for key in names)])
            temp.replace(destination/f"{name}.csv")
        shutil.copyfile(self.path/"manifest.json", destination/"manifest.json")
        (destination/'selection.json').write_text(json.dumps(dict(point_id=self.point_filter,
            meaning='All retained rows of vehicles that passed the selected point; null means all vehicles')),
            encoding='utf-8')
