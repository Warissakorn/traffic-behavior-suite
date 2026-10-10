"""Explicit Arrow schemas shared by writers and tests."""
import pyarrow as pa
import pyarrow.parquet as pq

SCHEMAS = {
    "frames": pa.schema([("frame_index", pa.int64()), ("clip_index", pa.int32()), ("t_video", pa.float64()), ("t", pa.float64())]),
    "detections": pa.schema([("frame_index", pa.int64()), ("t", pa.float64()), ("det_id", pa.int64()), ("class_id", pa.int16()), ("score", pa.float32()),
        ("x1", pa.float32()), ("y1", pa.float32()), ("x2", pa.float32()), ("y2", pa.float32()), ("gx", pa.float32()), ("gy", pa.float32()), ("ground_method", pa.int8()), ("track_id", pa.int64())]),
    "trajectories": pa.schema([("vehicle_id", pa.int64()), ("t", pa.float64()), ("x", pa.float32()), ("y", pa.float32()), ("v", pa.float32()), ("a", pa.float32()),
        ("heading", pa.float32()), ("lane_id", pa.int16()), ("s", pa.float32()), ("d", pa.float32()), ("leader_id", pa.int64()), ("space_headway", pa.float32()), ("time_headway", pa.float32()), ("observed", pa.bool_()), ("quality", pa.float32())]),
    "vehicles": pa.schema([("vehicle_id", pa.int64()), ("class_id", pa.int16()), ("class_conf", pa.float32()), ("t_first", pa.float64()), ("t_last", pa.float64()), ("flags", pa.int32()), ("quality", pa.float32())]),
    "line_crossings": pa.schema([("vehicle_id", pa.int64()), ("line_id", pa.string()), ("t", pa.float64()), ("direction", pa.int8()), ("lane_id", pa.int16()), ("v", pa.float32())]),
    "runs": pa.schema([("run_id", pa.string()), ("site_id", pa.string()), ("started_at", pa.timestamp("us", tz="UTC")), ("finished_at", pa.timestamp("us", tz="UTC")),
        ("config_hash", pa.string()), ("model_hashes", pa.string()), ("engine_version", pa.string()), ("clock_offset_s", pa.float64()), ("clock_drift_ppm", pa.float64())])
}


class Writer:
    def __init__(self, path, name, metadata):
        schema = SCHEMAS[name].with_metadata({key.encode(): str(value).encode() for key, value in metadata.items()})
        self.schema = schema
        self.writer = pq.ParquetWriter(path, schema, compression="zstd")

    def write(self, rows):
        if rows:
            self.writer.write_table(pa.Table.from_pylist(rows, schema=self.schema))

    def close(self):
        self.writer.close()
