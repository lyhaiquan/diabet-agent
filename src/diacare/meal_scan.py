"""Agent bữa ăn: gửi ảnh khay cơm cho dịch vụ Calo Khay (nhận diện 44 món, ước lượng gram) qua HTTP, rồi tính
lượng tinh bột của bữa bằng bảng data/nutrition/calo_khay_carb.csv (tools/build_carb_table.py, nguồn Nutrition5k /
USDA FNDDS).

Calo Khay là project riêng (YOLO + DINOv2, cần torch), chạy như một dịch vụ cục bộ: chay_calo_khay.bat. DiaCare chỉ
gọi POST {DIACARE_CALO_URL}/api/scan, nên không phải cài torch vào môi trường của DiaCare.

Mọi con số tinh bột tính theo bảng, không do LLM viết. Kết quả là KHOẢNG ước lượng:
  thấp = tổng gram x (1 - sai số gram) x carb chính
  cao  = tổng gram x (1 + sai số gram) x carb cận trên
Sai số gram ±30% theo đánh giá của Calo Khay; gram người dùng đã tự sửa thì lấy ±15%. Riêng gram "trung bình"
(cơm khi không bật độ sâu: luôn 228 g; món khi không thấy đĩa) không phải số đo từ ảnh: README Calo Khay ghi sai số
tổng khay ~112 g khi không bật độ sâu, cỡ một nửa phần cơm, nên lấy ±50%. Chỉ để theo dõi, không dùng để tính liều
insulin.
"""
import csv
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARB_TABLE = ROOT / "data" / "nutrition" / "calo_khay_carb.csv"
DEFAULT_URL = "http://127.0.0.1:8010"
MODEL_GRAM_ERR = 0.30
USER_GRAM_ERR = 0.15
MEAN_GRAM_ERR = 0.50
MEAN_METHODS = ("rice_mean", "class_mean")
NOT_COUNTED = "drink"


class CaloKhayError(RuntimeError):
    """Lỗi có câu tiếng Việt để hiện thẳng cho người dùng."""


def service_url():
    return (os.environ.get("DIACARE_CALO_URL") or DEFAULT_URL).rstrip("/")


def load_table(path=CARB_TABLE):
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            num = (lambda v: float(v) if v not in ("", None) else None)
            out[r["class"]] = {"name": r["name_vi"], "carb": num(r["carb_per_100g"]),
                               "carb_high": num(r["carb_high"]), "kcal": num(r["kcal_per_100g"]),
                               "match": r["match"], "note": r["note"]}
    return out


def _multipart(field, filename, data, content_type):
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def scan(image_bytes, filename="khay.jpg", content_type="image/jpeg", url=None, timeout=60):
    """Gửi ảnh cho Calo Khay, trả về JSON kết quả quét (items, plate_found, warnings...)."""
    body, ctype = _multipart("image", filename, image_bytes, content_type)
    req = urllib.request.Request((url or service_url()) + "/api/scan", data=body, method="POST",
                                 headers={"Content-Type": ctype})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("message")
        except (ValueError, AttributeError):
            msg = None
        raise CaloKhayError(msg or f"Dịch vụ nhận diện món báo lỗi {e.code}.") from e
    except (urllib.error.URLError, OSError) as e:
        raise CaloKhayError("Chưa kết nối được dịch vụ nhận diện món Calo Khay. Hãy bật nó bằng chay_calo_khay.bat "
                            "rồi thử lại.") from e
    with resp:
        return json.loads(resp.read().decode("utf-8"))


def items_from_scan(res, table):
    """Danh sách món để người dùng xác nhận/sửa. Không thấy đĩa thì mọi món đều cần xác nhận (ảnh có thể không
    phải khay cơm)."""
    items = []
    for it in res.get("items", []):
        cls = it["cls"] if it["cls"] in table else None
        items.append({
            "cls": cls, "name": table[cls]["name"] if cls else it.get("name", it["cls"]),
            "grams": int(round(it.get("grams") or 0)), "conf": it.get("conf"),
            "needs_confirm": bool(it.get("needs_confirm")) or not res.get("plate_found", True) or cls is None,
            "suggestions": [s for s in it.get("suggestions", []) if s in table],
            "gram_method": it.get("gram_method"), "gram_source": "model",
        })
    return items


def meal_carbs(items, table):
    """Tổng tinh bột (khoảng) và kcal của bữa từ danh sách món đã xác nhận."""
    lo = mid = hi = kcal = 0.0
    rows, uncounted = [], []
    for it in items:
        row = table.get(it.get("cls"))
        grams = float(it.get("grams") or 0)
        if row is None or row["carb"] is None:
            if grams > 0:
                uncounted.append(row["name"] if row else (it.get("name") or "món lạ"))
            continue
        if it.get("gram_source") == "user":
            err = USER_GRAM_ERR
        elif it.get("gram_method") in MEAN_METHODS:
            err = MEAN_GRAM_ERR
        else:
            err = MODEL_GRAM_ERR
        c_mid = grams * row["carb"] / 100
        c_lo = grams * (1 - err) * row["carb"] / 100
        c_hi = grams * (1 + err) * row["carb_high"] / 100
        lo, mid, hi = lo + c_lo, mid + c_mid, hi + c_hi
        kcal += grams * (row["kcal"] or 0) / 100
        rows.append({"cls": it["cls"], "name": row["name"], "grams": grams, "carb": round(c_mid, 1),
                     "carb_low": round(c_lo, 1), "carb_high": round(c_hi, 1)})
    return {"carb_g": round(mid), "carb_low": round(lo), "carb_high": round(hi), "kcal": round(kcal),
            "items": rows, "uncounted": uncounted}


def carb_text(total):
    """Câu tóm tắt cho người dùng. Khoảng, không phải một con số chính xác."""
    if not total["items"]:
        return "Chưa có món nào để tính tinh bột."
    text = (f"Bữa này ước lượng khoảng **{total['carb_low']}–{total['carb_high']} g tinh bột** "
            f"(giữa khoảng {total['carb_g']} g), khoảng {total['kcal']} kcal.")
    top = max(total["items"], key=lambda r: r["carb"])
    if total["carb_g"] and top["carb"] >= 0.5 * total["carb_g"]:
        text += f" Phần lớn tinh bột đến từ {top['name']} ({top['grams']:.0f} g)."
    if total["uncounted"]:
        text += f" Chưa tính: {', '.join(total['uncounted'])} (đồ uống ngọt có thể nhiều tinh bột hơn cả khay)."
    return text
