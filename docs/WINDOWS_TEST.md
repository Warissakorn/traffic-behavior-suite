# ทดสอบ GUI บน Windows

## จากซอร์ส (รองรับวิดีโอจริงเมื่อเพิ่ม detection dependencies)

1. ดาวน์โหลด ZIP ของ branch ที่ต้องการทดสอบและแตกไฟล์
2. ติดตั้ง Python **3.12 x64** แล้วดับเบิลคลิก `Setup-Windows.cmd` (ใช้อินเทอร์เน็ตครั้งแรก)
3. เปิด `Launch-TBS.cmd` → แท็บ **ตัวอย่าง / ล่าสุด** → **ทดสอบตัวอย่าง**
4. ผลที่ต้องได้: 50 frames, 1 track, 1 crossing; เปิดหน้าผลลัพธ์และตรวจภาพได้
5. `Test-Windows.cmd` ตรวจ environment, benchmark และ GUI/worker smoke อัตโนมัติ

## ทดสอบวิดีโอจริงโดยไม่ใช้ calibration

1. กด **เปิดวิดีโอ** หรือเลือกไฟล์ในหน้า **ทดสอบวิดีโอ → วิดีโอจริง**
2. ดูภาพ เล่น/พัก กลับต้นคลิป หรือเลื่อนเวลาได้ทันที ไม่ต้องมี site YAML หรือโมเดล
3. หากจะลอง detection ให้รัน `Setup-Detection-Windows.cmd` เพิ่ม แล้วเลือก local YOLO
   weights ตั้ง Confidence, Device และ Class IDs (ปล่อยว่างเพื่อใช้ทุก class ของโมเดล)
4. เลือกโฟลเดอร์ผลลัพธ์ แล้วกด **ทดสอบ detection ทั้งคลิป**
5. หน้าประมวลผลแสดงจำนวนเฟรม/detections และยกเลิกได้ เมื่อสำเร็จเปิดหน้าภาพ + overlay
   เพื่อดูกรอบ class/confidence พร้อมเลื่อน/เล่นผลตาม PTS
6. **ส่งออก CSV** ได้ `detections.csv` (กรอบหน่วย px), `frames.csv`, `counts.csv`
   และ manifest; counts เป็นจำนวน detection ต่อ class รวมทุกเฟรม ไม่ใช่จำนวนรถไม่ซ้ำ

โหมดนี้เก็บพิกัดภาพเท่านั้น (`gx`, `gy`, `ground_method`, `track_id` เป็น null)
ไฟล์ vehicles/trajectories/line_crossings เป็นตารางว่างตาม schema เพื่อให้เปิดผลได้ด้วย
ResultStore เดิม; manifest ระบุ `run_mode: video_test` ส่วน epoch คือเวลาเริ่มงาน UTC
เวลาในคลิปเริ่มที่ PTS แรก ไม่ใช่เวลาถ่ายจริง inference ไม่ดาวน์โหลด weights เอง; ใช้ปุ่มดาวน์โหลด/อัปเดตโมเดลเมื่อจำเป็น
หากอ่านระยะเวลาท้ายคลิปไม่ได้ จะยังเล่นต่อเนื่องได้ แต่ slider เวลาไม่เปิดใช้งาน

## วิเคราะห์จุดสำรวจด้วย calibration

กด **ใช้วิดีโอนี้ตั้งค่าจุดสำรวจ** หรือเปิด/สร้าง site แล้วเลือกเวลาเริ่มจริง,
Camera YAML แบบ planar_homography และ local weights กดตรวจความพร้อมก่อนรัน
เพื่อคำนวณ trajectory ความเร็ว และเส้นนับ; input image ต้องผ่าน undistort แล้ว
ดูภาพได้แม้ยังไม่ได้เลือก calibration แต่การวาดเส้นบนพิกัดเมตรต้องโหลด calibration ก่อน

ฟอร์มรองรับ playlist, timezone, camera import, เส้นนับบนภาพและการแก้พิกัดเมตร,
model path, ช่อง Confidence/Device/Class IDs และ tracking options JSON ตาม Foundation schema
การเพิ่มหลายคลิปจะจัดเวลาเริ่มต่อเนื่องจากระยะเวลา PTS ของแต่ละคลิป
ต้องแก้เวลาให้ตรงการถ่ายจริง โดยเฉพาะคลิปที่มีช่วงว่างหรืออ่านระยะเวลาไม่ได้
ตรวจความพร้อมอ่านเฟรมแรก/ท้ายและตรวจเวลาซ้อนในงานเบื้องหลัง; pipeline ยังคงตรวจ PTS ทุกเฟรม
เลือกเส้น → วาดสองจุด; zoom ด้วยล้อเมาส์; ลาก endpoint ของเส้นที่เลือกเพื่อแก้ตำแหน่ง

ผลลัพธ์มีตารางการนับ, รายคัน/trajectory แบบแบ่งหน้า, วิดีโอ overlay ที่ seek ตาม PTS
และ CSV UTF-8 BOM พร้อมหน่วย/epoch/site/run ID
ค่าที่ pipeline ยังไม่คำนวณแสดงเป็น missing; ผลจำลองไม่ได้ยืนยันความแม่นยำกล้องจริง

แผงตั้งค่าปรับสัดส่วนหรือพับด้วย **แผงตั้งค่า** ได้ และซ่อน navigation ด้วย **เมนู**
ภาพและตารางยืดตามพื้นที่หน้าต่าง ฟอร์มที่ยาวเลื่อนภายในแผง ปุ่มรันอยู่ด้านล่างเสมอ
โปรแกรมจำขนาดหน้าต่างและสัดส่วนแผงเมื่อปิด

## Portable test build: CPU และ NVIDIA CUDA

Workflow **Windows portable test** สร้างโปรแกรม Windows x64 สองรุ่น:

| Artifact | การใช้งาน |
|---|---|
| `TBS-Windows-cpu` | เปิดวิดีโอ ตรวจ YOLO จับคู่รถและ OD บน CPU |
| `TBS-Windows-cuda` | ความสามารถเดียวกัน พร้อม PyTorch CUDA 12.8 และ ONNX Runtime GPU สำหรับ NVIDIA |

1. เปิด GitHub repository → **Actions → Windows portable test** → เลือก run ที่สำเร็จ
2. ดาวน์โหลด Artifact รุ่นที่ต้องการ (เก็บ 7 วัน) ถ้าเป็นการรันเอง เลือก **Run workflow**
   และ profile `cpu`, `cuda` หรือ `both` ได้หลัง workflow อยู่ใน repository
3. แตก ZIP ของ artifact แล้วแตก `TBS-Windows-cpu.zip` หรือ `TBS-Windows-cuda.zip` ภายในอีกครั้ง
4. เปิด `TBS/TBS.exe` ไม่ต้องติดตั้ง Python; ต้องเก็บ `TBSWorker.exe` และ `_internal` ไว้ด้วยกัน
5. เลือก/ดาวน์โหลด weights ผ่านโปรแกรม แล้วทดสอบวิดีโอจริง โมเดล pretrained ไม่ได้รวมใน ZIP

รุ่น CUDA มีขนาดใหญ่กว่ารุ่น CPU มากเพราะรวม GPU runtime
ต้องมี NVIDIA GPU และ driver ที่รองรับ CUDA 12.8 แนะนำอัปเดต driver จาก NVIDIA
ไม่ต้องติดตั้ง CUDA Toolkit เพื่อใช้แพ็กเกจนี้ ส่วน AMD/Intel ยังไม่รองรับผ่าน CUDA
ไฟล์ `.zip.sha256` ใช้ตรวจ SHA-256 ของ ZIP ได้ และ `build-info.json` ระบุ commit กับ package versions

### เลือก GPU ในโปรแกรม

- YOLO: Device `auto` เลือก CUDA GPU 0 ถ้าพร้อม ไม่เช่นนั้นใช้ CPU
- Device `0` / `cuda:0` บังคับ NVIDIA GPU; ถ้าไม่พร้อมจะแจ้งข้อผิดพลาด ไม่อ้างว่าประมวลผลด้วย GPU
- ปุ่ม **ตรวจ GPU ที่พร้อมใช้** แสดงชื่อ GPU; เปิด **FP16** ได้เฉพาะ YOLO บน CUDA
- Re-ID ONNX: เลือก **อุปกรณ์ Re-ID ONNX** เป็น `auto` หรือ `0` ในหน้าจับคู่รถ
  ต้องเลือกโมเดล Vehicle Re-ID ONNX ด้วย histogram สีทำงานบน CPU
- manifest ของ YOLO และผล Re-ID บันทึก backend/device ที่เลือกใช้จริง
  งาน decode วิดีโอ, tracking, geometry, CSV/Parquet และ candidate assignment ยังใช้ CPU
  FP16 ไม่ได้เปลี่ยน ONNX input contract ซึ่งยังเป็น float32 RGB

`Test-GPU.cmd` ในโฟลเดอร์โปรแกรมทดสอบ inference จริงบน GPU 0 ด้วยโมเดลสุ่มในเครื่อง
ทั้ง YOLO11/YOLO26 และ ONNX embedding เล็ก ๆ ดูผลที่ `gpu-test.json` และ `gpu-test.log`
การทดสอบนี้ยืนยัน runtime/driver ไม่ได้วัดความแม่นยำโมเดล
รุ่น CPU จะไม่ผ่านการทดสอบ GPU ซึ่งเป็นพฤติกรรมที่ถูกต้อง

### สิ่งที่ GitHub Actions ตรวจ

รัน source tests จากนั้นใช้ PyInstaller สร้าง GUI/worker ที่แชร์ runtime folder เดียว
และรัน frozen YOLO11/YOLO26, ONNX Re-ID บน CPU และ GUI → worker demo smoke ก่อนสร้าง ZIP
CUDA job ตรวจว่า wheel/runtime เป็น CUDA 12.8 และมี CUDA provider
Windows hosted runner ไม่มี NVIDIA GPU จึงยังไม่ใช่หลักฐานว่า CUDA inference ผ่านบนการ์ดจริง
ให้รัน `Test-GPU.cmd` บนเครื่องทดสอบด้วย
ถ้า tests, packaging, smoke หรือ artifact upload ล้มเหลว workflow จะแสดง failure
และพยายามแนบ build diagnostics; ไม่แสดง success ทั้งที่ไม่มีไฟล์ให้ดาวน์โหลด

สร้างเองบน Windows จากซอร์ส:

```powershell
py -3.12 -m venv .venv-build
.venv-build\Scripts\python.exe tools/windows/install_profile.py --profile cpu --build
.venv-build\Scripts\python.exe tools/windows/build.py --profile cpu
# เลือก --profile cuda ในทั้งสองคำสั่งหากต้องการแพ็กเกจ NVIDIA
```

ไฟล์อยู่ที่ `dist/TBS-Windows-cpu.zip` หรือ `dist/TBS-Windows-cuda.zip`
การสร้าง `.exe` ต้องใช้ Windows; Linux cloud ใช้ตรวจ source/runtime และ workflow ได้

### ติดตั้งจาก source บนเครื่อง NVIDIA

รัน `Setup-GPU-Windows.cmd` แล้วเปิด `Launch-TBS.cmd`
ติดตั้ง PyTorch 2.7.1 / torchvision 0.22.1 จาก official CUDA 12.8 index พร้อม ONNX Runtime GPU
`Setup-Detection-Windows.cmd` ใช้ runtime CPU ที่ pin ไว้แทน
อย่าติดตั้ง `onnxruntime` และ `onnxruntime-gpu` ซ้อนกันใน environment เดียว
setup scripts จะถอน distribution ฝั่งตรงข้ามก่อนติดตั้ง profile ใหม่

## เมื่อพบปัญหา

environment รุ่นเดิมใน LOCALAPPDATA สามารถคัดลอกเข้าโปรเจกต์โดยรัน
`py -3.12 tools/windows/migrate_environment.py` เมื่อยังไม่มี `.venv`
เครื่องมือนี้คัดลอก dependencies และปรับ launcher โดยเก็บต้นฉบับไว้ ไม่ดาวน์โหลดแพ็กเกจใหม่
ยังต้องติดตั้ง Python 3.12 x64; `.venv` ไม่ใช่ portable build และเมื่อย้ายโปรเจกต์ต้องรัน Setup ใหม่

* เปิด `Launch-TBS-Debug.cmd` เพื่อเห็น traceback และข้อความ dependency
* environment และ dependencies อยู่ใน `.venv` ภายในโฟลเดอร์โปรเจกต์ (ไม่รวมใน Git)
* log/settings อยู่ใน `%LOCALAPPDATA%/TrafficBehaviorSuite`
* log งานอยู่ใน `sessions/<session>.log`; launcher log อยู่ใน `logs/startup.log`
* ยกเลิกปกติรอเฟรม/stage ปัจจุบันคืน control; หลัง 5 วินาทีเลือก force-stop ได้
* failed/cancelled/interrupted run เป็นผลบางส่วน ไม่เปิดเป็นผลวิเคราะห์สำเร็จ
* artifact quota เต็ม: workflow จะแจ้ง upload failure ต้องคืนพื้นที่ Artifact แล้วรันใหม่
* setup ถูกขัดจังหวะ: รัน Setup ใหม่; ย้ายโฟลเดอร์ซอร์สให้ setup environment สำหรับ path ใหม่

CI ตรวจ Python tests บน Windows/Linux, GUI offscreen และ Windows frozen build;
การแสดงผล DPI, hardware decoder/driver และความแม่นยำภาคสนามยังต้องตรวจบนเครื่องจริง
