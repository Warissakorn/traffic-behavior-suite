# Roadmap

เรียงตามลำดับการพึ่งพา ทุกเฟสจบเมื่อผ่าน **exit criteria** ที่วัดได้

แผนเฉพาะสำหรับวิดีโอ 06:00–22:00 ประมาณ 96 คลิป และการจับคู่รถเข้า–ออกโครงการ:
ดู [แผนงานสำรวจตลอดวัน](LONG_SURVEY_PLAN.md) ซึ่งจัดชุดส่งมอบและเกณฑ์ทดสอบก่อนเริ่มแก้โค้ด

| เฟส | งานหลัก | Exit criteria |
|---|---|---|
| **0 — Foundation** | repo, CI, config + JSON Schema, Parquet schema, นำเข้า ground truth (CVAT), benchmark harness, ชุดข้อมูลอ้างอิง ≥ 2 site | benchmark รันอัตโนมัติใน CI และได้ baseline จากโปรแกรมเดิม |
| **1 — Measurement core (Python reference)** | S0 timestamp แบบ PTS, S1 camera calibration เต็มรูป, S3 ground point (bottom-center), S5 RTS smoother, trajectory writer | position RMSE ≤ 0.5 ม., speed RMSE ≤ 3 กม./ชม. |
| **2 — Tracking & lanes** | fine-tune YOLO ข้อมูลไทย, tracking บนพิกัดพื้น, tracklet stitching, S6 Frenet/lane, S7 counters | IDF1 ≥ 0.85, count GEH < 5 |
| **3 — Cross-point** | vehicle Re-ID model + track embedding, S9 solver (FAISS + ST prior + min-cost flow), S10 clock sync, active learning | Re-ID precision ≥ 95% @ recall ≥ 50%, clock error ≤ 0.5 วินาที |
| **4 — C++ engine** | port S0, S2–S8 เป็น C++ (TensorRT, NVDEC), pybind11, golden tests | ผลตรง reference, ≥ 2× real-time ต่อกล้อง 1080p |
| **5 — Accuracy+** | wheel keypoint / footprint, SAHI tiling, multi-view fusion (ถ้ามี) | position RMSE ≤ 0.3 ม., speed RMSE ≤ 2 กม./ชม. |
| **6 — Parameters & export** | S11 micro/macro, S12 SUMO/VISSIM/VISUM, รายงาน | calibrate แล้ว validate กับข้อมูล hold-out ผ่านเกณฑ์ GEH/ความเร็ว |
| **7 — Product** | GUI PySide6 ครบทุกหน้าจอ, installer Windows/Linux, คู่มือไทย/อังกฤษ | ติดตั้งและรันบนเครื่องใหม่ได้ใน 1 ขั้นตอน |

หมายเหตุ
- เฟส 1–3 ทำเป็น Python reference ก่อนเสมอ; เฟส 4 เริ่มเมื่อ stage นั้นนิ่งแล้ว (อาจเริ่มคู่ขนานกับเฟส 3 สำหรับ S0–S5)
- ทรัพยากรนอกโค้ด: GPU ระดับ RTX 4090, การวัดจุดอ้างอิงภาคสนาม (GNSS-RTK), โดรน/probe vehicle ที่มี GPS, เวลาทำ annotation
