import json, sqlite3, cv2, numpy as np
from shapely.geometry import Polygon, box as sbox
from core.config import PROJECT_ROOT, get_settings
from core.camera_utils import snapshot_path
from worker.detector import OnnxYoloxDetector, _preprocess, _decode_outputs, _cxcywh_to_xywh, INPUT_SIZE

CAM = 3
COCO = ("person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant stop_sign "
        "parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella "
        "handbag tie suitcase frisbee skis snowboard sports_ball kite baseball_bat baseball_glove skateboard "
        "surfboard tennis_racket bottle wine_glass cup fork knife spoon bowl banana apple sandwich orange "
        "broccoli carrot hot_dog pizza donut cake chair couch potted_plant bed dining_table toilet tv laptop "
        "mouse remote keyboard cell_phone microwave oven toaster sink refrigerator book clock vase scissors "
        "teddy_bear hair_drier toothbrush").split()

det = OnnxYoloxDetector(PROJECT_ROOT / "models" / "yolox_s.onnx")
img = cv2.imread(str(snapshot_path(CAM)))
H, W = img.shape[:2]
db = sqlite3.connect(get_settings().db_path)
slots = [(c, json.loads(p)) for c, p in db.execute(
    "select code, polygon from slots where camera_id=? order by code", (CAM,))]


def run(image, ox=0, oy=0, conf=0.05):
    padded, ratio = _preprocess(image, INPUT_SIZE)
    raw = det.session.run(None, {det.input_name: padded[None]})[0][0]
    d = _decode_outputs(raw, INPUT_SIZE)
    cls = d[:, 5:].argmax(1)
    sc = d[:, 4] * d[np.arange(len(d)), 5 + cls]
    keep = np.where(sc >= conf)[0]
    if len(keep) == 0:
        return []
    xywh = _cxcywh_to_xywh(d[keep, :4]) / ratio
    idx = np.array(cv2.dnn.NMSBoxes(xywh.tolist(), sc[keep].tolist(), conf, 0.45)).reshape(-1)
    out = []
    for i in idx:
        x, y, w, h = xywh[i]
        out.append((COCO[cls[keep][i]], float(sc[keep][i]), (x + ox, y + oy, x + w + ox, y + h + oy)))
    return sorted(out, key=lambda r: -r[1])


def slot_of(b):
    nb = sbox(b[0] / W, b[1] / H, b[2] / W, b[3] / H)
    best, code = 0.0, "-"
    for c, poly in slots:
        p = Polygon(poly)
        if p.is_valid and p.area > 0:
            r = p.intersection(nb).area / p.area
            if r > best:
                best, code = r, c
    return f"{code}({best:.0%})" if best > 0 else "-"


def show(title, rows):
    print(f"\n=== {title} ===")
    print(f"{'class':<14}{'score':>6}  {'slot(ทับ%)':<14} box[x1,y1,x2,y2]")
    for name, s, b in rows[:20]:
        print(f"{name:<14}{s:>6.2f}  {slot_of(b):<14} {[int(v) for v in b]}")
    if not rows:
        print("(ไม่พบวัตถุใดเลย)")


print("ภาพ", W, "x", H, "| ช่อง:", [c for c, _ in slots])
full = run(img)
show("1) ทั้งภาพ ทุกคลาส (score>=0.05)", full)
half = W // 2 + 100
left = run(img[:, :half], 0, 0)
show(f"2) ตัดเฉพาะซ้าย x0-{half} (ขยายใหญ่ขึ้น ~1.8 เท่า)", left)
flip = img[::-1, ::-1].copy()
rot = [(n, s, (W - b[2], H - b[3], W - b[0], H - b[1])) for n, s, b in run(flip)]
show("3) หมุนภาพ 180 องศา", rot)

vis = img.copy()
for c, poly in slots:
    pts = np.array([[int(x * W), int(y * H)] for x, y in poly], np.int32)
    cv2.polylines(vis, [pts], True, (255, 160, 0), 3)
    cv2.putText(vis, c, tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 160, 0), 3)
for name, s, b in full:
    color = (0, 220, 0) if name in ("car", "truck", "bus") else (0, 0, 255)
    cv2.rectangle(vis, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), color, 3)
    cv2.putText(vis, f"{name} {s:.2f}", (int(b[0]) + 4, int(b[1]) + 34), cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 3)
out = get_settings().data_dir / "snapshots" / f"debug_camera_{CAM}.jpg"
cv2.imwrite(str(out), vis)
print("\nบันทึกภาพวิเคราะห์ไว้ที่", out)
