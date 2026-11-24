# -*- coding: utf-8 -*-
"""Chụp ảnh các phần mới của giao diện web ở V4.9 cho báo cáo: trợ lý chủ động hỏi (thẻ xác nhận số đo), trang Bữa
ăn (ảnh khay cơm qua Calo Khay, thẻ xác nhận món), lời nhắc Q-learning có 👍/👎 ở trang Hôm nay.

Cần API ở http://localhost:8604, web ở http://localhost:3000 và dịch vụ Calo Khay ở cổng 8010 (chay_calo_khay.bat).
Không gọi LLM. Script tự tạo một tài khoản thử với mật khẩu ngẫu nhiên (không dùng lại), nên chạy trên DB nháp.
    python docs/report/shots_web_v49.py [api_url] [web_url] [anh_khay.jpg]
"""
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8604"
WEB = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:3000"
TRAY = Path(sys.argv[3] if len(sys.argv) > 3 else "D:/CVision/Final_Project_Digital_Image_Processing/examples/B_212.jpg")
FIGS = Path(__file__).resolve().parent / "figs"
VN = timezone(timedelta(hours=7))

c = httpx.Client(base_url=API, timeout=120)
r = c.post("/auth/register", json={"email": f"baocao-{secrets.token_hex(4)}@example.test",
                                   "password": secrets.token_urlsafe(16), "name": "Lan"})
r.raise_for_status()
token = r.json()["access_token"]
c.headers["Authorization"] = f"Bearer {token}"
pid = c.post("/patients", json={"name": "Cô Lan", "diagnosed": True}).raise_for_status().json()["id"]

# nhật ký tới hôm qua (hôm nay chưa đo -> trợ lý hỏi "chưa thấy số đường huyết nào")
now = datetime.now(VN)
for d, v in [(5, 7.0), (4, 7.4), (3, 7.9), (2, 8.1), (1, 8.4)]:
    c.post(f"/patients/{pid}/readings/glucose", json={
        "value": v, "context": "fasting",
        "measured_at": (now - timedelta(days=d)).replace(hour=6, minute=30).isoformat()}).raise_for_status()
lunch = (now - timedelta(days=1)).replace(hour=12, minute=0)
c.post(f"/patients/{pid}/meals", json={"slot": "lunch", "eaten_at": lunch.isoformat(), "items": [
    {"cls": "rice", "grams": 250}, {"cls": "braised_fish", "grams": 90, "model_grams": 90, "gram_method": "area"},
    {"cls": "water_spinach", "grams": 80}]}).raise_for_status()
c.post(f"/patients/{pid}/readings/glucose", json={"value": 11.2, "context": "after_meal",
       "measured_at": (lunch + timedelta(minutes=95)).isoformat()}).raise_for_status()
c.post(f"/patients/{pid}/meals", json={"slot": "breakfast", "items": [{"cls": "pho_bo", "grams": 600}],
       "eaten_at": (now - timedelta(days=1)).replace(hour=7, minute=15).isoformat()}).raise_for_status()

def split_two_columns(path):
    """Ảnh cả trang Bữa ăn rất dài: cắt ở một hàng nền trống gần giữa rồi ghép hai nửa cạnh nhau cho vừa trang A4."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    a = np.asarray(im).astype(int)
    cut = min(range(h // 2 - 400, h // 2 + 400), key=lambda y: a[y].std(axis=0).sum())
    top, bot = im.crop((0, 0, w, cut)), im.crop((0, cut, w, h))
    out = Image.new("RGB", (2 * w + 40, max(top.size[1], bot.size[1])), (255, 255, 255))
    out.paste(top, (0, 0))
    out.paste(bot, (w + 40, 0))
    out.save(path)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    ctx = b.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2, locale="vi-VN",
                        color_scheme="light")
    ctx.add_init_script(f"localStorage.setItem('diacare.token', {token!r});"
                        f"localStorage.setItem('diacare.patient', '{pid}');")
    page = ctx.new_page()
    # ảnh cả trang: bỏ nút Next.js dev, thanh điều hướng và ô soạn tin nằm cuối trang thay vì cố định
    STYLE = ("nextjs-portal{display:none!important} .nav,.composer,.topbar{position:static!important}"
             " .chat{padding-bottom:0!important}")

    def save(name, full=True):
        page.add_style_tag(content=STYLE)
        time.sleep(1.0)
        page.screenshot(path=str(FIGS / name), full_page=full)
        print(name)

    # 1. trợ lý chủ động hỏi -> trả lời bằng chữ số đọc -> thẻ xác nhận (chưa lưu)
    page.goto(WEB + "/chat")
    page.get_by_text("Lời nhắc hôm nay").first.wait_for(timeout=60000)
    page.get_by_label("Câu hỏi").fill("sáu phẩy tám lúc đói")
    page.get_by_label("Câu hỏi").press("Enter")
    page.get_by_text("Mình ghi vào nhật ký như thế này nhé?").wait_for(timeout=30000)
    save("c9_web_hoi_the.png")
    page.get_by_role("button", name="Lưu vào nhật ký").click()
    page.get_by_text("Mình đã ghi").wait_for(timeout=30000)
    save("c9_web_hoi_luu.png")

    # 2. trang Bữa ăn: ảnh khay cơm -> Calo Khay nhận diện -> thẻ xác nhận món, khoảng tinh bột
    page.goto(WEB + "/meals")
    page.get_by_text("Các bữa đã ghi").wait_for(timeout=60000)
    page.get_by_label("Hoặc chọn ảnh có sẵn").set_input_files(str(TRAY))
    page.get_by_role("button", name="Nhận diện món").click()
    page.get_by_text("Kiểm tra lại các món").wait_for(timeout=120000)
    page.get_by_text("g tinh bột").first.wait_for(timeout=30000)
    save("c9_web_bua_an.png")
    split_two_columns(FIGS / "c9_web_bua_an.png")

    # 3. trang Hôm nay: lời nhắc Q-learning kèm 👍/👎 (chụp riêng khung lời nhắc)
    page.goto(WEB + "/today")
    nudge = page.get_by_role("note").filter(has_text="Lời nhắc hôm nay")
    nudge.wait_for(timeout=60000)
    page.add_style_tag(content=STYLE)
    time.sleep(0.8)
    nudge.screenshot(path=str(FIGS / "c9_web_loi_nhac.png"))
    print("c9_web_loi_nhac.png")
    b.close()
