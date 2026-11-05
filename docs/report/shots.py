# -*- coding: utf-8 -*-
"""Chup anh giao dien DiaCare-MAS cho Chuong 6 (Playwright + Edge, app chay o che do demo tai localhost:8600)."""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8600"
FIGS = Path(__file__).resolve().parent.parent / "figs"
LABS = "PHIẾU XÉT NGHIỆM\nHbA1c: 8.5 %\nGlucose lúc đói: 10.0 mmol/L\nNghiệm pháp dung nạp glucose 2h: 182 mg/dL"
QUESTION = "Dạo này tôi khát nước liên tục, đi tiểu nhiều, nước tiểu có kiến bâu. Kết quả xét nghiệm của tôi thế nào?"


def idle(page, t=60):
    """Doi Streamlit chay xong (bieu tuong 'Running' bien mat)."""
    time.sleep(1.0)
    end = time.time() + t
    while time.time() < end:
        if page.locator('[data-testid="stStatusWidget"]').count() == 0:
            return
        time.sleep(0.4)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    page = b.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=2, locale="vi-VN")
    page.goto(URL)
    page.wait_for_selector("text=DiaCare-MAS", timeout=120000)
    idle(page)
    sb = page.locator('[data-testid="stSidebar"]')
    sb.get_by_role("button", name="Nạp hồ sơ mẫu cao").click()
    idle(page)
    sb.get_by_label("Tên bệnh nhân").fill("Nguyễn Văn A")
    sb.get_by_role("button", name="Lưu hồ sơ").click()
    idle(page)
    sb.get_by_label("Hoặc dán nội dung phiếu xét nghiệm").fill(LABS)
    sb.get_by_role("button", name="Nhập kết quả").click()
    idle(page)
    sb.screenshot(path=str(FIGS / "c6_ui_sidebar.png"))

    page.get_by_placeholder("Nhập câu hỏi về phòng ngừa tiểu đường...").fill(QUESTION)
    page.keyboard.press("Enter")
    idle(page, 120)
    page.get_by_text("Agent đã làm gì").first.click()
    idle(page)
    msg = page.locator('[data-testid="stChatMessage"]').last
    msg.scroll_into_view_if_needed()
    msg.screenshot(path=str(FIGS / "c6_ui_chat.png"))

    page.get_by_text("Hoạt động agent", exact=True).click()
    idle(page)
    frame_el = page.locator('[data-testid="stIFrame"]')
    frame_el.scroll_into_view_if_needed()
    fr = frame_el.content_frame
    fr.locator("select").select_option("2")
    fr.locator("button.primary").click()
    time.sleep(2.6)
    frame_el.screenshot(path=str(FIGS / "c6_ui_flow_dang_chay.png"))
    fr.locator(".st").filter(has_text="Xong").wait_for(timeout=60000)
    time.sleep(0.5)
    frame_el.screenshot(path=str(FIGS / "c6_ui_flow_xong.png"))
    b.close()
print("ok")
