# โมเดล AI

โฟลเดอร์นี้เก็บไฟล์โมเดล `.onnx` ซึ่ง**ไม่ commit เข้า git** (ไฟล์ใหญ่ ดูที่ `.gitignore`)
ต้องดาวน์โหลดเองก่อนรัน `docker compose up` หรือก่อนรันสคริปต์ P0

## โมเดลที่ใช้

**YOLOX-s** (Apache License 2.0) จาก [Megvii-BaseDetection/YOLOX](https://github.com/Megvii-BaseDetection/YOLOX)
— เลือกใช้เพราะ license เปิดกว่า Ultralytics YOLO (AGPL-3.0) ดูเหตุผลเต็มใน SPEC.md ข้อ 3.2 และ D-1

## วิธีดาวน์โหลด

```bash
mkdir -p models
curl -L -o models/yolox_s.onnx \
  https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx
```

ไฟล์ที่ได้ควรมีขนาดประมาณ 34 MB, input `images` shape `[1,3,640,640]`, output `output` shape `[1,8400,85]`

ตรวจสอบว่าโหลดเข้า ONNX Runtime ได้:

```bash
python -c "import onnxruntime as ort; ort.InferenceSession('models/yolox_s.onnx')"
```

## เลือกโมเดลที่แม่นขึ้น (YOLOX-m)

YOLOX-m แม่นกว่า YOLOX-s ชัดเจน (ทดสอบกับกล้องลานจอดจริง: ความมั่นใจของรถ 0.9 เทียบกับ 0.4–0.5
ทำให้ไม่หลุดเกณฑ์ง่าย) แต่ใช้ CPU มากขึ้นประมาณ 2 เท่า และไฟล์ใหญ่ ~97 MB — license เดียวกัน (Apache-2.0)

1. ดาวน์โหลดไว้คู่กับ yolox_s (บน Server ในโฟลเดอร์ `~/smart-parking`):
   ```bash
   curl -L -o models/yolox_m.onnx \
     https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_m.onnx
   ```
2. เทียบกับภาพจริงของกล้องก่อน (ไม่เปลี่ยนค่าในระบบ):
   ```bash
   docker compose exec -T worker python - < tools/compare_models.py
   ```
3. ถ้าผลดีกว่าและเวลาต่อภาพรับได้ ให้เพิ่มใน `.env` แล้วรีสตาร์ต:
   ```bash
   echo "DETECTOR_MODEL=yolox_m.onnx" >> .env
   docker compose up -d
   docker compose logs worker | grep "ใช้โมเดล"
   ```
   ย้อนกลับ: ลบบรรทัด `DETECTOR_MODEL` ใน `.env` แล้ว `docker compose up -d`
   (ถ้าตั้งชื่อไฟล์ที่ไม่มีอยู่ ระบบจะกลับไปใช้ yolox_s.onnx ให้อัตโนมัติ)

ประมาณงานของ CPU: เวลาต่อภาพ x จำนวนกล้อง ต้องน้อยกว่ารอบตรวจจับ (ค่าเริ่ม 30 วินาที/กล้อง) มากๆ
