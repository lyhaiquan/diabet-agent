import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd
import pytest

from diacare import meal_scan
from diacare.factory import open_store

# Kết quả thật của Calo Khay cho examples/B_212.jpg (bỏ polygons): giữ để biết khi API đổi dạng
SCAN = json.loads((Path(__file__).parent / "fixtures" / "calo_scan_B212.json").read_text(encoding="utf-8"))
TABLE = meal_scan.load_table()


def test_table_covers_every_calo_khay_class():
    calo = [c for c, r in TABLE.items() if not r["match"].startswith("nhập tay")]
    assert len(calo) == 45
    for cls, row in TABLE.items():
        if cls == "drink":
            assert row["carb"] is None
            continue
        assert 0 <= row["carb"] <= row["carb_high"] <= 100, cls
        assert row["kcal"] is not None, cls
    assert TABLE["rice"]["carb"] == 28.0
    # chả giò có vỏ: không được lấy 4% của mục "spring rolls" (ước thấp là chiều nguy hiểm)
    assert TABLE["shrimp_spring_roll"]["carb"] > 20
    assert TABLE["coconut_braised_pork"]["carb_high"] > TABLE["coconut_braised_pork"]["carb"]


def test_items_from_real_scan():
    items = meal_scan.items_from_scan(SCAN, TABLE)
    assert [it["cls"] for it in items] == ["potato", "stir_fried_vegetables", "rice", "fried_tofu", "boiled_egg",
                                           "quail_egg"]
    veg = items[1]
    assert veg["needs_confirm"] and veg["suggestions"] == ["pork_broccoli"]
    assert items[2]["gram_method"] == "rice_mean" and items[2]["grams"] == 228


def test_no_plate_means_confirm_everything():
    res = dict(SCAN, plate_found=False)
    assert all(it["needs_confirm"] for it in meal_scan.items_from_scan(res, TABLE))


def test_meal_carbs_range_and_rice_dominates():
    items = meal_scan.items_from_scan(SCAN, TABLE)
    t = meal_scan.meal_carbs(items, TABLE)
    # cơm 228 g x 28% = 63,8 g; khoai 84 g x 17% = 14,3 g
    assert 80 <= t["carb_g"] <= 90
    assert t["carb_low"] < t["carb_g"] < t["carb_high"]
    # cơm 228 g là mức trung bình (rice_mean) -> ±50%; các món khác ±30%
    rice = 228 * 0.28
    assert t["carb_low"] == pytest.approx(0.5 * rice + 0.7 * (t["carb_g"] - rice), abs=1.5)
    text = meal_scan.carb_text(t)
    assert "cơm trắng" in text and f"{t['carb_low']}–{t['carb_high']} g tinh bột" in text


def test_user_grams_narrow_the_range():
    model = meal_scan.meal_carbs([{"cls": "rice", "grams": 150, "gram_source": "model"}], TABLE)
    user = meal_scan.meal_carbs([{"cls": "rice", "grams": 150, "gram_source": "user"}], TABLE)
    assert model["carb_g"] == user["carb_g"] == 42
    assert user["carb_high"] - user["carb_low"] < model["carb_high"] - model["carb_low"]


def test_drink_is_listed_as_not_counted():
    t = meal_scan.meal_carbs([{"cls": "rice", "grams": 100}, {"cls": "drink", "grams": 300}], TABLE)
    assert t["uncounted"] == ["đồ uống"]
    assert "Chưa tính: đồ uống" in meal_scan.carb_text(t)


class FakeCalo(BaseHTTPRequestHandler):
    seen = []
    status = 200

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.seen.append((self.path, self.headers["Content-Type"], body))
        if self.status == 200:
            data = json.dumps(SCAN).encode()
        else:
            data = json.dumps({"error": "image_too_large", "message": "Ảnh quá lớn (tối đa 10 MB)."}).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def calo():
    FakeCalo.seen, FakeCalo.status = [], 200
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeCalo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_scan_posts_multipart_image(calo, monkeypatch):
    monkeypatch.setenv("DIACARE_CALO_URL", calo + "/")
    res = meal_scan.scan(b"\xff\xd8JPEGDATA", "khay.jpg")
    path, ctype, body = FakeCalo.seen[0]
    assert path == "/api/scan" and ctype.startswith("multipart/form-data; boundary=")
    assert b'name="image"; filename="khay.jpg"' in body and b"\xff\xd8JPEGDATA" in body
    assert res["total"]["grams"] == 483


def test_scan_error_message_is_passed_through(calo):
    FakeCalo.status = 413
    with pytest.raises(meal_scan.CaloKhayError, match="Ảnh quá lớn"):
        meal_scan.scan(b"x", url=calo)


def test_scan_service_down_says_how_to_start_it():
    with pytest.raises(meal_scan.CaloKhayError, match="chay_calo_khay.bat"):
        meal_scan.scan(b"x", url="http://127.0.0.1:9", timeout=3)



def test_manual_dishes_outside_canteen():
    """Món ngoài khay căng tin (người dùng tự thêm): tên không trùng món Calo Khay, khoảng tinh bột hợp lý."""
    manual = {c: r for c, r in TABLE.items() if r["match"].startswith("nhập tay")}
    assert {"pho_bo", "bun_cha", "banh_mi_thit", "chao_trang", "chuoi"} <= set(manual)
    names = [r["name"] for r in TABLE.values()]
    assert len(names) == len(set(names))                     # bảng chọn món ghép theo tên
    for cls, r in manual.items():
        assert 0 < r["carb"] <= r["carb_high"] <= 100 and r["kcal"] > 0, cls
    # một bát phở ~600 g: khoảng 60-77 g tinh bột; một ổ bánh mì thịt 150 g: 37-50 g
    pho = meal_scan.meal_carbs([{"cls": "pho_bo", "name": "phở bò (cả bát)", "grams": 600,
                                 "gram_source": "user"}], TABLE)
    assert 45 < pho["carb_low"] < pho["carb_g"] < pho["carb_high"] < 100


def test_rows_added_by_user_are_not_pending():
    from meal_ui import rows_to_items
    df = pd.DataFrame([{"Món": "phở bò (cả bát)", "Gram": 600, "Đúng món": None},
                       {"Món": "chuối", "Gram": 100, "Đúng món": False}])
    out, pending, unknown = rows_to_items(df, [], TABLE)
    assert pending == 0 and unknown == [] and [it["gram_source"] for it in out] == ["user", "user"]

def test_rows_to_items_marks_user_edits_and_pending():
    from meal_ui import rows_to_items, to_frame
    items = meal_scan.items_from_scan(SCAN, TABLE)
    df = to_frame(items, TABLE)
    assert not df.loc[1, "Đúng món"] and "có thể là: thịt xào súp lơ" in df.loc[1, "Ghi chú"]
    df.loc[2, "Gram"] = 150                       # sửa gram cơm
    df.loc[1, "Món"] = "thịt xào súp lơ"           # đổi món theo gợi ý
    df.loc[1, "Đúng món"] = True
    df = pd.concat([df, pd.DataFrame([{"Món": "đồ uống", "Gram": 300, "Đúng món": True}])], ignore_index=True)
    out, pending, unknown = rows_to_items(df, items, TABLE)
    assert pending == 0 and unknown == []
    # đổi tên món nhưng giữ gram mô hình -> vẫn sai số của mô hình; chỉ gram đã sửa và dòng thêm mới là người dùng
    assert [o["gram_source"] for o in out] == ["model", "model", "user", "model", "model", "model", "user"]
    assert out[1]["cls"] == "pork_broccoli" and out[2]["grams"] == 150


def test_deleting_a_row_keeps_other_rows_matched():
    from meal_ui import rows_to_items, to_frame
    items = meal_scan.items_from_scan(SCAN, TABLE)
    df = to_frame(items, TABLE).drop(index=0)    # xoá món nhận nhầm đầu tiên (data_editor giữ nhãn dòng)
    out, _, _ = rows_to_items(df, items, TABLE)
    assert [o["gram_source"] for o in out] == ["model"] * 5
    assert out[1]["cls"] == "rice" and out[1]["gram_method"] == "rice_mean"


def test_average_rice_grams_get_wide_range():
    measured = meal_scan.meal_carbs([{"cls": "rice", "grams": 228, "gram_method": "area"}], TABLE)
    mean = meal_scan.meal_carbs([{"cls": "rice", "grams": 228, "gram_method": "rice_mean"}], TABLE)
    assert mean["carb_g"] == measured["carb_g"] == 64
    assert mean["carb_low"] == 32 and mean["carb_high"] == 96   # ±50%
    assert measured["carb_high"] - measured["carb_low"] < mean["carb_high"] - mean["carb_low"]


def test_store_meals_encrypts_items(tmp_path, monkeypatch):
    monkeypatch.setenv("DIACARE_DB", str(tmp_path / "m.db"))
    store = open_store()
    pid = store.save_patient("An", {})
    t = meal_scan.meal_carbs([{"cls": "rice", "grams": 150, "gram_source": "user"}], TABLE)
    mid = store.add_meal(pid, "2026-11-24T12:00:00+07:00", "lunch", t["items"], t["carb_g"], t["carb_low"],
                         t["carb_high"], t["kcal"])
    raw = store.conn.execute("SELECT items_json FROM meals WHERE id = ?", (mid,)).fetchone()[0]
    assert "cơm" not in raw
    meals = store.list_meals(pid)
    assert meals[0]["items"][0]["name"] == "cơm trắng" and meals[0]["carb_g"] == 42
    store.delete_meal(mid, pid)
    assert store.list_meals(pid) == []


# ---- nối bữa ăn với đường huyết sau ăn ----
from datetime import datetime, timedelta  # noqa: E402

from diacare import journal  # noqa: E402

NOW = datetime(2026, 11, 24, 20, 0, tzinfo=journal.VN_TZ)


def _meal(hours_ago, carb, slot="lunch", mid=1):
    return {"id": mid, "eaten_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "slot": slot,
            "carb_g": carb, "carb_low": carb * 0.7, "carb_high": carb * 1.3,
            "items": [{"name": "cơm trắng", "grams": carb / 0.28}]}


def _glu(mmol, hours_ago, context="after_meal"):
    return {"kind": "glucose", "value": mmol * 18.0, "unit": "mmol/L", "context": context,
            "measured_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_pair_takes_first_reading_45min_to_3h_after():
    meals = [_meal(8, 80)]
    readings = [_glu(6.0, 8.5), _glu(11.5, 6.5), _glu(8.0, 6.0), _glu(7.0, 4.0)]
    p = meal_scan.pair_after_meal(meals, readings)[0]
    assert p["minutes"] == 90 and p["status"] == "above_target"
    assert meal_scan.after_meal_text(p) == "11,5 mmol/L sau 90 phút, cao hơn mục tiêu"


def test_unpaired_meal():
    p = meal_scan.pair_after_meal([_meal(8, 80)], [_glu(7.0, 8.2)])[0]
    assert p["reading"] is None and meal_scan.after_meal_text(p) == "chưa đo sau ăn"


def test_journal_lines_compare_high_and_ok_meals():
    meals = [_meal(24 * d + 8, carb, mid=d) for d, carb in enumerate([100, 95, 40, 45])]
    readings = [_glu(v, 24 * d + 6.5) for d, v in enumerate([12.0, 11.0, 8.0, 7.5])]
    lines = meal_scan.meal_journal_lines(meals, readings, now=NOW)
    text = "\n".join(lines)
    assert "4 bữa" in lines[0]
    assert "đường huyết sau ăn: 12,0 mmol/L sau 90 phút" in lines[1]   # bữa gần nhất, dù danh sách không theo thứ tự
    assert "Có đo sau ăn 4/4 bữa; 2 bữa đường huyết sau ăn cao hơn mục tiêu" in text
    assert "các bữa cao sau ăn trung bình khoảng 98 g tinh bột, các bữa trong mục tiêu khoảng 42 g" in text


def test_no_meals_no_lines():
    assert meal_scan.meal_journal_lines([], [_glu(7, 1)], now=NOW) == []


def test_journal_agent_adds_meal_lines_with_own_budget(tmp_path):
    from diacare.context import (ADVICE_TOKEN_BUDGET, JOURNAL_TOKEN_BUDGET, MEAL_TOKEN_BUDGET, build_context,
                                 estimate_tokens)
    from diacare.db import Store
    from diacare.state import State
    store = Store(tmp_path / "m.db")
    pid = store.save_patient("Lan", {})
    store.add_reading(pid, "glucose", 11.0 * 18, NOW - timedelta(hours=1), unit="mmol/L", context="after_meal")
    store.add_meal(pid, NOW - timedelta(hours=2, minutes=30), "lunch", [{"name": "cơm trắng", "grams": 200}],
                   56, 39, 73, 260)
    digest = journal.JournalAgent(store, now=NOW).collect(pid)
    assert digest["meal_lines"] and not any("Bữa" in line for line in digest["lines"])
    state = State(question="Trưa nay tôi ăn vậy có ổn không?", profile={}, patient_id=pid)
    state.journal = {**digest, "lines": digest["lines"] + ["- " + "x" * 300] * 5}
    text = build_context("advisor", state)["journal_text"]
    assert "Bữa gần nhất: bữa trưa" in text and "11,0 mmol/L sau 90 phút, cao hơn mục tiêu" in text
    assert estimate_tokens(text) <= JOURNAL_TOKEN_BUDGET + MEAL_TOKEN_BUDGET + ADVICE_TOKEN_BUDGET


def test_journal_agent_meals_only(tmp_path):
    from diacare.db import Store
    store = Store(tmp_path / "m.db")
    pid = store.save_patient("Lan", {})
    store.add_meal(pid, NOW - timedelta(hours=3), "lunch", [{"name": "cơm trắng", "grams": 200}], 56, 39, 73)
    digest = journal.JournalAgent(store, now=NOW).collect(pid)
    assert digest["lines"] == [] and "Chưa có lần đo" in digest["meal_lines"][-1]
    from diacare.context import build_context
    from diacare.state import State
    state = State(question="Bữa trưa của tôi thế nào?", profile={}, patient_id=pid)
    state.journal = digest
    assert "Bữa gần nhất: bữa trưa" in build_context("advisor", state)["journal_text"]


def test_annotate_draws_numbered_regions():
    """Ảnh xác nhận có khoanh vùng + số món, khớp cột # của bảng (người dùng thấy món nào nhận sai)."""
    import io

    from PIL import Image
    img = Image.new("RGB", (200, 100), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    items = [{"no": 1, "polygons": [[[10, 10], [60, 10], [60, 60], [10, 60]]]},
             {"no": 2, "polygons": []}]
    out = Image.open(io.BytesIO(meal_scan.annotate(buf.getvalue(), items, {"w": 100, "h": 50}))).convert("RGB")
    assert out.size == (200, 100)
    # vùng món 1 (toạ độ x2 vì ảnh gốc lớn gấp đôi ảnh Calo Khay xử lý) đã đổi màu, góc ngoài vùng giữ trắng
    assert out.getpixel((30, 30)) != (255, 255, 255) and out.getpixel((195, 95)) == (255, 255, 255)


def test_items_from_scan_keep_number_and_polygons():
    items = meal_scan.items_from_scan(SCAN, TABLE)
    assert [it["no"] for it in items] == list(range(1, len(items) + 1))
    assert all("polygons" in it for it in items)


# ---------- gợi ý ăn uống từ đường huyết sau ăn ----------

def _tray(hours_ago, rice_g, extra=(), slot="lunch", mid=1):
    """Bữa đã lưu như meal_ui lưu: món kèm tinh bột từng món (meal_carbs)."""
    items = [{"cls": "rice", "grams": rice_g}] + [{"cls": c, "grams": g} for c, g in extra]
    t = meal_scan.meal_carbs(items, TABLE)
    return {"id": mid, "eaten_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "slot": slot,
            "carb_g": t["carb_g"], "carb_low": t["carb_low"], "carb_high": t["carb_high"], "items": t["items"]}


def test_advice_names_the_dish_that_carries_the_carbs():
    meals = [_tray(30, 300, [("fried_tofu", 100)], mid=1), _tray(6, 280, [("water_spinach", 150)], mid=2),
             _tray(54, 120, [("water_spinach", 200), ("boiled_egg", 60)], mid=3)]
    readings = [_glu(11.6, 28.5), _glu(10.8, 4.5), _glu(7.9, 52.5)]
    a = meal_scan.meal_advice(meals, readings, TABLE, now=NOW)
    assert a["status"] == "high"
    top = a["limit"][0]
    assert top["name"] == "cơm trắng" and top["times"] == 2 and top["share"] >= 80
    assert top["suggest_grams"] == 190  # bớt một phần ba của khoảng 290 g, làm tròn 10 g
    text = " ".join(a["lines"])
    assert "Nên hạn chế: cơm trắng" in text and "2/3 bữa cao sau ăn" in text
    assert "rau muống" in text  # món ít tinh bột có trong bữa vẫn trong mục tiêu của chính người dùng
    assert "bữa trưa hôm nay" in a["headline"] and "10,8 mmol/L" in a["headline"]


def test_advice_one_high_meal_is_not_a_conclusion():
    a = meal_scan.meal_advice([_tray(6, 300)], [_glu(11.0, 4.5)], TABLE, now=NOW)
    assert a["status"] == "high" and any("chưa đủ để kết luận" in s for s in a["lines"])


def test_advice_never_says_cut_carbs_after_hypo():
    meals = [_tray(6, 300)]
    readings = [_glu(11.0, 4.5), _glu(3.4, 2, context="before_meal")]
    a = meal_scan.meal_advice(meals, readings, TABLE, now=NOW)
    assert a["status"] == "hypo" and not a["limit"]
    assert "không gợi ý ăn bớt" in a["headline"]
    assert not any("hạn chế" in s for s in a["lines"])


def test_advice_asks_to_measure_after_meals_first():
    a = meal_scan.meal_advice([_tray(6, 200)], [_glu(6.0, 10, context="fasting")], TABLE, now=NOW)
    assert a["status"] == "need_after" and "2 giờ sau" in a["headline"] and not a["limit"]
    assert meal_scan.meal_advice([], [], TABLE, now=NOW)["status"] == "no_meals"


def test_advice_all_in_target_keeps_current_eating():
    a = meal_scan.meal_advice([_tray(6, 150, [("cabbage", 150)])], [_glu(7.5, 4.5)], TABLE, now=NOW)
    assert a["status"] == "all_ok" and not a["limit"] and "bắp cải luộc" in " ".join(a["lines"])


def test_advisor_sees_precomputed_advice(tmp_path):
    from diacare.context import build_context
    from diacare.db import Store
    from diacare.state import State
    store = Store(tmp_path / "m.db")
    pid = store.save_patient("Lan", {})
    for hours, rice, mmol in ((30, 300, 11.6), (6, 280, 10.8)):
        m = _tray(hours, rice, [("fried_tofu", 100)])
        store.add_meal(pid, m["eaten_at"], "lunch", m["items"], m["carb_g"], m["carb_low"], m["carb_high"], 400)
        store.add_reading(pid, "glucose", mmol * 18, NOW - timedelta(hours=hours - 1.5), unit="mmol/L",
                          context="after_meal")
    digest = journal.JournalAgent(store, now=NOW).collect(pid)
    assert digest["advice_lines"][0].startswith("- Gợi ý ăn uống đã tính sẵn")
    state = State(question="Hôm nay tôi nên ăn gì?", profile={}, patient_id=pid)
    state.journal = digest
    text = build_context("advisor", state)["journal_text"]
    assert "Nên hạn chế: cơm trắng" in text and "Thử bớt còn khoảng" in text
