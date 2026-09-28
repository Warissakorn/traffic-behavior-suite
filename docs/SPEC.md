# Traffic Behavior Suite — รายละเอียดโปรแกรม (Software Specification)

> เวอร์ชันเอกสาร 0.1 (ร่าง) · สถาปัตยกรรม Hybrid C++ / Python
> ต่อยอดจาก `traffic-vehicle-counter` และ `Match-Vehicle-AI`

---

## 1. วัตถุประสงค์

สร้างระบบที่แปลง **วิดีโอกล้องจราจร** เป็น **ข้อมูลพฤติกรรมการขับขี่และการเดินทาง**
ที่แม่นยำพอจะใช้เป็นพารามิเตอร์ของ

- **แบบจำลองจราจรระดับ Micro** — SUMO, PTV VISSIM, Aimsun
- **แบบจำลองขนส่งและจราจรระดับ Macro** — PTV VISUM, EMME, Cube, TransCAD

หลักการออกแบบ: **"วัดให้แม่น" มาก่อน "นับให้เร็ว"** — ทุกขั้นตอนต้องวัดความแม่นยำ
เทียบ ground truth ได้ และผลลัพธ์ต้องทำซ้ำได้ (reproducible)

### 1.1 ขอบเขต (In scope)
- ประมวลผลวิดีโอแบบ offline (batch) หนึ่งหรือหลายจุดสำรวจ
- Trajectory ของรถแต่ละคันในพิกัดจริง (เมตร, วินาที) ระดับช่องจราจร
- นับรถ OD ภายในจุด / นับผ่านเส้น แยกประเภทและทิศทาง
- Re-ID ข้ามจุด → OD ระหว่างจุด + การกระจายเวลาเดินทาง
- ประมาณพารามิเตอร์ Micro / Macro และ export ไปยังโปรแกรมจำลอง
- เครื่องมือ ground truth, benchmark, เทรนโมเดล

### 1.2 นอกขอบเขต (ระยะแรก)
- การอ่านป้ายทะเบียน (ระบบใช้รูปลักษณ์เท่านั้น — ลดประเด็นข้อมูลส่วนบุคคล)
- การควบคุมสัญญาณไฟแบบ real-time
- ระบบ cloud / multi-user server

---

## 2. ความต้องการ (Requirements)

### 2.1 Functional Requirements

| รหัส | ความต้องการ |
|---|---|
| FR-01 | นำเข้าวิดีโอหลายไฟล์ต่อจุด (playlist) พร้อม timestamp ต่อเฟรมจาก PTS |
| FR-02 | คาลิเบรตกล้องเต็มรูปแบบ (intrinsics, distortion, extrinsics) จากจุดอ้างอิงภาคสนาม |
| FR-03 | กำหนดช่องจราจร (centerline + ขอบ), โซน OD, เส้นนับ บนภาพและบน BEV |
| FR-04 | ตรวจจับรถทุกเฟรม แยกประเภท: รถจักรยานยนต์, รถเก๋ง, รถกระบะ, รถตู้, รถสองแถว, รถบัส, รถบรรทุก 6/10 ล้อ, รถพ่วง (ปรับได้) |
| FR-05 | หาจุดสัมผัสพื้น (ground point) และกรอบรถบนพื้น (ground footprint) |
| FR-06 | Tracking ต่อเนื่อง + tracklet stitching แบบ offline |
| FR-07 | Trajectory reconstruction: ตัด outlier + RTS smoother → x, y, v, a, heading |
| FR-08 | แปลงเป็นพิกัด Frenet (s, d) ต่อช่องจราจร, หาคันหน้า/คันตาม, ตรวจการเปลี่ยนช่อง |
| FR-09 | นับ OD ภายในจุด และนับผ่านเส้น (ความสามารถเดิมของ traffic-vehicle-counter) |
| FR-10 | สร้าง "sighting" 1 รายการต่อ track ต่อเส้นอ้างอิง พร้อม embedding ระดับ track |
| FR-11 | Re-ID ข้ามจุด N จุด ด้วย appearance + spatio-temporal + min-cost flow |
| FR-12 | เทียบเวลาระหว่างกล้อง (OCR timeline + cross-correlation + probe vehicle) |
| FR-13 | ประมาณพารามิเตอร์ Micro (ความเร็ว, headway, car-following, lane-change, saturation flow) |
| FR-14 | ประมาณพารามิเตอร์ Macro (ปริมาณ, PCU, PHF, OD, เวลาเดินทาง, BPR) |
| FR-15 | Export ไป SUMO / VISSIM / VISUM / CSV / Parquet |
| FR-16 | เครื่องมือ ground truth + benchmark อัตโนมัติ |
| FR-17 | Human-in-the-loop: ยืนยัน/ปฏิเสธคู่ Re-ID และ track ที่น่าสงสัย → ข้อมูลเทรน |
| FR-18 | GUI ภาษาไทย/อังกฤษ สำหรับตั้งค่า, สั่งรัน, ตรวจผล |

### 2.2 Non-functional Requirements

| รหัส | ความต้องการ |
|---|---|
| NFR-01 | ผลลัพธ์ทำซ้ำได้: ทุก run บันทึก config hash, model hash, engine version |
| NFR-02 | ประมวลผลวิดีโอ 1080p ≥ 2× real-time ต่อกล้องบน RTX 4090 (โหมดละเอียดทุกเฟรม) |
| NFR-03 | ติดตั้งบน Windows 10/11 และ Ubuntu 22.04+ ด้วยตัวติดตั้งเดียว |
| NFR-04 | หน่วยความจำคงที่ระหว่างรันยาว (ไม่มี leak ใน 24 ชม.) |
| NFR-05 | ทุกโมดูลมี unit test; engine C++ ต้องให้ผลตรงกับ reference Python ภายใน tolerance |
| NFR-06 | License AGPL-3.0 (สืบทอดจากโปรแกรมต้นทาง) |

### 2.3 เป้าความแม่นยำ (Acceptance Metrics)

| ตัวชี้วัด | เป้า | วิธีวัด |
|---|---|---|
| การนับ | error ≤ 5% ต่อประเภท, GEH < 5 | เทียบนับมือ |
| จำแนกประเภท | ≥ 95% | confusion matrix |
| Tracking | IDF1 ≥ 0.85, HOTA ≥ 0.70 | TrackEval |
| ตำแหน่ง | RMSE ≤ 0.3 ม. | จุดอ้างอิง / โดรน |
| ความเร็ว | RMSE ≤ 2 กม./ชม. | GPS probe / โดรน |
| Re-ID | precision ≥ 95% ที่ recall ≥ 50% | คู่ที่ label มือ |
| เวลาระหว่างกล้อง | ≤ 0.5 วินาที | probe vehicle |

---

## 3. สถาปัตยกรรม

```
┌──────────────────────────── Python layer (tbs) ─────────────────────────────┐
│  GUI (PySide6)   CLI (tbs ...)   Calibration   Ground truth / Benchmark      │
│  Training (YOLO / Re-ID / keypoint → ONNX)                                   │
│  Cross-point Re-ID solver · Clock sync · Parameter estimation · Exporters    │
└──────────▲─────────────────────────────────────────▲─────────────────────────┘
           │ pybind11 (tbs._engine)                   │ Parquet / Arrow (ไฟล์)
┌──────────┴───────────────── C++ core engine (libtbs) ┴───────────────────────┐
│  Decode (NVDEC/FFmpeg) → Detect (TensorRT) → Ground point → Track            │
│  → Stitch → Smooth (RTS) → Frenet/Lane → Counters → Sighting + Embedding     │
│  → Writers (Parquet)                                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 การแบ่งหน้าที่ระหว่างภาษา

| ชั้น | ภาษา | เหตุผล |
|---|---|---|
| งานต่อเฟรม/ต่อรถ (decode, inference, tracking, smoothing, counting) | **C++** | ปริมาณข้อมูลสูง, multi-thread, GPU zero-copy |
| Re-ID solver ข้ามจุด, สถิติ, calibration พารามิเตอร์ | **Python** | ยังต้องทดลองบ่อย, ใช้ scipy/statsmodels/FAISS-python |
| เทรนโมเดล | **Python** | PyTorch / Ultralytics / FastReID |
| GUI | **Python (PySide6)** | พัฒนาเร็ว, รองรับภาษาไทย, เรียก engine ผ่าน pybind11 |

### 3.2 สัญญาระหว่างชั้น (Contracts)
1. **โมเดล** — ONNX เป็นมาตรฐานกลาง; engine สร้าง TensorRT plan cache เอง
2. **ข้อมูล** — Parquet ตาม schema ใน [`DATA_SCHEMA.md`](DATA_SCHEMA.md), มี `schema_version`
3. **Config** — YAML หนึ่งไฟล์ต่อ site + หนึ่งไฟล์ต่อ project; validate ด้วย JSON Schema ทั้งสองภาษา
4. **API** — engine เปิด API แบบ "job": `Engine.run(job_config) -> RunReport` พร้อม progress callback

### 3.3 Reference implementation
ทุก stage ของ engine มีเวอร์ชัน Python อ้างอิง (`tbs.reference.*`) พัฒนาก่อนเสมอ
→ เมื่อความแม่นยำถึงเป้าจึง port เป็น C++ → test เทียบผลแบบ golden file
(ตำแหน่ง ±1e-3 ม., นับตรงกัน 100%)

---

## 4. โครงสร้าง repo

```
traffic-behavior-suite/
├── engine/                  C++17/20 core (libtbs)
│   ├── include/tbs/         public headers
│   ├── src/                 decode/ detect/ geometry/ track/ smooth/ lane/ count/ reid/ io/
│   └── tests/               GoogleTest + golden files
├── bindings/                pybind11 → tbs._engine
├── python/tbs/
│   ├── reference/           Python reference ของทุก stage
│   ├── calib/               camera calibration, lane/zone editor logic
│   ├── reid/                cross-point solver, clock sync
│   ├── params/              micro/ macro estimation
│   ├── export/              sumo/ vissim/ visum/
│   ├── gt/                  ground truth import (CVAT), metrics
│   ├── train/               YOLO / Re-ID / keypoint training + ONNX export
│   ├── gui/                 PySide6 app
│   └── cli.py
├── configs/                 ตัวอย่าง site/project YAML + JSON Schema
├── benchmarks/              ชุดทดสอบความแม่นยำ + ผล baseline
├── tools/                   installer, packaging, dev scripts
└── docs/
```

---

## 5. รายละเอียด Pipeline แต่ละขั้น

### S0 — Ingest & Timestamp
- **Input:** ไฟล์วิดีโอ / playlist ต่อ site
- **ทำ:** อ่าน PTS ต่อเฟรม (FFmpeg/NVDEC), ตรวจเฟรมซ้ำ/เฟรมหาย, หาเวลาเริ่มจากชื่อไฟล์ / metadata / OCR
- **Output:** `frame_index → t_video (s)`; `t_wall = t_video + clip_offset + clock_offset(site)`
- **ที่มา:** `analysis_session.py` (duplicate-frame check), `timestamp_ocr.py`, `timeline.py`

### S1 — Camera Calibration (Python, ครั้งเดียวต่อ site)
- จุดอ้างอิงภาคสนาม ≥ 8–12 จุด (GNSS-RTK หรือวัดระยะ) + เส้นตรงสำหรับหา distortion
- แก้ปัญหา PnP + bundle adjustment → `K, dist, R, t`; รองรับพื้นหลายระนาบ (piecewise plane)
- รายงาน reprojection error ต่อจุด และแผนที่ความไม่แน่นอนของตำแหน่งทั่วภาพ
- **ที่มา:** `perspective_math.py`, `calib_tools/perspective_tool.py`

### S2 — Detection (C++, TensorRT)
- YOLO (fine-tune ด้วยภาพไทย) + keypoint head (จุดล้อแตะพื้น 2–4 จุด)
- ตัวเลือก tiled inference (SAHI) สำหรับบริเวณไกล กำหนดเป็น ROI ต่อ site
- Batch หลายเฟรม, FP16; ภาพอยู่บน GPU ตลอดตั้งแต่ decode
- **Output ต่อ detection:** bbox, class, score, keypoints, appearance crop pointer

### S3 — Ground Projection (C++)
- ลำดับความสำคัญ: keypoint ล้อ → footprint 3D → จุดกึ่งกลางขอบล่าง + ชดเชยด้วยขนาดมาตรฐานของประเภทรถ
- ฉายผ่าน undistort + ray-plane intersection → `(x_m, y_m)`, heading, length, width
- บันทึก `ground_method` และ covariance ของตำแหน่ง

### S4 — Tracking (C++)
- BoT-SORT/OC-SORT-style: Kalman ในพิกัดพื้น (ไม่ใช่พิกเซล), appearance cost, camera-motion compensation
- **Stitching (offline):** รวม tracklet ด้วย min-cost flow บนกราฟ (ระยะเวลาห่าง, ระยะทาง, ความเร็วที่ต้องการ, appearance)
- **Output:** tracks + quality flags (occluded, stitched, low_conf)

### S5 — Trajectory Reconstruction (C++)
1. ตัด outlier ตามข้อจำกัดฟิสิกส์ (|a| ≤ 8 ม./วินาที², |jerk| จำกัด, ห้ามถอยหลังบนช่องจราจรทางเดียว)
2. RTS smoother (constant-acceleration หรือ kinematic bicycle) ใช้ covariance จาก S3
3. Resample เป็นช่วงเวลาคงที่ (ค่าเริ่มต้น 0.1 วินาที)
4. ตรวจความสอดคล้องภายใน (∫v dt ≈ Δs) → คะแนนคุณภาพต่อ trajectory

### S6 — Lane & Frenet (C++)
- แปลง (x, y) → (lane_id, s, d) ตาม centerline ของแต่ละช่อง
- หาคันหน้า/คันตาม (leader/follower), space headway, time headway, gap
- ตรวจการเปลี่ยนช่อง (hysteresis บน d) และบันทึก event
- รถจักรยานยนต์: เก็บ d แบบต่อเนื่อง (ไม่บังคับให้อยู่ในช่อง) สำหรับ sublane model

### S7 — Counters (C++)
- โซน OD และเส้นนับ (logic เดิมจาก `zone_counter.py`, `line_counter.py`) ทำงานบน trajectory ที่ smooth แล้ว
- เวลาข้ามเส้นแบบ sub-frame interpolation

### S8 — Sighting & Embedding (C++)
- 1 sighting ต่อ track ต่อเส้นอ้างอิง: เวลา, ทิศ, ประเภท, สี, ความยาว
- เลือก K ภาพดีที่สุดตามคุณภาพ (ขนาด, ความคม, ไม่ถูกบัง, มุมมอง) → Re-ID model (TensorRT)
  → embedding ระดับ track (quality-weighted mean + แยกตาม viewpoint)
- บันทึก crop ตัวแทนไว้ให้มนุษย์ตรวจ

### S9 — Cross-point Re-ID (Python)
1. Candidate generation: FAISS + กรองประเภท/สี + ลำดับเวลา
2. Scoring: appearance (k-reciprocal re-ranking) × spatio-temporal prior (การกระจายเวลาเดินทางเรียนรู้แบบ EM)
3. Assignment: min-cost flow ข้าม N จุด (รถ 1 คัน = เส้นทางเดียวที่เป็นไปได้ตามเวลา)
4. Confidence calibration (isotonic) → ความน่าจะเป็นจริง
5. Active learning: ส่งคู่ที่ไม่แน่ใจให้มนุษย์ตรวจ → ชุดเทรน
- **ที่มา:** `matcher.py`, `training_export.py`

### S10 — Clock Sync (Python)
- Offset/drift ต่อกล้องจาก: OCR timeline, cross-correlation ของปริมาณ, คู่ Re-ID ความมั่นใจสูง, probe vehicle
- ประมาณแบบ robust (Theil-Sen / RANSAC) และวนซ้ำกับ S9

### S11 — Parameter Estimation (Python)
**Micro**
- Desired/free-flow speed distribution ต่อประเภท (เฉพาะรถที่ไม่มีคันหน้าใกล้)
- Headway, standstill gap, acceleration/deceleration profiles
- Car-following (IDM, Krauss, Wiedemann 99): calibrate ด้วย spacing error (Punzo et al.), CMA-ES/GA,
  เก็บเป็น **การกระจาย** ของพารามิเตอร์ต่อประเภท + validation แบบ hold-out
- Lane-change: gap acceptance (critical gap distribution), อัตราการเปลี่ยนช่อง
- ทางแยก: saturation flow, start-up lost time, turning ratio

**Macro**
- ปริมาณรายช่วงเวลา, สัดส่วนประเภท, PCU (วิธี headway ratio), PHF
- OD ระหว่างจุด: Re-ID sample + counts → GLS/Bayesian OD estimation
- เวลาเดินทาง: mixture model (คู่จริง + noise) → การกระจายต่อ link/ช่วงเวลา
- BPR fit (α, β) จากเวลาเดินทาง vs. ปริมาณ หลายช่วง/หลายวัน

### S12 — Export (Python)
| ปลายทาง | ไฟล์ |
|---|---|
| SUMO | `vTypeDistribution` (.add.xml), edgeData/routeSampler inputs, detectors |
| VISSIM | driving behavior parameter sets, vehicle compositions, desired speed distributions (CSV/COM script) |
| VISUM | OD matrix ($O format), link counts, travel times, VDF parameters |
| ทั่วไป | Parquet / CSV + รายงาน HTML |

---

## 6. C++ Engine API (ร่าง)

```cpp
namespace tbs {

struct JobConfig {                // โหลดจาก YAML ที่ validate แล้ว
  std::string site_id;
  std::vector<std::string> videos;
  CameraModel camera;             // K, dist, R, t, ground planes
  RoadGeometry road;              // lanes, zones, count lines
  ModelPaths models;              // detector.onnx, reid.onnx
  StageOptions options;           // tiling, smoother, resample_dt, ...
  std::string output_dir;
};

struct RunReport {
  std::string run_id, config_hash, engine_version;
  int64_t frames, detections, tracks, sightings;
  double wall_seconds;
  std::vector<std::string> warnings;
};

class Engine {
 public:
  explicit Engine(const EngineOptions& opt);          // device, precision, threads
  RunReport run(const JobConfig& job,
                std::function<void(const Progress&)> on_progress = {},
                const StopToken& stop = {});
};

// Stage-level API สำหรับ test และ golden comparison
std::vector<GroundDetection> project(const std::vector<Detection>&, const CameraModel&);
Trajectory smooth(const RawTrack&, const SmootherOptions&);
FrenetTrack to_frenet(const Trajectory&, const RoadGeometry&);

}  // namespace tbs
```

Python:
```python
from tbs import _engine
eng = _engine.Engine(device="cuda:0", precision="fp16")
report = eng.run(job, on_progress=cb)
```

### 6.1 Threading
`decode → [ring buffer] → detect (batch, GPU stream) → project+track (CPU thread ต่อกล้อง) → writer`
- 1 ชุด pipeline ต่อกล้อง, แชร์ TensorRT context แบบ multi-stream
- Backpressure ด้วย bounded queue; ยกเลิกได้ทุกขั้นผ่าน `StopToken`

### 6.2 Dependencies
OpenCV 4.x, TensorRT 10 / ONNX Runtime (fallback CPU), FFmpeg + NVIDIA Video Codec SDK,
Eigen 3, Apache Arrow/Parquet, yaml-cpp, nlohmann/json, spdlog, GoogleTest, pybind11
— จัดการด้วย vcpkg; build ด้วย CMake ≥ 3.24

---

## 7. Config

- `configs/project.yaml` — รายชื่อ site, ความสัมพันธ์ระหว่าง site (link, ระยะทาง), ช่วงเวลาศึกษา
- `configs/sites/<site_id>.yaml` — วิดีโอ, camera model, lanes/zones/lines, ROI, stage options
- ทุกไฟล์มี `schema_version` และ validate ด้วย `configs/schema/*.json`
- ดูตัวอย่าง [`../configs/site.example.yaml`](../configs/site.example.yaml)

---

## 8. GUI (PySide6)

| หน้าจอ | หน้าที่ |
|---|---|
| Project | สร้าง/เปิด project, จัดการ site และ link |
| Site setup | เลือกวิดีโอ, คาลิเบรตกล้อง, วาดช่องจราจร/โซน/เส้น (ต่อยอด `calib_tools/`) |
| Run | สั่งรัน engine, progress, resource monitor (ต่อยอด `sysmon.py`) |
| Review | เล่นวิดีโอพร้อม trajectory overlay, ตรวจ track ที่มี flag, ตรวจคู่ Re-ID |
| Parameters | ดูการกระจายพารามิเตอร์, กราฟ, validation, export |
| Benchmark | รัน benchmark เทียบ ground truth และดูประวัติคะแนน |

ใช้ระบบ i18n และ theme แนวเดียวกับ `Match-Vehicle-AI/app/` (ไทย/อังกฤษ, สว่าง/มืด)

---

## 9. การทดสอบและ Benchmark

- **Unit test:** GoogleTest (C++), pytest (Python) — CI ทุก PR
- **Golden test:** เปรียบเทียบ C++ stage กับ Python reference บนข้อมูลสั้น
- **Accuracy benchmark:** `benchmarks/<dataset>/` — วิดีโอ + ground truth (CVAT) + ผล baseline;
  metric: HOTA/IDF1, position/speed RMSE, count GEH, Re-ID P/R
- **Regression gate:** PR ที่ทำให้ metric หลักแย่ลงเกิน tolerance จะไม่ผ่าน
- **Performance benchmark:** FPS ต่อ stage, VRAM, RAM ในรันยาว

---

## 10. การย้ายโค้ดจากโปรแกรมเดิม

| โค้ดเดิม | ปลายทาง | การดำเนินการ |
|---|---|---|
| `traffic-vehicle-counter/zone_counter.py`, `line_counter.py` | `engine/src/count/` + `tbs.reference.count` | port logic + test |
| `perspective_math.py`, `calib_tools/*` | `tbs.calib` | ขยายเป็น full camera model |
| `detector.py`, `tracker_manager.py` | `engine/src/detect`, `engine/src/track` | ออกแบบใหม่ (ground-plane tracking) |
| `tools/prelabel.py`, `labelme2yolo.py`, `train.py`, `dataset_audit.py` | `tbs.train` | ย้ายเกือบตรง |
| `Match-Vehicle-AI/timestamp_ocr.py`, `timeline.py` | `tbs.reid.clock` / S0 | ย้ายเกือบตรง |
| `matcher.py` | `tbs.reid.solver` | ขยายเป็น N-point + min-cost flow |
| `embedder.py` | `train/reid` + `engine/src/reid` | เปลี่ยนเป็นโมเดล vehicle Re-ID |
| `training_export.py` | `tbs.reid.active_learning` | ย้าย |
| `device.py`, `sysmon.py`, `model_manager.py`, `app_paths.py`, `i18n.py`, `theme.py` | `tbs` utilities / GUI | ย้ายและปรับ |

โปรแกรมเดิมทั้งสองยังคงใช้งานได้ระหว่างพัฒนา

---

## 11. ความเสี่ยงและการรับมือ

| ความเสี่ยง | ผลกระทบ | การรับมือ |
|---|---|---|
| มุมกล้องต่ำ/การบดบัง | trajectory ขาด, ID สลับ | แนวทางติดตั้งกล้อง, โดรน, multi-view fusion (เฟสหลัง) |
| ไม่มี ground truth เพียงพอ | พิสูจน์ความแม่นยำไม่ได้ | เฟส 0 ต้องเสร็จก่อน, งบ annotation |
| โมเดลไม่ generalize ข้าม site | ความแม่นยำตกเมื่อเปลี่ยนที่ | fine-tune ต่อ site, active learning |
| ความซับซ้อนสองภาษา | พัฒนาช้า, บั๊กไม่ตรงกัน | reference-first + golden test |
| เวลาระหว่างกล้องคลาดเคลื่อน | เวลาเดินทางผิด | S10 + probe vehicle |
| กลางคืน/ฝน | Re-ID และ detection แย่ลง | แยก metric ตามสภาพ, ติด flag, จำกัดการใช้ข้อมูล |

---

## 12. แผนงาน

ดู [`ROADMAP.md`](ROADMAP.md)
