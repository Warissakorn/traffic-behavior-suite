# ทดสอบ GUI บน Windows

## จากซอร์ส (รองรับวิดีโอจริงเมื่อเพิ่ม detection dependencies)

1. ดาวน์โหลด ZIP ของ branch `codex/foundation-single-site-pipeline` และแตกไฟล์
2. ติดตั้ง Python **3.12 x64** แล้วดับเบิลคลิก `Setup-Windows.cmd` (ใช้อินเทอร์เน็ตครั้งแรก)
3. เปิด `Launch-TBS.cmd` แล้วกด **ทดสอบตัวอย่าง**
4. ผลที่ต้องได้: 50 frames, 1 track, 1 crossing; เปิดหน้าผลลัพธ์และตรวจภาพได้
5. `Test-Windows.cmd` ตรวจ environment, benchmark และ GUI/worker smoke อัตโนมัติ

หากจะใช้ local YOLO weights ให้รัน `Setup-Detection-Windows.cmd` เพิ่ม แล้วเปิด/สร้าง
site ใน GUI เลือกวิดีโอพร้อมเวลาเริ่ม, camera YAML แบบ planar_homography และไฟล์ weights
กดตรวจความพร้อมก่อนประมวลผล; input image ต้องผ่าน undistort แล้ว
ตัวโปรแกรมไม่ดาวน์โหลด detector weights เอง

ฟอร์มรองรับ playlist, timezone, camera import, เส้นนับบนภาพและการแก้พิกัดเมตร,
model path และ options JSON ตาม Foundation schema
เลือกเส้น → วาดสองจุด; zoom ด้วยล้อเมาส์; ลาก endpoint ของเส้นที่เลือกเพื่อแก้ตำแหน่ง

ผลลัพธ์มีตารางการนับ, รายคัน/trajectory แบบแบ่งหน้า, วิดีโอ overlay ที่ seek ตาม PTS
และ CSV UTF-8 BOM พร้อมหน่วย/epoch/site/run ID
ค่าที่ pipeline ยังไม่คำนวณแสดงเป็น missing; ผลจำลองไม่ได้ยืนยันความแม่นยำกล้องจริง

## Portable test build (demo-only)

Workflow **Windows portable test** สร้าง `TBS-Windows-Test.zip` บน Windows
หากอัปโหลด artifacts สำเร็จ ให้ดาวน์โหลดจากหน้า workflow แล้วแตกไฟล์และเปิด `TBS.exe`
รุ่นนี้รวม Python/Qt และ runtime ของ demo ไม่ต้องติดตั้ง Python และทดสอบตัวอย่าง offline ได้
ยังไม่รวม Torch/Ultralytics/weights; งานวิดีโอจริงใช้ source + detection setup ด้านบน

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

* เปิด `Launch-TBS-Debug.cmd` เพื่อเห็น traceback และข้อความ dependency
* log/settings/environment อยู่ใน `%LOCALAPPDATA%/TrafficBehaviorSuite`
* log งานอยู่ใน `sessions/<session>.log`; launcher log อยู่ใน `logs/startup.log`
* ยกเลิกปกติรอเฟรม/stage ปัจจุบันคืน control; หลัง 5 วินาทีเลือก force-stop ได้
* failed/cancelled/interrupted run เป็นผลบางส่วน ไม่เปิดเป็นผลวิเคราะห์สำเร็จ
* artifact quota เต็มไม่ทำให้ tests/build ล้ม; workflow เก็บ ZIP ใน draft release เป็นทางสำรอง
  ภายใต้ tag `tbs-windows-test-<commit>` ใน repository เดิม (ยังไม่ publish release)
* setup ถูกขัดจังหวะ: รัน Setup ใหม่; ย้ายโฟลเดอร์ซอร์สให้ setup environment สำหรับ path ใหม่

CI ตรวจ Python tests บน Windows/Linux, GUI offscreen และ Windows frozen build;
การแสดงผล DPI, hardware decoder/driver และความแม่นยำภาคสนามยังต้องตรวจบนเครื่องจริง
