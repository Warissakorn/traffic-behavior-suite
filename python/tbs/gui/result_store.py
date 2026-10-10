"""Paged Foundation result access and streamed CSV exports."""
from collections import Counter
import csv
import json
from pathlib import Path
import shutil
import bisect
import pyarrow.parquet as pq


class ResultStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.manifest = json.loads((self.path/"manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("schema_version") != "1-foundation":
            raise ValueError("Unsupported result schema")
        if self.manifest.get("status") != "completed":
            raise ValueError(f"ผลบางส่วน: {self.manifest.get('status')}")
        for name in ["frames", "detections", "trajectories", "vehicles", "line_crossings", "runs"]:
            schema = pq.read_schema(self.path/f"{name}.parquet")
            if not schema.metadata or schema.metadata.get(b"run_id", b"").decode() != self.manifest["run_id"]:
                raise ValueError(f"Result metadata mismatch: {name}")
        self.config = json.loads((self.path/"config.resolved.json").read_text(encoding="utf-8"))
        self.frame_ends = []
        total = 0
        with pq.ParquetFile(self.path/"frames.parquet") as file:
            for group in range(file.num_row_groups):
                total += file.metadata.row_group(group).num_rows
                self.frame_ends.append(total)

    def page(self, name, offset=0, limit=200, columns=None):
        remaining = limit
        result = []
        with pq.ParquetFile(self.path/f"{name}.parquet") as file:
            for batch in file.iter_batches(batch_size=1024, columns=columns):
                if offset >= batch.num_rows:
                    offset -= batch.num_rows
                    continue
                selected = batch.slice(offset, min(remaining, batch.num_rows-offset))
                result.extend(selected.to_pylist())
                remaining -= selected.num_rows
                offset = 0
                if not remaining:
                    break
        return result

    def counts(self):
        classes = {}
        with pq.ParquetFile(self.path/"vehicles.parquet") as file:
            for batch in file.iter_batches(columns=["vehicle_id", "class_id"]):
                classes.update({r["vehicle_id"]: r["class_id"] for r in batch.to_pylist()})
        totals = Counter()
        with pq.ParquetFile(self.path/"line_crossings.parquet") as file:
            for batch in file.iter_batches():
                for row in batch.to_pylist():
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
                    if row["frame_index"] == index:
                        result.append(row)
        return result

    def export_csv(self, directory):
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        targets = [destination/f"{name}.csv" for name in ["counts", "vehicles", "trajectories"]]+[destination/"manifest.json"]
        if any(path.exists() for path in targets):
            raise ValueError("ปลายทางมีไฟล์ผลลัพธ์อยู่แล้ว กรุณาเลือกโฟลเดอร์ใหม่")
        prefix = {"site_id": self.manifest["site_id"], "run_id": self.manifest["run_id"], "epoch": self.manifest["epoch"]}
        for name in ["counts", "vehicles", "trajectories"]:
            names = ["line_id", "direction", "class_id", "events"] if name == "counts" else pq.read_schema(self.path/f"{name}.parquet").names
            units = {"t":"t_s", "t_first":"t_first_s", "t_last":"t_last_s", "x":"x_m", "y":"y_m", "v":"v_m_s", "a":"a_m_s2", "heading":"heading_rad", "s":"s_m", "d":"d_m", "space_headway":"space_headway_m", "time_headway":"time_headway_s"}
            temp = destination/f"{name}.csv.tmp"
            with temp.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([*prefix, *(units.get(key,key) for key in names)])
                def batches_from_file():
                    with pq.ParquetFile(self.path/f"{name}.parquet") as file:
                        for batch in file.iter_batches():
                            yield batch.to_pylist()
                batches = [self.counts()] if name == "counts" else batches_from_file()
                for rows in batches:
                    for row in rows:
                        writer.writerow([*prefix.values(), *(row.get(key) for key in names)])
            temp.replace(destination/f"{name}.csv")
        shutil.copyfile(self.path/"manifest.json", destination/"manifest.json")
