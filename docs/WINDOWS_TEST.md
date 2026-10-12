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
เวลาในคลิปเริ่มที่ PTS แรก ไม่ใช่เวลาถ่ายจริง โปรแกรมไม่ดาวน์โหลด weights เอง
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

## Portable test build (demo-only)

Workflow **Windows portable test** สร้าง `TBS-Windows-Test.zip` บน Windows
หากอัปโหลด artifacts สำเร็จ ให้ดาวน์โหลดจากหน้า workflow แล้วแตกไฟล์และเปิด `TBS.exe`
รุ่นนี้รวม Python/Qt และ runtime ของ demo ไม่ต้องติดตั้ง Python และทดสอบตัวอย่าง offline ได้
เปิดดูวิดีโอได้ แต่ยังไม่รวม Torch/Ultralytics/weights;
การทดสอบ detection ของวิดีโอจริงใช้ source + detection setup ด้านบน

`TBSWorker.exe` และโฟลเดอร์ `_internal` ต้องอยู่กับ `TBS.exe`; ห้ามย้ายเฉพาะ exe
ดูเวอร์ชันที่ build ใน `build-info.json` และตรวจแบบ offscreen ด้วย `TBS.exe --smoke`
เกณฑ์นี้เป็น packaged smoke; ควรตรวจการกดใช้งานและ DPI บน desktop จริงเพิ่มเติม

สร้างเองบน Windows จากซอร์ส:

```powershell
py -3.12 -m venv .venv-build
.venv-build\Scripts\python.exe -m pip install -e ".[gui]" pyinstaller -c tools/windows/constraints.txt
.venv-build\Scripts\python.exe tools/windows/build.py
```

ไฟล์อยู่ที่ `dist/TBS-Windows-Test.zip`; build script ตรวจ GUI → frozen worker → demo
ก่อนสร้าง ZIP และ fail หาก smoke ไม่ผ่าน

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
* artifact quota เต็มไม่ทำให้ tests/build ล้ม; workflow เก็บ ZIP ใน draft release เป็นทางสำรอง
  ภายใต้ tag `tbs-windows-test-<commit>` ใน repository เดิม (ยังไม่ publish release)
* setup ถูกขัดจังหวะ: รัน Setup ใหม่; ย้ายโฟลเดอร์ซอร์สให้ setup environment สำหรับ path ใหม่

CI ตรวจ Python tests บน Windows/Linux, GUI offscreen และ Windows frozen build;
การแสดงผล DPI, hardware decoder/driver และความแม่นยำภาคสนามยังต้องตรวจบนเครื่องจริง
