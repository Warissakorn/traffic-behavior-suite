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
Python environment และ dependencies ทั้งหมดอยู่ใน `.venv` ภายในโปรเจกต์ (ไม่รวมใน Git)
เปิดวิดีโอได้ทันทีในหน้า **ทดสอบวิดีโอ**; ตัวอย่างจำลองอยู่ในแท็บ **ตัวอย่าง / ล่าสุด**
`Test-Windows.cmd` ตรวจ benchmark และ GUI/worker
โมเดลจริงเพิ่ม dependencies ด้วย `Setup-Detection-Windows.cmd` และเลือก local weights

```bash
python -m pip install -e ".[gui]"
tbs gui
```

GUI เปิด/เล่น/พัก/เลื่อนวิดีโอตาม PTS โดยไม่ต้องมี calibration และลอง local detector
ได้ทั้งคลิปผ่าน worker พร้อม progress/cancel, กรอบ class/confidence และ CSV พิกัดภาพ
วาด ROI แล้วเลือก **ตัดภาพตาม ROI ก่อนส่งเข้า YOLO** ได้ โดยกรอบผลตรวจจับและภาพผลลัพธ์ยังอ้างอิงภาพเต็ม
เมื่อต้องการ trajectory/ความเร็ว/เส้นนับ ให้ใช้หน้าตั้งค่า site พร้อม calibration
สร้าง Camera YAML ได้จาก **จุดสำรวจ → กล้อง → สร้าง Camera YAML จากภาพ…** โดยคลิกจุดอ้างอิง
แล้วกรอกพิกัดจริงเป็นเมตร หรือใช้สี่เหลี่ยมที่ทราบกว้าง–ยาว โปรแกรมคำนวณเมทริกซ์และเลือกไฟล์ให้เอง
โหมด **ระยะตามแนวถนน** ใช้ต้น–ปลายช่วงบนขอบถนนสองด้าน พร้อมระยะตามรถวิ่งและความกว้างที่วัดจริง
ล้อเมาส์เลื่อนฟอร์มโดยไม่เปลี่ยนค่าช่องตัวเลข/รายการเลือก ส่วนบนภาพยังซูมได้ตามเดิม
แผงตั้งค่าปรับขนาดและพับได้ ตาราง Parquet แบ่งหน้า และโปรแกรมจำขนาดหน้าต่าง
ดู [`docs/WINDOWS_TEST.md`](docs/WINDOWS_TEST.md) สำหรับ source launchers และ portable CPU/NVIDIA CUDA build

### GPU และไฟล์ Windows สำหรับทดสอบ

รัน `Setup-GPU-Windows.cmd` สำหรับ NVIDIA แล้วเลือก Device `auto` หรือ `0`
ในโปรแกรม รองรับ YOLO CUDA/FP16 และ ONNX Re-ID ผ่าน ONNX Runtime GPU
GitHub Actions **Windows portable test** สร้าง `TBS-Windows-cpu` และ `TBS-Windows-cuda`
ให้ดาวน์โหลดจาก Artifacts ของ run ที่สำเร็จ รุ่น portable รวม runtime สำหรับวิดีโอจริงแล้ว
weights เลือกหรือดาวน์โหลดจากโปรแกรมได้ภายหลัง

### โมเดลตรวจจับ

เลือกและลงทะเบียน local weights หรือดาวน์โหลด/อัปเดตโมเดลทางการจากโปรแกรม
ได้ทั้งหน้าทดสอบวิดีโอและแท็บโมเดลของจุดสำรวจ
มีโปรไฟล์ YOLO11/YOLO26 (n/s/m), ตรวจ task + inference บนเฟรมตัวอย่าง,
ปรับ image size/IoU และบันทึก hash/runtime/class names ใน manifest
เปรียบเทียบความเร็วและทรัพยากรด้วย `tbs compare-models` (ยังไม่ใช่ accuracy benchmark)
ดู [`docs/MODELS.md`](docs/MODELS.md) สำหรับขั้นตอนและข้อจำกัด

## เอกสาร
- วาดกรอบ ROI และเส้นผ่านจุด A/B ในแท็บ **พื้นที่ / จุดผ่าน** แล้วเลือกเฉพาะรถที่ผ่านจุด
  หรือจับคู่สองจุดจาก run เดียวกันในหน้า **จับคู่รถ / OD**
- [`docs/REID_OD.md`](docs/REID_OD.md) — จับคู่รถข้ามจุด/ข้ามเวลา ตรวจยืนยัน และส่งออกต้นทาง–ปลายทาง
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


