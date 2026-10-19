# โมเดลตรวจจับและการเปรียบเทียบ

รอบนี้เพิ่มทะเบียน **local detector weights** สำหรับ GUI และ CLI พร้อมโปรไฟล์
YOLO11n/s/m, YOLO26n/s/m และโมเดล custom ที่ Ultralytics อ่านได้
ชื่อโปรไฟล์ใช้จัดรายการ ไม่ได้ยืนยันสถาปัตยกรรมหรือความแม่นยำจากชื่อไฟล์
การตรวจ task และชื่อ class ใช้ผลจาก runtime จริง

## เริ่มใช้บน Windows

1. รัน `Setup-Detection-Windows.cmd` แล้วเปิด `Launch-TBS.cmd`
2. เปิดวิดีโอในหน้า **ทดสอบวิดีโอ**
3. เลือกโปรไฟล์ YOLO11/YOLO26 แล้วกด **ดาวน์โหลด / อัปเดต YOLO** หรือเลือกไฟล์ weights ในเครื่องแล้วกด **เพิ่มในรายการ**
4. ปรับ device, confidence, class IDs, image size และ IoU
5. กด **ตรวจและลองโมเดล** เพื่อลอง inference บนเฟรมปัจจุบัน
6. เมื่อผ่านแล้ว กด **ทดสอบ detection ทั้งคลิป** หรือใช้วิดีโอตั้งค่าจุดสำรวจ

ทะเบียนใช้ร่วมกันระหว่างหน้าทดสอบวิดีโอกับแท็บโมเดลของจุดสำรวจ
เก็บในโฟลเดอร์ข้อมูลของผู้ใช้ (`TrafficBehaviorSuite/models.json`)
เก็บ path อ้างอิงไฟล์เดิม ไม่คัดลอก weights และไม่ดาวน์โหลดโมเดลอัตโนมัติ
หากย้ายหรือเปลี่ยนไฟล์ ต้องเลือกและลงทะเบียนใหม่

## ดาวน์โหลดและอัปเดตจากโปรแกรม

ปุ่ม **ดาวน์โหลด / อัปเดต YOLO** ตรวจ release ล่าสุดของ `ultralytics/assets`
บน GitHub และดาวน์โหลดเฉพาะโปรไฟล์ที่เลือก (YOLO11/YOLO26 ขนาด n/s/m)
แสดงความคืบหน้าและยกเลิกได้ โดยทำงานเบื้องหลังไม่หยุดการเล่นวิดีโอ
ต้องเชื่อมต่อ `api.github.com`, `github.com` และ `release-assets.githubusercontent.com`
หากถูกจำกัดเครือข่าย ให้เพิ่มโดเมนเหล่านี้ใน environment settings

โปรแกรมตรวจขนาดและ SHA-256 จาก release metadata ก่อนบันทึกและลงทะเบียน
หากต้นทางไม่มี checksum จะรายงานข้อผิดพลาดและไม่ใช้ไฟล์นั้น
เก็บ weights ใน `TrafficBehaviorSuite/downloads/<sha256>/` แยกตามเนื้อหา
กดซ้ำจะตรวจรุ่นใหม่และใช้ cache เมื่อ hash ตรงกัน โมเดลรุ่นก่อนและ custom weights
ยังอยู่ครบ อัปเดตหมายถึง pretrained weights ทางการ ไม่ใช่การฝึกเพิ่มหรืออัปเดต Python dependencies
ดาวน์โหลดเสร็จแล้วเลือกไฟล์ให้อัตโนมัติ แต่ยังต้องกด **ตรวจและลองโมเดล**
และติดตั้ง `[detect]` ก่อน inference เช่นเดิม
การเพิ่มไฟล์ในรายการตรวจรูปแบบ/ขนาด/hash เท่านั้น; ต้องลอง inference เพื่อยืนยันว่าใช้งานได้
งาน hashing และลองโมเดลทำเบื้องหลัง; ระหว่างนั้นยังเล่น/เลื่อนวิดีโอได้
กรอบตัวอย่างจะแสดงเฉพาะเมื่อภาพยังตรงกับเฟรมที่ตรวจ และล้างเมื่อเปลี่ยนเฟรม/ตัวเลือก

## รุ่นและขอบเขต

| โปรไฟล์ | ไฟล์ทั่วไป | การใช้งานในแผน |
|---|---|---|
| YOLO11n / YOLO26n | `yolo11n.pt` / `yolo26n.pt` | จุดเริ่มต้นสำหรับเปรียบเทียบความเร็ว |
| YOLO11s / YOLO26s | `yolo11s.pt` / `yolo26s.pt` | ตัวเลือกขนาด small สำหรับ benchmark |
| YOLO11m / YOLO26m | `yolo11m.pt` / `yolo26m.pt` | ตัวเลือก medium เมื่อต้องการเปรียบเทียบเพิ่ม |
| Custom | เช่น `traffic-thai.pt` | weights ที่ fine-tune ด้วย taxonomy ของทีม |

รองรับ adapter ผ่าน `ultralytics==8.4.63` เพื่อให้รุ่น dependency ทำซ้ำได้
เริ่มใช้ `.pt` ก่อน; `.onnx`, `.engine`, `.torchscript` ยังรับเป็น local file
ตาม adapter เดิม แต่ต้องผ่านการตรวจ runtime บนเครื่องและ device ที่จะใช้
ยังไม่ถือว่า format เหล่านี้ผ่าน parity หรือ performance validation

COCO vehicle IDs: car=2, motorcycle=3, bus=5, truck=7
เลือก `2,3,5,7` เฉพาะเมื่อโมเดลนั้นใช้ COCO taxonomy
โมเดลทั่วไปไม่ได้แยกกระบะ รถตู้ สองแถว และประเภทรถบรรทุกไทยครบตาม SPEC
ต้องเตรียม labelled data และ fine-tune; ไม่เปลี่ยนชื่อ class เพื่ออ้างความสามารถเพิ่ม
โมเดล pose/classify/segment ถูกปฏิเสธใน detector pipeline รอบนี้
synthetic detector ยังคงใช้เฉพาะ demo/regression ไม่อยู่ในรายการโมเดลจราจร

## CLI

```bash
tbs models catalog
tbs models register ./models/yolo11s.pt --preset yolo11s --name "YOLO11s baseline"
tbs models list
tbs models check ./models/yolo11s.pt --video traffic.mp4 --time 2.5 --device cpu --image-size 640 --class-ids 2 3 5 7
```

ระบุทะเบียนเฉพาะเครื่อง/การทดลองได้ด้วย
`tbs models --registry ./local-models.json register ./models/traffic.pt`
เมื่อไม่ระบุ `--video` คำสั่ง check ใช้ภาพว่างเป็น inference smoke test
ไม่ใช่การทดสอบความแม่นยำ

Site YAML เดิมที่ใช้ `models.detector` เป็น path ยังใช้ได้
เพิ่มตัวเลือกได้ดังนี้ (ต้องใส่ hash ของไฟล์จริงเมื่อใช้ `detector_sha256`):

```yaml
models:
  detector: ./models/traffic.pt
options:
  device: cpu
  confidence: 0.25
  iou: 0.7
  image_size: 640
  class_ids: [2, 3, 5, 7]
```

`image_size` ต้องเป็นจำนวนเต็มที่หาร 32 ลงตัว ระหว่าง 32–4096
`models.detector_sha256` เป็น optional lowercase SHA-256 สำหรับล็อก weights
GUI เพิ่ม hash เมื่อเลือกโมเดลที่ลงทะเบียนหรือตรวจ inference สำเร็จ
worker ปฏิเสธไฟล์ที่ hash เปลี่ยน; ผลที่ล้มเหลวไม่ถูกแสดงเป็นผลสำเร็จ
manifest ของทั้ง site/video-test เพิ่ม `detector_model`: filename, format,
SHA-256, task, runtime version, class names และ options; Parquet schema เดิมยังเหมือนเดิม

## เปรียบเทียบโมเดล

```bash
tbs compare-models traffic.mp4 --model ./models/yolo11s.pt --model ./models/yolo26s.pt --output benchmark-output --device cpu --image-size 640 --class-ids 2 3 5 7 --max-frames 300 --warmup 2
```

แต่ละโมเดลรันใน subprocess ใหม่ ใช้วิดีโอ/options/จำนวนเฟรมเดียวกัน
`--max-frames 0` (ค่าเริ่มต้น) ใช้ทั้งคลิป; ค่าอื่นใช้ N เฟรมแรก
ผลอยู่ใน `comparison-<uuid>/comparison.json` และ `comparison.csv`
หากโมเดลใดล้มเหลว เก็บ error แล้วทดสอบโมเดลถัดไป; command คืน exit code 2
เมื่อมีโมเดลล้มเหลว และ 0 เมื่อทั้งหมดสำเร็จ

| ตัวชี้วัด | ความหมาย |
|---|---|
| `decode_inference_fps` | decode + inference; ไม่รวม load, warmup และเขียนรายงาน |
| `inference_ms_per_frame` | เวลา adapter inference เฉลี่ย รวม preprocessing/postprocessing และถ่ายผลสู่ CPU |
| `model_load_s` | เวลาสร้าง detector; backend บางแบบโหลดเพิ่มใน warmup |
| `peak_rss_bytes` | RAM ของ process ที่สุ่มวัดทุก 20 ms รวม load/warmup; อาจพลาด spike สั้น |
| `peak_cuda_allocated_bytes` / `peak_cuda_reserved_bytes` | peak ของ PyTorch allocator ของ process หลัง warmup; ไม่ใช่ VRAM รวมของการ์ดหรือ TensorRT |
| `accuracy_metrics` | `null` จนกว่าจะมี ground truth และ accuracy evaluator |

ทรัพยากรที่อ่านไม่ได้รายงานเป็น `null` พร้อม `resource_notes`;
CPU run มี CUDA metrics เป็น `null` ห้ามแทนด้วยศูนย์เพื่ออ้างผลวัด
จำนวน detection และ FPS ไม่ได้พิสูจน์ความแม่นยำ และยังไม่เลือกโมเดลเริ่มต้นแทนผู้ใช้
ควรทดสอบบนเครื่องเป้าหมายและคลิปหลายสภาพก่อนตัดสินรุ่น/ขนาด

## Validation และงานต่อไป

Regression ครอบคลุมทะเบียน/hash, config เก่า, task/class/options, metadata,
GUI background/overlay และ benchmark subprocess บน synthetic fixture
workflow `Local detector adapter` ตรวจ inference ของ YOLO11n/YOLO26n ด้วย
random initialized local weights ซึ่งทดสอบความเข้ากันได้ ไม่ได้วัดความแม่นยำ
Windows/GPU/weights จริงของทีมและ export parity ยังต้องทำ smoke/benchmark เพิ่ม

ถัดไป: labelled footage ≥2 site → accuracy benchmark → Thai taxonomy fine-tuning
→ tracking/stitching → vehicle Re-ID และ wheel keypoints ตาม dependency ใน ROADMAP

อ้างอิง:
- https://docs.ultralytics.com/models/yolo11/
- https://docs.ultralytics.com/models/yolo26/
- https://docs.ultralytics.com/datasets/detect/coco/
