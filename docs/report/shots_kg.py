# -*- coding: utf-8 -*-
"""Chup khung "Do thi tri thuc da dung" (Playwright + Edge). App chay o che do demo voi DIACARE_KG=neo4j,
da co it nhat mot benh nhan. Vi du:  python docs/report/shots_kg.py http://localhost:8602"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8602"
FIGS = Path(__file__).resolve().parent / "figs"
QUESTION = "Tôi bị béo phì và trầm cảm thì có dễ bị tiểu đường không?"


def idle(page, t=60):
    time.sleep(1.0)
    end = time.time() + t
    while time.time() < end:
        if page.locator('[data-testid="stStatusWidget"]').count() == 0:
            return
        time.sleep(0.4)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    page = b.new_page(viewport={"width": 1280, "height": 1000}, device_scale_factor=2, locale="vi-VN",
                      color_scheme="light")
    page.goto(URL)
    page.wait_for_selector("text=DiaCare-MAS", timeout=120000)
    idle(page)
    page.get_by_placeholder("Nhập câu hỏi về phòng ngừa tiểu đường...").fill(QUESTION)
    page.keyboard.press("Enter")
    idle(page, 120)
    page.get_by_text("Đồ thị tri thức đã dùng").last.click()
    idle(page)
    time.sleep(2)
    chart = page.locator('[data-testid="stGraphVizChart"]').last
    chart.scroll_into_view_if_needed()
    chart.screenshot(path=str(FIGS / "c7_kg_subgraph.png"))
    # Khung cao hơn màn hình và ô chat ghim ở đáy sẽ che mất phần dưới: phóng cao khung nhìn rồi cắt
    # từ bảng cạnh tới hết câu Cypher.
    page.set_viewport_size({"width": 1280, "height": 3200})
    idle(page)
    panel = page.locator('[data-testid="stExpander"]').filter(has_text="Đồ thị tri thức đã dùng").last
    top = panel.locator('[data-testid="stDataFrame"]').bounding_box()
    code = panel.locator('[data-testid="stCode"]').bounding_box()
    box = panel.bounding_box()
    page.screenshot(path=str(FIGS / "c7_ui_kg_panel.png"),
                    clip={"x": box["x"], "y": top["y"] - 12, "width": box["width"],
                          "height": code["y"] + code["height"] - top["y"] + 24})
    b.close()
print("ok")
