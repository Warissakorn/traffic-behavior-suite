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

> สถานะ: **Foundation (Phase 0)** — มี Python reference pipeline และ synthetic benchmark;
> ยังต้องตรวจความแม่นยำกับข้อมูลจราจรจริงและพัฒนา calibration/tracking ตาม SPEC

## เริ่มใช้งาน Python reference

```bash
python -m pip install -e ".[dev]"
tbs demo --output demo-output
tbs validate demo-output/fixture/site.yaml
tbs run demo-output/fixture/site.yaml --output output
```

ดูขอบเขตที่รองรับและข้อจำกัดใน [`docs/FOUNDATION.md`](docs/FOUNDATION.md)

## GUI และ Windows Test

บน Windows: ติดตั้ง Python 3.12 x64 → `Setup-Windows.cmd` → `Launch-TBS.cmd`
เปิดวิดีโอได้ทันทีในหน้า **ทดสอบวิดีโอ**; ตัวอย่างจำลองอยู่ในแท็บ **ตัวอย่าง / ล่าสุด**
`Test-Windows.cmd` ตรวจ benchmark และ GUI/worker
โมเดลจริงเพิ่ม dependencies ด้วย `Setup-Detection-Windows.cmd` และเลือก local weights

```bash
python -m pip install -e ".[gui]"
tbs gui
```

GUI เปิด/เล่น/พัก/เลื่อนวิดีโอตาม PTS โดยไม่ต้องมี calibration และลอง local detector
ได้ทั้งคลิปผ่าน worker พร้อม progress/cancel, กรอบ class/confidence และ CSV พิกัดภาพ
เมื่อต้องการ trajectory/ความเร็ว/เส้นนับ ให้ใช้หน้าตั้งค่า site พร้อม calibration
แผงตั้งค่าปรับขนาดและพับได้ ตาราง Parquet แบ่งหน้า และโปรแกรมจำขนาดหน้าต่าง
ดู [`docs/WINDOWS_TEST.md`](docs/WINDOWS_TEST.md) สำหรับ source launchers และ portable demo build

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

