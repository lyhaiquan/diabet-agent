# -*- coding: utf-8 -*-
"""Hinh Chuong 6: so do kien truc DiaCare-MAS va so do harness (ve bang matplotlib, khong nhap tay so lieu)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

FIGS = Path(__file__).resolve().parent / "figs"
plt.rcParams["font.family"] = "Segoe UI"

INK, MUTED, ACC, OK, LINE = "#2b2622", "#6f655d", "#c0562f", "#2f7d57", "#b9ada1"
FILL = {"agent": "#fffaf3", "hub": "#fdeee4", "data": "#eef4f8", "out": "#eef7f0", "io": "#f4f1ec"}


def box(ax, x, y, w, h, title, sub="", kind="agent", tsize=11):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=FILL[kind], ec=ACC if kind == "hub" else "#cbbfb3", lw=1.8 if kind == "hub" else 1.2))
    ax.text(x + w / 2, y + h * (0.63 if sub else 0.5), title, ha="center", va="center", fontsize=tsize,
            fontweight="bold", color=INK)
    if sub:
        ax.text(x + w / 2, y + h * 0.3, sub, ha="center", va="center", fontsize=8.3, color=MUTED)
    return (x, y, w, h)


def mid(b, side):
    x, y, w, h = b
    return {"l": (x, y + h / 2), "r": (x + w, y + h / 2), "t": (x + w / 2, y + h), "b": (x + w / 2, y)}[side]


def arrow(ax, p, q, color=ACC, style="-|>", lw=1.4, ls="-", rad=0.0, label=None, lpos=0.5, loff=(0, 0.12)):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=12, color=color, lw=lw, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))
    if label:
        x = p[0] + (q[0] - p[0]) * lpos + loff[0]
        y = p[1] + (q[1] - p[1]) * lpos + loff[1]
        ax.text(x, y, label, fontsize=7.8, color=MUTED, ha="center", style="italic")


def zone(ax, x, y, w, h, label):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.2", fc="none",
                                ec=LINE, lw=1.1, ls=(0, (5, 4))))
    ax.text(x + 0.15, y + h - 0.28, label, fontsize=8.5, color=MUTED, fontweight="bold")


def architecture():
    fig, ax = plt.subplots(figsize=(14.6, 9.3), dpi=200)
    ax.set_xlim(0, 14.6)
    ax.set_ylim(0, 9.3)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    zone(ax, 2.55, 1.3, 9.6, 6.5, "HARNESS (code của hệ, không phải mô hình)")
    q = box(ax, 0.2, 4.15, 1.9, 1.0, "Người dùng", "câu hỏi + hồ sơ", "io")
    o = box(ax, 5.85, 4.1, 2.9, 1.1, "Orchestrator", "điều phối tuần tự, ghi trace", "hub", 12)
    top = [("Memory", "trích & nhớ thông tin"), ("Lab", "ngưỡng ADA · OCR"),
           ("Predictor", "3 nguồn · hiệu chỉnh"), ("Retriever", "RAG · sbert"), ("Graph", "đồ thị tri thức")]
    bot = [("Nutrition", "bảng USDA"), ("RL", "học từ phản hồi"), ("Context", "cắt ngữ cảnh"),
           ("Advisor", "LLM qua Ollama"), ("Rules", "lọc an toàn, gắn cờ")]
    xs = [2.8, 4.65, 6.5, 8.35, 10.2]
    tb = [box(ax, x, 6.15, 1.65, 0.95, t, s) for x, (t, s) in zip(xs, top)]
    bb = [box(ax, x, 2.05, 1.65, 0.95, t, s) for x, (t, s) in zip(xs, bot)]
    for i, b in enumerate(tb):
        arrow(ax, mid(o, "t"), mid(b, "b"), label=str(i + 1), lpos=0.55, loff=(0.13, 0))
    for i, b in enumerate(bb):
        arrow(ax, mid(o, "b"), mid(b, "t"), label=str(i + 6), lpos=0.55, loff=(0.13, 0))
    arrow(ax, mid(q, "r"), mid(o, "l"), label="câu hỏi")

    # tai nguyen (ngoai harness): dat ngay tren / duoi agent dung no
    db = box(ax, 2.8, 8.2, 3.5, 0.85, "SQLite", "bệnh nhân · bộ nhớ · xét nghiệm · log", "data", 10)
    mdl = box(ax, 6.5, 8.2, 1.65, 0.85, "predictor_ms", "BRFSS · NHANES", "data", 10)
    kb = box(ax, 8.35, 8.2, 1.65, 0.85, "Kho tài liệu", "MedlinePlus · WHO", "data", 10)
    kg = box(ax, 10.2, 8.2, 1.65, 0.85, "Neo4j / networkx", "108 nút · PrimeKG", "data", 10)
    usda = box(ax, 2.8, 0.25, 1.65, 0.85, "USDA FDC", "bảng dinh dưỡng", "data", 10)
    pol = box(ax, 4.65, 0.25, 1.65, 0.85, "rl_policy · SQLite", "chính sách RL", "data", 10)
    llm = box(ax, 8.35, 0.25, 1.65, 0.85, "Ollama", "qwen2.5 7B / 14B", "data", 10)
    dash = dict(color=LINE, ls="--")
    arrow(ax, mid(tb[0], "t"), (3.625, 8.2), style="<|-|>", **dash)
    arrow(ax, mid(tb[1], "t"), (5.475, 8.2), style="<|-|>", **dash)
    arrow(ax, mid(mdl, "b"), mid(tb[2], "t"), **dash)
    arrow(ax, mid(kb, "b"), mid(tb[3], "t"), **dash)
    arrow(ax, mid(kg, "b"), mid(tb[4], "t"), **dash)
    arrow(ax, mid(bb[0], "b"), mid(usda, "t"), style="<|-|>", **dash)
    arrow(ax, mid(pol, "t"), mid(bb[1], "b"), **dash)
    arrow(ax, mid(bb[3], "b"), mid(llm, "t"), style="<|-|>", label="stream token", lpos=0.62, loff=(0.62, 0), **dash)

    out = box(ax, 12.45, 2.05, 2.0, 0.95, "Câu trả lời", "nháp + ghi chú + cờ", "out", 10)
    arrow(ax, mid(bb[4], "r"), mid(out, "l"), color=OK, label="bản cuối", loff=(0, 0.12))
    fig.savefig(FIGS / "c6_kien_truc.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def harness():
    """So do vong lap agent tong quat vs pipeline co dinh cua DiaCare."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), dpi=200)
    for ax in axes:
        ax.set_xlim(0, 6.4)
        ax.set_ylim(0, 4.6)
        ax.axis("off")
    a, b = axes
    a.set_title("(a) Vòng lặp agent tổng quát (kiểu ReAct)", fontsize=11, color=INK, loc="left")
    u = box(a, 0.1, 1.85, 1.3, 0.9, "Yêu cầu", "", "io")
    m = box(a, 2.35, 3.2, 1.9, 0.9, "Mô hình", "quyết định bước tiếp", "hub")
    t = box(a, 2.35, 0.5, 1.9, 0.9, "Gọi công cụ", "harness thực thi", "agent")
    f = box(a, 5.0, 1.85, 1.3, 0.9, "Kết quả", "", "out")
    arrow(a, mid(u, "r"), mid(m, "l"), rad=-0.15)
    arrow(a, mid(m, "b"), mid(t, "t"), rad=0.35, label="tool_use", lpos=0.5, loff=(0.55, 0))
    arrow(a, mid(t, "t"), mid(m, "b"), rad=0.35, label="kết quả quan sát", lpos=0.5, loff=(-0.75, 0))
    arrow(a, mid(m, "r"), mid(f, "l"), color=OK, rad=-0.15, label="không còn tool_use", lpos=0.5, loff=(0.75, 0.05))
    a.text(3.2, 0.05, "Số vòng không biết trước; mô hình tự chọn công cụ.", ha="center", fontsize=8.5, color=MUTED)

    b.set_title("(b) Pipeline có kiểm soát của DiaCare-MAS", fontsize=11, color=INK, loc="left")
    steps = ["Memory", "Lab", "Predictor", "Retriever", "Graph", "Nutrition", "RL", "Context", "Advisor", "Rules"]
    prev = None
    for i, s in enumerate(steps):
        x, y = 0.05 + (i % 5) * 1.28, 3.0 if i < 5 else 1.2
        bx = box(b, x, y, 1.08, 0.8, s, "LLM" if s == "Advisor" else "code", "hub" if s == "Advisor" else "agent", 9.5)
        if prev is not None:
            if i == 5:
                arrow(b, mid(prev, "b"), mid(bx, "t"))
            else:
                arrow(b, mid(prev, "r"), mid(bx, "l"))
        prev = bx
    b.text(3.2, 0.35, "Thứ tự cố định; chỉ 1 trong 10 bước gọi LLM. Rules luôn chạy sau cùng.", ha="center",
           fontsize=8.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(FIGS / "c6_harness.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    harness()
    print("ok")
