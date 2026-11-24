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
    assert len(TABLE) == 45
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
