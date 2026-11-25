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
    top = [("Memory", "trích & nhớ"), ("Lab", "ngưỡng ADA · OCR"), ("Journal", "nhật ký 14 ngày"),
           ("Predictor", "3 nguồn · hiệu chỉnh"), ("Retriever", "RAG · sbert"), ("Graph", "đồ thị tri thức")]
    bot = [("Nutrition", "bảng USDA"), ("RL", "học từ phản hồi"), ("Context", "cắt ngữ cảnh"),
           ("Advisor", "LLM qua Ollama"), ("Rules", "lọc an toàn, gắn cờ")]
    xt = [2.7 + i * 1.55 for i in range(6)]
    xs = [2.8, 4.65, 6.5, 8.35, 10.2]
    tb = [box(ax, x, 6.15, 1.45, 0.95, t, s, tsize=10.5) for x, (t, s) in zip(xt, top)]
    bb = [box(ax, x, 2.05, 1.65, 0.95, t, s) for x, (t, s) in zip(xs, bot)]
    for i, b in enumerate(tb):
        arrow(ax, mid(o, "t"), mid(b, "b"), label=str(i + 1), lpos=0.55, loff=(0.13, 0))
    for i, b in enumerate(bb):
        arrow(ax, mid(o, "b"), mid(b, "t"), label=str(i + 7), lpos=0.55, loff=(0.13, 0))
    arrow(ax, mid(q, "r"), mid(o, "l"), label="câu hỏi")

    # tai nguyen (ngoai harness): dat ngay tren / duoi agent dung no
    db = box(ax, 2.7, 8.2, 4.55, 0.85, "SQLite", "bệnh nhân · nhật ký · bộ nhớ · xét nghiệm · log", "data", 10)
    mdl = box(ax, xt[3], 8.2, 1.45, 0.85, "predictor_ms", "BRFSS · NHANES", "data", 9.5)
    kb = box(ax, xt[4], 8.2, 1.45, 0.85, "Kho tài liệu", "MedlinePlus · WHO", "data", 9.5)
    kg = box(ax, xt[5], 8.2, 1.45, 0.85, "Neo4j / networkx", "108 nút · PrimeKG", "data", 9.5)
    usda = box(ax, 2.8, 0.25, 1.65, 0.85, "USDA FDC", "bảng dinh dưỡng", "data", 10)
    pol = box(ax, 4.65, 0.25, 1.65, 0.85, "rl_policy · SQLite", "chính sách RL", "data", 10)
    llm = box(ax, 8.35, 0.25, 1.65, 0.85, "Ollama", "qwen2.5 7B / 14B", "data", 10)
    dash = dict(color=LINE, ls="--")
    for b in tb[:2]:
        arrow(ax, mid(b, "t"), (mid(b, "t")[0], 8.2), style="<|-|>", **dash)
    arrow(ax, (mid(tb[2], "t")[0], 8.2), mid(tb[2], "t"), **dash)
    arrow(ax, mid(mdl, "b"), mid(tb[3], "t"), **dash)
    arrow(ax, mid(kb, "b"), mid(tb[4], "t"), **dash)
    arrow(ax, mid(kg, "b"), mid(tb[5], "t"), **dash)
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
    steps = ["Memory", "Lab", "Journal", "Predictor", "Retriever", "Graph",
             "Nutrition", "RL", "Context", "Advisor", "Rules"]
    prev = None
    for i, s in enumerate(steps):
        x, y = 0.05 + (i % 6) * 1.06, 3.0 if i < 6 else 1.2
        bx = box(b, x, y, 0.9, 0.8, s, "LLM" if s == "Advisor" else "code", "hub" if s == "Advisor" else "agent", 8.5)
        if prev is not None:
            if i == 6:
                arrow(b, mid(prev, "b"), mid(bx, "t"))
            else:
                arrow(b, mid(prev, "r"), mid(bx, "l"))
        prev = bx
    b.text(3.2, 0.35, "Thứ tự cố định; chỉ 1 trong 11 bước gọi LLM. Rules luôn chạy sau cùng.", ha="center",
           fontsize=8.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(FIGS / "c6_harness.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def deployment():
    """Các lớp triển khai: giao diện -> dịch vụ API -> pipeline agent; giọng nói và nhật ký đi qua API."""
    fig, ax = plt.subplots(figsize=(14.0, 6.4), dpi=200)
    ax.set_xlim(0, 14.0)
    ax.set_ylim(0, 6.4)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    web = box(ax, 0.2, 4.2, 2.9, 1.3, "Web Next.js", "điện thoại · máy tính · giọng nói", "io", 11)
    stl = box(ax, 0.2, 1.4, 2.9, 1.3, "Streamlit", "4 trang người dùng + nhà phát triển", "io", 11)
    zone(ax, 4.0, 0.5, 5.6, 5.5, "DỊCH VỤ API (FastAPI · src/api)")
    auth = box(ax, 4.3, 4.35, 2.4, 1.0, "Xác thực", "scrypt · JWT HS256", "agent", 10)
    jr = box(ax, 6.95, 4.35, 2.4, 1.0, "Nhật ký · Tái khám", "số đo · lịch · PDF", "agent", 10)
    chat = box(ax, 6.95, 2.65, 2.4, 1.0, "Chat", "JSON hoặc SSE", "hub", 10)
    asr = box(ax, 4.3, 2.65, 2.4, 1.0, "/transcribe", "PhoWhisper-small · CPU", "agent", 10)
    lab = box(ax, 4.3, 0.95, 2.4, 1.0, "Xét nghiệm", "văn bản · tệp · OCR", "agent", 10)
    fb = box(ax, 6.95, 0.95, 2.4, 1.0, "Phản hồi", "thích · không thích → RL", "agent", 10)
    pipe = box(ax, 10.5, 2.55, 3.2, 1.2, "Orchestrator", "11 agent (hình 2.1)", "hub", 12)
    db = box(ax, 10.5, 4.6, 3.2, 1.0, "SQLite (WAL)", "mỗi request một kết nối", "data", 10)
    llm = box(ax, 10.5, 0.6, 3.2, 1.0, "Ollama", "qwen2.5", "data", 10)
    arrow(ax, mid(web, "r"), (4.0, 4.85), label="HTTPS + Bearer", loff=(0, 0.14))
    arrow(ax, mid(stl, "r"), (10.5, 2.62), color=LINE, ls="--", label="Streamlit gọi thẳng trong tiến trình",
          lpos=0.36, loff=(0, 0.2))
    arrow(ax, mid(chat, "r"), mid(pipe, "l"))
    arrow(ax, mid(pipe, "t"), mid(db, "b"), style="<|-|>")
    arrow(ax, mid(pipe, "b"), mid(llm, "t"), style="<|-|>")
    arrow(ax, mid(jr, "r"), mid(db, "l"), color=LINE, ls="--")
    fig.savefig(FIGS / "c8_trien_khai.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


FILL["ext"] = "#f3eef8"   # dịch vụ ngoài hệ (Calo Khay, Kaggle)
FILL["side"] = "#f1f6ee"  # luồng ngoài pipeline tư vấn


def system_v49():
    """Kiến trúc toàn hệ ở V4.9: giao diện, lõi (pipeline tư vấn + các luồng không gọi LLM), tài nguyên, dịch vụ ngoài."""
    W, H = 16.4, 11.6
    fig, ax = plt.subplots(figsize=(W, H), dpi=200)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    dash = dict(color=LINE, ls="--")

    # ---- giao diện ----
    zone(ax, 2.2, 9.55, 14.0, 1.85, "GIAO DIỆN")
    user = box(ax, 0.15, 9.9, 1.75, 1.0, "Người dùng", "gõ · nói · chụp ảnh", "io", 10.5)
    st_ = box(ax, 2.45, 9.75, 3.6, 1.15, "Streamlit (src/app.py)", "chat gõ/nói · nút micro to · ảnh · 8 trang", "io", 10.5)
    web = box(ax, 6.6, 9.75, 2.75, 1.15, "Web Next.js (web/)", "5 trang · đọc to (trình duyệt)", "io", 10.5)
    cli = box(ax, 9.65, 9.75, 2.2, 1.15, "CLI / benchmark", "src/cli.py · eval", "io", 10.5)
    mcpc = box(ax, 12.2, 9.75, 3.8, 1.15, "Trợ lý AI khác (MCP)", "Claude Desktop, IDE...", "io", 10.5)
    arrow(ax, mid(user, "r"), mid(st_, "l"))
    api = box(ax, 6.6, 8.2, 2.75, 0.95, "API FastAPI (src/api)", "JWT · mỗi người chỉ thấy hồ sơ mình", "hub", 10)
    mcps = box(ax, 12.2, 8.2, 3.8, 0.95, "MCP server (mcp_server.py)", "6 công cụ tất định, không mở dữ liệu bệnh nhân", "agent", 10)
    arrow(ax, mid(web, "b"), mid(api, "t"), label="HTTP + token", lpos=0.75, loff=(0.75, 0))
    arrow(ax, mid(mcpc, "b"), mid(mcps, "t"), label="stdio JSON-RPC", lpos=0.75, loff=(0.85, 0))

    # ---- lõi ----
    zone(ax, 2.2, 2.35, 14.0, 5.55, "LÕI (src/diacare)")
    ax.text(2.45, 7.2, "Luồng ngoài pipeline (câu soạn sẵn, không gọi LLM)", fontsize=8.5, color=OK, fontweight="bold")
    side = [("Giọng nói", "PhoWhisper nghe → câu hỏi · Piper đọc lại"),
            ("Trợ lý chủ động hỏi", "checkin.py · thẻ xác nhận số đo"),
            ("Nhập xét nghiệm", "labs.py + OCR · ảnh, PDF, chữ"),
            ("Agent bữa ăn", "meal_scan.py · khoảng tinh bột")]
    sb = [box(ax, 2.45, 6.05 - i * 1.05, 3.6, 0.88, t, s, "side", 10.5) for i, (t, s) in enumerate(side)]

    orch = box(ax, 6.55, 6.2, 9.4, 0.95, "Orchestrator: pipeline tư vấn cho một câu hỏi",
               "chặn câu chào / ngoài phạm vi · lọc tài liệu bị chèn lệnh · ghi trace · bắt lỗi", "hub", 11.5)
    rowa = [("Memory", "trích & nhớ"), ("Lab", "ngưỡng ADA"), ("Journal", "nhật ký, bữa ăn"),
            ("Predictor", "predictor_ms"), ("Retriever", "kb/ · sbert"), ("Graph", "Neo4j/networkx"),
            ("Nutrition", "USDA FDC")]
    rowb = [("RL", "bandit, phản hồi"), ("Context", "ngân sách token"), ("Advisor", "LLM, stream"),
            ("Critic", "nguồn, con số"), ("Rules", "luật an toàn")]
    xa = [6.55 + i * 1.355 for i in range(7)]
    ra = [box(ax, x, 4.75, 1.25, 0.85, t, s, tsize=9.8) for x, (t, s) in zip(xa, rowa)]
    zone(ax, xa[3] - 0.08, 4.62, 4 * 1.355 + 0.03, 1.1, "")
    ax.text(xa[3], 5.78, "4 agent chỉ đọc: chạy song song", fontsize=7.8, color=MUTED, style="italic")
    ax.text(7.3, 5.78, "1–3: lần lượt", fontsize=7.8, color=MUTED, style="italic")
    for a, b in zip(ra[:3], ra[1:4]):
        arrow(ax, mid(a, "r"), mid(b, "l"), lw=1.1)
    xb = [6.55 + i * 1.6 for i in range(6)]
    rb = [box(ax, x, 3.2, 1.4, 0.85, t, s, tsize=10) for x, (t, s) in zip(xb, rowb)]
    ans = box(ax, xb[5], 3.2, 1.4, 0.85, "Câu trả lời", "+ cờ, nguồn", "out", 10)
    for a, b in zip(rb + [ans], rb[1:] + [ans]):
        arrow(ax, mid(a, "r"), mid(b, "l"), lw=1.1, color=OK if b is ans else ACC)
    ax.text(6.55, 2.6, "tuần tự; Rules luôn chạy cuối", fontsize=7.8,
            color=MUTED, style="italic")
    arrow(ax, (7.15, 6.2), (7.15, 5.62), color=ACC)
    ax.plot([15.3, 15.3, 7.25], [4.62, 4.36, 4.36], color=ACC, lw=1.4)
    arrow(ax, (7.25, 4.36), (7.25, 4.05), color=ACC)

    # vào lõi
    arrow(ax, (mid(sb[0], "t")[0], 9.75), mid(sb[0], "t"), label="âm thanh", lpos=0.45, loff=(0.45, 0))
    arrow(ax, (5.85, 9.75), (6.75, 7.15), label="trong tiến trình", lpos=0.5, loff=(-0.65, 0))
    arrow(ax, mid(api, "b"), (mid(api, "b")[0], 7.15))
    arrow(ax, mid(cli, "b"), (mid(cli, "b")[0], 7.15))
    arrow(ax, mid(sb[0], "r"), (6.55, mid(sb[0], "r")[1]))
    arrow(ax, (14.1, 8.2), (14.1, 7.15), **dash)
    ax.text(14.2, 7.6, "gọi thẳng Lab, Nutrition,\nGraph, Predictor, Retriever", fontsize=7.6, color=MUTED)

    # ---- tài nguyên và dịch vụ ngoài ----
    zone(ax, 0.1, 0.1, 16.2, 2.0, "TÀI NGUYÊN  ·  DỊCH VỤ NGOÀI (khung tím)")
    db = box(ax, 0.35, 0.3, 3.2, 1.15, "SQLite / PostgreSQL",
             "hồ sơ · nhật ký · bữa ăn · xét nghiệm\ntrí nhớ · log (chữ sức khoẻ mã hoá)", "data", 10)
    calo = box(ax, 3.8, 0.3, 2.75, 1.15, "Calo Khay :8010",
               "YOLO26s-seg + DINOv2 · 44 món\nservices/calo_khay · venv torch", "ext", 10)
    carb = box(ax, 6.75, 0.3, 1.7, 1.15, "Bảng tinh bột", "Nutrition5k\nUSDA FNDDS", "data", 9.5)
    llm = box(ax, 8.65, 0.3, 2.3, 1.15, "Ollama", "3B trên máy hoặc\n7B Kaggle T4 (đường hầm)", "ext", 10)
    box(ax, 11.15, 0.3, 1.55, 1.15, "predictor_ms", "BRFSS · NHANES\n(Predictor)", "data", 9.5)
    box(ax, 12.9, 0.3, 1.55, 1.15, "Kho tài liệu", "kb/ · ADA, WHO\n(Retriever)", "data", 9.5)
    box(ax, 14.65, 0.3, 1.55, 1.15, "Đồ thị tri thức", "108 nút\n(Graph)", "data", 9.5)

    arrow(ax, (3.6, mid(sb[3], "b")[1]), mid(calo, "t"), label="ảnh khay · HTTP", lpos=0.12, loff=(-0.85, 0), **dash)
    arrow(ax, (5.4, mid(sb[3], "b")[1]), mid(carb, "t"), **dash)
    for b in sb[1:]:
        arrow(ax, mid(b, "l"), (0.9, mid(b, "l")[1]), style="-", **dash)
    ax.plot([0.9, 0.9], [mid(sb[1], "l")[1], mid(sb[3], "l")[1]], color=LINE, ls="--", lw=1.4)
    arrow(ax, (0.9, mid(sb[3], "l")[1]), (0.9, 1.45), **dash)
    ax.text(0.98, 2.6, "ghi", fontsize=7.8, color=MUTED, style="italic")
    arrow(ax, mid(rb[2], "b"), (mid(llm, "t")[0] + 0.5, 1.45), style="<|-|>", label="stream token", lpos=0.3,
          loff=(0.6, 0), **dash)
    fig.savefig(FIGS / "c10_kien_truc_v49.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    harness()
    deployment()
    system_v49()
    print("ok")
