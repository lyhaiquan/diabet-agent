# -*- coding: utf-8 -*-
"""Chụp ảnh giao diện web Next.js cho báo cáo (mục 5.6).

Cần API ở http://localhost:8604 (nên dùng Ollama thật để câu trả lời có nghĩa) và web ở http://localhost:3000.
Script tự tạo một tài khoản thử với mật khẩu ngẫu nhiên (không dùng lại), ghi nhật ký 14 ngày, hỏi một câu,
rồi chụp các trang bằng Playwright + Edge ở khổ điện thoại.
    python docs/report/shots_web.py [api_url] [web_url]
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
FIGS = Path(__file__).resolve().parent / "figs"
VN = timezone(timedelta(hours=7))
QUESTION = "Mấy hôm nay đường huyết của tôi thế nào, tôi nên làm gì?"

c = httpx.Client(base_url=API, timeout=600)
email = f"baocao-{secrets.token_hex(4)}@example.test"
r = c.post("/auth/register", json={"email": email, "password": secrets.token_urlsafe(16), "name": "Lan"})
r.raise_for_status()
token = r.json()["access_token"]
c.headers["Authorization"] = f"Bearer {token}"
pid = c.post("/patients", json={"name": "Cô Lan", "diagnosed": True}).raise_for_status().json()["id"]

now = datetime.now(VN)
fasting = [8.4, 8.1, 7.9, 7.2, 7.4, 6.9, 7.0, 6.6, 7.1, 6.8, 7.3, 6.5, 6.9, 7.0]  # mới nhất trước
after = {0: 11.8, 1: 10.9, 2: 12.4, 4: 9.6, 6: 9.1, 8: 8.7, 10: 9.4, 12: 8.9}
for d, v in enumerate(fasting):
    day = now - timedelta(days=d)
    if d == 0 and now.hour < 7:
        continue
    c.post(f"/patients/{pid}/readings/glucose", json={
        "value": v, "context": "fasting", "measured_at": day.replace(hour=6, minute=30).isoformat()}).raise_for_status()
    if d in after and (d or now.hour >= 14):
        c.post(f"/patients/{pid}/readings/glucose", json={
            "value": after[d], "context": "after_meal",
            "measured_at": day.replace(hour=13, minute=30).isoformat()}).raise_for_status()
c.post(f"/patients/{pid}/readings/glucose", json={
    "value": 3.7, "context": "bedtime", "measured_at": (now - timedelta(days=5)).replace(hour=22).isoformat()})
for d, (s, di) in {1: (138, 84), 5: (132, 82), 9: (128, 79)}.items():
    c.post(f"/patients/{pid}/readings/bp", json={"systolic": s, "diastolic": di,
                                                 "measured_at": (now - timedelta(days=d)).isoformat()})
c.post(f"/patients/{pid}/readings/weight", json={"kg": 63.4, "measured_at": (now - timedelta(days=20)).isoformat()})
c.post(f"/patients/{pid}/readings/weight", json={"kg": 62.6, "measured_at": (now - timedelta(days=1)).isoformat()})
c.post(f"/patients/{pid}/labs", json={"text": "HbA1c: 7.4 %"})
c.put(f"/patients/{pid}/appointment", json={"date": (now + timedelta(days=5)).date().isoformat(),
                                             "place": "Bệnh viện Bạch Mai"})
c.post(f"/patients/{pid}/questions", json={"text": "Đường huyết sau ăn trưa hay cao, có cần đổi giờ uống thuốc không?"})
print("đang hỏi trợ lý (Ollama)...")
c.post(f"/patients/{pid}/chat", json={"question": QUESTION}).raise_for_status()

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    ctx = b.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2, locale="vi-VN",
                        color_scheme="light")
    ctx.add_init_script(f"localStorage.setItem('diacare.token', {token!r});"
                        f"localStorage.setItem('diacare.patient', '{pid}');")
    page = ctx.new_page()

    # Ảnh chụp cả trang: bỏ nút Next.js dev, cho thanh điều hướng và ô soạn tin nằm cuối trang thay vì cố định
    STYLE = ("nextjs-portal{display:none!important} .nav,.composer,.topbar{position:static!important}"
             " .chat{padding-bottom:0!important}")

    def shot(path, name, wait_text, full=True):
        page.goto(WEB + path)
        page.get_by_text(wait_text).first.wait_for(timeout=60000)
        page.add_style_tag(content=STYLE)
        time.sleep(1.2)
        page.screenshot(path=str(FIGS / name), full_page=full)
        print(name)

    shot("/today", "c8_web_homnay.png", "14 ngày qua")
    shot("/journal", "c8_web_nhatky.png", "Nhật ký")
    shot("/visit", "c8_web_taikham.png", "Tái khám")
    shot("/chat", "c8_web_tuvan.png", "Trọng tâm lần này")
    b.close()
