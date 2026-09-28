# Traffic Behavior Suite

ระบบวิเคราะห์ **พฤติกรรมการขับขี่และการเดินทาง** จากวิดีโอกล้องจราจร
เพื่อสร้างพารามิเตอร์ให้แบบจำลองจราจรระดับ **Micro** (SUMO, VISSIM, Aimsun)
และแบบจำลองขนส่งระดับ **Macro** (VISUM, EMME, Cube)

*Turns traffic-camera video into vehicle trajectories, cross-point journeys and
calibrated parameters for micro- and macro-scale traffic simulation.*

สถาปัตยกรรม **Hybrid**: แกนประมวลผลต่อเฟรมเป็น **C++** (TensorRT, NVDEC) ·
งานวิจัย/เทรน/สถิติ/GUI เป็น **Python**

ต่อยอดจาก [traffic-vehicle-counter](https://github.com/Warissakorn/traffic-vehicle-counter)
และ [Match-Vehicle-AI](https://github.com/Warissakorn/Match-Vehicle-AI)

> สถานะ: **ออกแบบ (Phase 0)** — ยังไม่มีโค้ดใช้งานได้

## เอกสาร
- [`docs/SPEC.md`](docs/SPEC.md) — รายละเอียดโปรแกรม: ความต้องการ, สถาปัตยกรรม, pipeline, API
- [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) — รูปแบบข้อมูล Parquet
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — แผนงานและเกณฑ์จบแต่ละเฟส

## Pipeline โดยย่อ
```
วิดีโอ → Timestamp → Camera calibration → Detection → Ground point → Tracking + stitching
      → Trajectory smoothing → Lane/Frenet → Counters → Sightings + Re-ID embedding
      → Cross-point Re-ID + clock sync → Micro/Macro parameters → SUMO / VISSIM / VISUM
```

## โครงสร้าง
```
engine/     C++ core (libtbs)          bindings/  pybind11
python/tbs  Python package             configs/   YAML + JSON Schema
benchmarks/ ground truth + metrics     docs/      เอกสาร
```

## License
AGPL-3.0 — ดู [LICENSE](LICENSE)
