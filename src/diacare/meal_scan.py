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
    for no, it in enumerate(res.get("items", []), 1):
        cls = it["cls"] if it["cls"] in table else None
        items.append({
            "no": no, "polygons": it.get("polygons") or [],
            "cls": cls, "name": table[cls]["name"] if cls else it.get("name", it["cls"]),
            "grams": int(round(it.get("grams") or 0)), "conf": it.get("conf"),
            "needs_confirm": bool(it.get("needs_confirm")) or not res.get("plate_found", True) or cls is None,
            "suggestions": [s for s in it.get("suggestions", []) if s in table],
            "gram_method": it.get("gram_method"), "gram_source": "model",
        })
    return items


# Màu vùng món trên ảnh (đủ tương phản trên nền cơm trắng và khay tối), lặp lại khi nhiều món hơn.
OVERLAY_COLORS = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180), (70, 240, 240),
                  (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (170, 110, 40), (128, 0, 0)]


def annotate(image_bytes, items, image_size=None):
    """Vẽ vùng của từng món (polygons Calo Khay trả về) lên ảnh, tô màu nhạt, viền đậm và ghi SỐ THỨ TỰ của món ở
    giữa vùng, khớp với cột "#" của bảng xác nhận: người dùng thấy món nào bị nhận sai. Toạ độ của Calo Khay theo
    kích thước ảnh nó đã xử lý (`image_size` = {"w", "h"}); ảnh gốc khác kích thước thì co giãn theo. Trả về PNG."""
    import io

    from PIL import Image, ImageDraw, ImageFont, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    sx = img.width / image_size["w"] if image_size and image_size.get("w") else 1.0
    sy = img.height / image_size["h"] if image_size and image_size.get("h") else 1.0
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    size = max(18, img.width // 22)
    try:
        font = ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        except OSError:
            font = ImageFont.load_default()
    labels = []
    for it in items:
        color = OVERLAY_COLORS[(it["no"] - 1) % len(OVERLAY_COLORS)]
        biggest = None
        for poly in it.get("polygons") or []:
            pts = [(x * sx, y * sy) for x, y in poly]
            if len(pts) < 3:
                continue
            draw.polygon(pts, fill=color + (70,), outline=color + (255,), width=max(2, img.width // 300))
            if biggest is None or len(pts) > len(biggest):
                biggest = pts
        if biggest:
            cx = sum(x for x, _ in biggest) / len(biggest)
            cy = sum(y for _, y in biggest) / len(biggest)
            labels.append((cx, cy, str(it["no"]), color))
    out = Image.alpha_composite(img.convert("RGBA"), layer)
    draw = ImageDraw.Draw(out)
    for cx, cy, text, color in labels:  # số vẽ sau cùng để không bị vùng khác che
        r = size * 0.8
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (255,), outline=(255, 255, 255, 255), width=3)
        draw.text((cx, cy), text, fill=(255, 255, 255, 255), font=font, anchor="mm")
    buf = io.BytesIO()
    out.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


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


# ---------- nối bữa ăn với đường huyết sau ăn ----------
# Đường huyết sau ăn đo 1-2 giờ sau khi bắt đầu ăn (ADA); nhận rộng 45 phút - 3 giờ vì người dùng ghi giờ ăn ước chừng.
AFTER_MIN, AFTER_MAX = 45, 180
SLOT_TEXT = {"breakfast": "bữa sáng", "lunch": "bữa trưa", "dinner": "bữa tối", "snack": "bữa phụ"}


def pair_after_meal(meals, readings, targets=None):
    """Mỗi bữa -> lần đo đường huyết ĐẦU TIÊN trong 45 phút - 3 giờ sau bữa (bất kể ghi là thời điểm đo nào), kèm
    nhận định so với mục tiêu sau ăn. Trả về [{"meal", "reading" (hoặc None), "minutes", "status"}]."""
    from datetime import timedelta

    from diacare import journal
    t = targets or journal.resolve_targets()
    glucose = sorted(journal.glucose_rows(readings), key=lambda r: journal.to_vn(r["measured_at"]))
    out = []
    for m in meals:
        eaten = journal.to_vn(m["eaten_at"])
        hit = next((r for r in glucose
                    if eaten + timedelta(minutes=AFTER_MIN) <= journal.to_vn(r["measured_at"])
                    <= eaten + timedelta(minutes=AFTER_MAX)), None)
        if hit is None:
            out.append({"meal": m, "reading": None, "minutes": None, "status": None})
            continue
        minutes = round((journal.to_vn(hit["measured_at"]) - eaten).total_seconds() / 60)
        out.append({"meal": m, "reading": hit, "minutes": minutes,
                    "status": journal.classify_glucose(hit["value"], "after_meal", t)})
    return out


def after_meal_text(pair, targets=None):
    """Ví dụ: "9,2 mmol/L sau 95 phút, trong mục tiêu" / "chưa đo sau ăn"."""
    from diacare import journal
    if pair["reading"] is None:
        return "chưa đo sau ăn"
    r = pair["reading"]
    return (f"{journal.fmt_glucose(r['value'], r.get('unit') or 'mmol/L')} sau {pair['minutes']} phút, "
            f"{journal.STATUS_TEXT[pair['status']]}")


def meal_journal_lines(meals, readings, days=14, now=None, targets=None):
    """Vài dòng tóm tắt bữa ăn (đã quét ảnh) và đường huyết sau các bữa đó, cho ngữ cảnh trang Tư vấn. Số liệu tính
    sẵn ở đây (như nhật ký), mô hình chỉ diễn giải."""
    from datetime import timedelta

    from diacare import journal
    now = journal.to_vn(now or journal.now_vn())
    t = targets or journal.resolve_targets()
    recent = sorted((m for m in meals if now - timedelta(days=days) <= journal.to_vn(m["eaten_at"]) <= now),
                    key=lambda m: journal.to_vn(m["eaten_at"]))
    if not recent:
        return []
    avg_lo = sum(m["carb_low"] for m in recent) / len(recent)
    avg_hi = sum(m["carb_high"] for m in recent) / len(recent)
    lines = [f"- Bữa ăn ghi bằng ảnh {days} ngày qua: {len(recent)} bữa, trung bình khoảng {avg_lo:.0f}–{avg_hi:.0f} g "
             "tinh bột mỗi bữa (ước lượng từ ảnh, sai số lớn)."]
    pairs = pair_after_meal(recent, readings, t)
    last = pairs[-1]
    m = last["meal"]
    dishes = ", ".join(f"{it['name']} {it['grams']:.0f} g" for it in m["items"] if not it.get("uncounted"))
    lines.append(f"  + Bữa gần nhất: {SLOT_TEXT.get(m['slot'], 'bữa ăn')} {journal.to_vn(m['eaten_at']):%H:%M %d/%m}, "
                 f"khoảng {m['carb_low']:.0f}–{m['carb_high']:.0f} g tinh bột ({dishes}); "
                 f"đường huyết sau ăn: {after_meal_text(last, t)}.")
    measured = [p for p in pairs if p["reading"] is not None]
    high = [p for p in measured if p["status"] in ("above_target", "very_high")]
    ok = [p for p in measured if p["status"] == "in_target"]
    if measured:
        line = (f"  + Có đo sau ăn {len(measured)}/{len(pairs)} bữa; {len(high)} bữa đường huyết sau ăn cao hơn "
                f"mục tiêu (dưới {journal._mmol(t['post'])} mmol/L)")
        if len(high) >= 2 and len(ok) >= 2:
            mid = (lambda ps: sum(p["meal"]["carb_g"] for p in ps) / len(ps))
            line += (f"; các bữa cao sau ăn trung bình khoảng {mid(high):.0f} g tinh bột, các bữa trong mục tiêu "
                     f"khoảng {mid(ok):.0f} g")
        lines.append(line + ".")
    else:
        lines.append("  + Chưa có lần đo đường huyết nào 1–2 giờ sau các bữa này.")
    return lines


# ---------- gợi ý ăn uống từ đường huyết sau ăn (V4.9) ----------
# Mọi con số ở đây tính bằng code từ bữa đã lưu, bảng tinh bột và số đo; LLM chỉ được đọc lại các câu này.
# Món ít tinh bột để gợi ý ăn thay phần tinh bột bớt đi: chọn theo nhóm (rau, đạm), con số lấy từ bảng.
LOW_CARB_VEG = ("water_spinach", "cabbage", "leafy_greens", "chayote", "radish", "stir_fried_vegetables",
                "bean_sprouts_green_beans", "bean_sprouts_bamboo")
LOW_CARB_PROTEIN = ("boiled_egg", "fried_tofu", "boiled_pork", "rolled_omelette", "fried_egg", "quail_egg")
LOW_CARB_MAX = 7.0        # g tinh bột / 100 g: dưới mức này coi là món ít tinh bột
MAIN_SHARE = 0.30         # món góp từ 30% tinh bột của bữa trở lên thì đáng nhắc
ADVICE_CAVEAT = ("Gợi ý từ ước lượng ảnh (gram sai khoảng ±30%, cơm có thể ±50%) và vài lần đo; đường huyết sau ăn "
                 "còn phụ thuộc thuốc, vận động và cả bữa, không chỉ một món. Không dùng để chỉnh liều thuốc hay "
                 "insulin; bác sĩ có thể đặt mục tiêu khác.")


def _round10(x):
    return int(round(x / 10.0) * 10)


def meal_advice(meals, readings, table=None, now=None, targets=None, days=14):
    """Gợi ý nên hạn chế món nào, có thể ăn thêm món nào, từ các bữa đã ghi và đường huyết đo sau các bữa đó.

    Trả về {"status", "headline", "limit": [...], "more": [...], "own_ok": [...], "lines": [...], "caveat"}.
    status: "hypo" (24 giờ qua có hạ đường huyết: KHÔNG khuyên bớt tinh bột), "no_meals", "need_after" (chưa đo
    sau ăn), "all_ok" (các bữa đã đo đều trong mục tiêu), "high" (có bữa cao sau ăn).
    Chỉ nói "nhiều lần" khi có từ 2 bữa cao trở lên; một lần thì nói rõ một lần chưa đủ kết luận."""
    from datetime import timedelta

    from diacare import journal
    table = table or load_table()
    now = journal.to_vn(now or journal.now_vn())
    t = targets or journal.resolve_targets()
    out = {"status": None, "headline": "", "limit": [], "more": [], "own_ok": [], "lines": [], "caveat": ADVICE_CAVEAT}

    # 1. An toàn trước: trong 24 giờ qua có hạ đường huyết thì không khuyên ăn bớt
    hypo = [r for r in journal.glucose_rows(readings)
            if now - timedelta(hours=24) <= journal.to_vn(r["measured_at"]) <= now
            and journal.classify_glucose(r["value"], r["context"], t) in ("hypo_1", "hypo_2")]
    if hypo:
        out["status"] = "hypo"
        out["headline"] = ("Trong 24 giờ qua bạn có lần hạ đường huyết, nên lúc này mình không gợi ý ăn bớt tinh bột. "
                           "Ăn đủ bữa, đúng giờ, và báo bác sĩ về lần hạ đường huyết này.")
        out["lines"] = [out["headline"], journal.ADVICE["hypo_1"][1]]
        return out

    recent = sorted((m for m in meals if now - timedelta(days=days) <= journal.to_vn(m["eaten_at"]) <= now),
                    key=lambda m: journal.to_vn(m["eaten_at"]))
    if not recent:
        out["status"] = "no_meals"
        out["headline"] = ("Chưa có bữa ăn nào được ghi. Chụp ảnh bữa ăn ở trang Bữa ăn, rồi đo đường huyết khoảng 2 giờ "
                           "sau khi ăn, mình sẽ cho biết món nào góp nhiều tinh bột.")
        out["lines"] = [out["headline"]]
        return out
    pairs = pair_after_meal(recent, readings, t)
    measured = [p for p in pairs if p["reading"] is not None]
    if not measured:
        out["status"] = "need_after"
        out["headline"] = (f"Bạn đã ghi {len(recent)} bữa nhưng chưa có lần đo nào 1–2 giờ sau các bữa đó. Đo đường "
                           "huyết khoảng 2 giờ sau khi bắt đầu ăn để biết bữa nào làm đường huyết lên cao.")
        out["lines"] = [out["headline"]]
        return out

    high = [p for p in measured if p["status"] in ("above_target", "very_high")]
    ok = [p for p in measured if p["status"] == "in_target"]
    post = journal._mmol(t["post"])

    # 2. Món ít tinh bột: trước hết là món có trong các bữa vẫn trong mục tiêu của chính người dùng
    own = {}
    for p in ok:
        for it in p["meal"]["items"]:
            row = table.get(it.get("cls"))
            if row and row["carb"] is not None and row["carb"] <= LOW_CARB_MAX:
                own.setdefault(it["cls"], row["name"])
    out["own_ok"] = list(own.values())
    pick = [c for c in LOW_CARB_VEG if c in table][:3] + [c for c in LOW_CARB_PROTEIN if c in table][:3]
    out["more"] = [{"cls": c, "name": table[c]["name"], "carb_per_100g": table[c]["carb"]} for c in pick]

    if not high:
        out["status"] = "all_ok"
        out["headline"] = (f"{len(measured)} lần đo sau ăn đều dưới {post} mmol/L. Bạn cứ giữ cách ăn hiện tại, nhất "
                           "là lượng cơm như các bữa đó.")
        out["lines"] = [out["headline"]]
        if out["own_ok"]:
            out["lines"].append("Món ít tinh bột trong các bữa đó: " + ", ".join(out["own_ok"]) + ".")
        return out

    # 3. Món góp nhiều tinh bột trong các bữa cao sau ăn
    dish = {}
    for p in high:
        meal_carb = sum(float(it.get("carb") or 0) for it in p["meal"]["items"] if not it.get("uncounted"))
        if meal_carb <= 0:
            continue
        for it in p["meal"]["items"]:
            c = float(it.get("carb") or 0)
            if it.get("uncounted") or c <= 0 or c / meal_carb < MAIN_SHARE:
                continue
            d = dish.setdefault(it.get("cls") or it["name"], {"name": it["name"], "times": 0, "carb": 0.0,
                                                               "grams": 0.0, "share": 0.0})
            d["times"] += 1
            d["carb"] += c
            d["grams"] += float(it.get("grams") or 0)
            d["share"] += c / meal_carb
    limit = []
    for d in sorted(dish.values(), key=lambda d: -d["carb"]):
        n = d["times"]
        grams = d["grams"] / n
        limit.append({"name": d["name"], "times": n, "grams": round(grams), "carb": round(d["carb"] / n),
                      "share": round(100 * d["share"] / n), "suggest_grams": max(_round10(grams * 2 / 3), 10)})
    out["limit"] = limit[:3]
    out["status"] = "high"

    last = high[-1]
    m, r = last["meal"], last["reading"]
    when = journal.to_vn(m["eaten_at"])
    if when.date() == now.date():
        day = "hôm nay"
    elif when.date() == now.date() - timedelta(days=1):
        day = "hôm qua"
    else:
        day = f"ngày {when:%d/%m}"
    out["headline"] = (f"Sau {SLOT_TEXT.get(m['slot'], 'bữa ăn')} {day} ({when:%H:%M}), đường huyết "
                       f"{journal.fmt_glucose(r['value'], r.get('unit') or 'mmol/L')} sau {last['minutes']} phút, "
                       f"cao hơn mục tiêu (dưới {post} mmol/L).")
    lines = [out["headline"]]
    if len(high) >= 2:
        lines.append(f"Trong {days} ngày qua có {len(high)}/{len(measured)} bữa cao sau ăn.")
    else:
        lines.append("Mới có một lần cao sau ăn, chưa đủ để kết luận; đo thêm sau vài bữa nữa để chắc hơn.")
    for d in out["limit"]:
        often = f"{d['times']} bữa cao" if d["times"] >= 2 else "bữa cao"
        lines.append(f"Nên hạn chế: {d['name']} khoảng {d['grams']} g, góp khoảng {d['carb']} g tinh bột "
                     f"({d['share']}% tinh bột của {often}). Thử bớt còn khoảng {d['suggest_grams']} g.")
    if len(high) >= 2 and len(ok) >= 2:
        def mid(ps):
            return sum(p["meal"]["carb_g"] for p in ps) / len(ps)
        lines.append(f"Các bữa cao sau ăn trung bình khoảng {mid(high):.0f} g tinh bột, các bữa trong mục tiêu khoảng "
                     f"{mid(ok):.0f} g.")
    if out["more"]:
        lines.append("Có thể ăn thêm thay phần bớt đi (ít tinh bột): "
                     + ", ".join(f"{x['name']} ({x['carb_per_100g']:g} g/100 g)".replace(".", ",")
                                 for x in out["more"]) + ".")
    if out["own_ok"]:
        lines.append("Món ít tinh bột đã có trong các bữa trong mục tiêu của bạn: " + ", ".join(out["own_ok"]) + ".")
    out["lines"] = lines
    return out
