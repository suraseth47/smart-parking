# โมเดล AI

โฟลเดอร์นี้เก็บไฟล์โมเดล `.onnx` ซึ่ง**ไม่ commit เข้า git** (ไฟล์ใหญ่ ดูที่ `.gitignore`)
ต้องดาวน์โหลดเองก่อนรัน `docker compose up` หรือก่อนรันสคริปต์ P0

## โมเดลที่ใช้

**YOLOX-s** (Apache License 2.0) จาก [Megvii-BaseDetection/YOLOX](https://github.com/Megvii-BaseDetection/YOLOX)
— เลือกใช้เพราะ license เปิดกว่า Ultralytics YOLO (AGPL-3.0) ดูเหตุผลเต็มใน SPEC.md ข้อ 3.2 และ D-1

ตั้งแต่ 3 พ.ย. 2569 ระบบใช้ **YOLOX-m** เป็นค่าเริ่ม (แม่นกว่ากับรถไกลกล้อง/ฝนตก ใช้ CPU มากกว่าประมาณ 2.5–3 เท่า)
ถ้าไม่มีไฟล์ yolox_m.onnx ระบบถอยไปใช้ yolox_s.onnx เอง — ควรมีทั้ง 2 ไฟล์

## วิธีดาวน์โหลด

```bash
mkdir -p models
curl -L -o models/yolox_m.onnx \
  https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_m.onnx
curl -L -o models/yolox_s.onnx \
  https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx
```

ไฟล์ yolox_m.onnx ประมาณ 97 MB (input/output รูปแบบเดียวกับ yolox_s)

ไฟล์ที่ได้ควรมีขนาดประมาณ 34 MB, input `images` shape `[1,3,640,640]`, output `output` shape `[1,8400,85]`

ตรวจสอบว่าโหลดเข้า ONNX Runtime ได้:

```bash
python -c "import onnxruntime as ort; ort.InferenceSession('models/yolox_s.onnx')"
```
