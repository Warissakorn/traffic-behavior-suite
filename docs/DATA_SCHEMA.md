# Data Schema (v1)

ข้อมูลทุกชนิดเก็บเป็น **Parquet** ภายใต้ `<output_dir>/<run_id>/` และทุกไฟล์มี metadata
`schema_version`, `run_id`, `config_hash`, `engine_version`

Runtime Foundation ใช้ subset `1-foundation` ตาม `python/tbs/storage.py`.
ในโหมดทดสอบ detection (`run_mode: video_test`) กรอบเป็นพิกัดภาพ หน่วย px;
`gx`, `gy`, `ground_method`, `track_id` เป็น null และตาราง vehicles/trajectories/
line_crossings ว่าง ส่วน epoch เป็นเวลาเริ่มงาน ไม่ใช่เวลาถ่ายจริง

หน่วย: ระยะทาง **เมตร**, เวลา **วินาที** (float64), ความเร็ว **ม./วินาที**, มุม **เรเดียน**
เวลา `t` = วินาทีนับจาก `epoch` ของ project (UTC, ระบุใน `project.yaml`) หลังแก้ clock offset แล้ว

## runs.parquet
| คอลัมน์ | ชนิด | คำอธิบาย |
|---|---|---|
| run_id | string | UUID |
| site_id | string | |
| started_at, finished_at | timestamp | |
| config_hash, model_hashes | string | SHA-256 |
| engine_version | string | |
| clock_offset_s, clock_drift_ppm | float64 | จาก S10 |

## detections.parquet (ตัวเลือก — debug/benchmark)
| คอลัมน์ | ชนิด | คำอธิบาย |
|---|---|---|
| frame_index | int64 | |
| t | float64 | |
| det_id | int64 | |
| class_id | int16 | |
| score | float32 | |
| x1, y1, x2, y2 | float32 | พิกเซล |
| kp | list<float32> | keypoints (u, v, conf) × N |
| gx, gy | float32 | ground point (ม.) |
| g_cov | list<float32> | covariance 2×2 |
| ground_method | int8 | 0=bottom-center, 1=footprint, 2=wheel-kp |
| track_id | int64 | หลัง tracking (−1 = ไม่ผูก) |

## trajectories.parquet (หลัก — S5/S6)
หนึ่งแถวต่อรถต่อช่วงเวลา resample (ค่าเริ่มต้น 0.1 วินาที)

| คอลัมน์ | ชนิด | คำอธิบาย |
|---|---|---|
| vehicle_id | int64 | unique ภายใน run |
| t | float64 | |
| x, y | float32 | พิกัดพื้น (ม.) |
| v | float32 | ความเร็ว |
| a | float32 | ความเร่งตามแนวการเคลื่อนที่ |
| heading | float32 | |
| lane_id | int16 | −1 = นอกช่อง |
| s, d | float32 | Frenet |
| leader_id | int64 | −1 = ไม่มี |
| space_headway, time_headway | float32 | NaN ถ้าไม่มีคันหน้า |
| observed | bool | false = ช่วงที่ interpolate/เติม |
| quality | float32 | 0–1 |

## vehicles.parquet (หนึ่งแถวต่อคัน)
| คอลัมน์ | ชนิด | คำอธิบาย |
|---|---|---|
| vehicle_id | int64 | |
| class_id, class_conf | int16, float32 | stable class |
| length, width | float32 | ม. |
| color | string | attribute |
| t_first, t_last | float64 | |
| origin_zone, dest_zone | string | OD ภายในจุด |
| flags | int32 | bitmask: occluded, stitched, low_conf, partial |
| quality | float32 | |

## lane_changes.parquet
| คอลัมน์ | ชนิด |
|---|---|
| vehicle_id, t_start, t_end, from_lane, to_lane | |
| lead_gap_target, lag_gap_target | float32 (ม.) |
| accepted | bool |

## line_crossings.parquet
| คอลัมน์ | ชนิด | คำอธิบาย |
|---|---|---|
| vehicle_id | int64 | |
| line_id | string | |
| t | float64 | sub-frame interpolation |
| direction | int8 | +1 / −1 |
| lane_id | int16 | |
| v | float32 | ความเร็วขณะข้าม |

## sightings.parquet (S8 → S9)
| คอลัมน์ | ชนิด | คำอธิบาย |
|---|---|---|
| sighting_id | string | `<site>:<run>:<vehicle>:<line>` |
| site_id, vehicle_id, line_id | | |
| t, direction, class_id, color, length | | |
| embedding | fixed_size_list<float16, D> | L2-normalized, D ตามโมเดล |
| embedding_model | string | hash |
| n_views, view_mask | int8 | |
| crop_ref | string | path ภาพตัวแทน |
| quality | float32 | |

## matches.parquet (S9)
| คอลัมน์ | ชนิด | คำอธิบาย |
|---|---|---|
| journey_id | int64 | รถ 1 คันข้ามหลายจุด |
| sighting_id | string | |
| seq | int16 | ลำดับจุดใน journey |
| p_match | float32 | ความน่าจะเป็นที่ calibrate แล้ว |
| appearance_score, st_score | float32 | |
| review_status | int8 | 0=auto, 1=confirmed, 2=rejected |

## Parameter outputs (S11)
- `params/micro/<class>.json` — การกระจายพารามิเตอร์ (ชื่อโมเดล, พารามิเตอร์, distribution, ช่วงความเชื่อมั่น, ขนาดตัวอย่าง, validation error)
- `params/macro/od_<period>.parquet`, `travel_time_<link>.parquet`, `vdf.json`
