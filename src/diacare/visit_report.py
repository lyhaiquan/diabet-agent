"""Bản tóm tắt 1 trang mang đi tái khám: đường huyết, huyết áp, cân nặng, xét nghiệm, thuốc, câu hỏi cho bác sĩ.

Dữ liệu do người bệnh tự ghi, so với mục tiêu chung ADA 2024 (xem journal.py). Phông DejaVu Sans đi kèm
matplotlib được nhúng vào PDF vì phông chuẩn Helvetica của PDF không có dấu tiếng Việt.
"""
import io
from datetime import timedelta
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from diacare import journal  # noqa: E402
from diacare.labs import LABELS as LAB_LABELS, classify  # noqa: E402

FONT, FONT_BOLD = "DejaVuSans", "DejaVuSans-Bold"


def collect(store, patient_id, days=28, now=None):
    """Gom dữ liệu của một người bệnh cho bản tóm tắt (tách khỏi phần vẽ để kiểm thử)."""
    now = journal.to_vn(now or journal.now_vn())
    patient = store.get_patient(patient_id)
    readings = store.list_readings(patient_id)
    labs = []
    for r in store.list_labs(patient_id):
        c = classify([{"test": r["test"], "value": r["value"], "unit": r["unit"]}])
        if c:
            labs.append(dict(c[0], date=journal.to_vn(r["created_at"]).date()))
    meds = [m["content"] for m in store.list_memories(patient_id) if m["kind"] == "medication"]
    conditions = [m["content"] for m in store.list_memories(patient_id) if m["kind"] in ("diagnosis", "condition")]
    return {
        "name": patient["name"] if patient else f"#{patient_id}",
        "now": now, "days": days,
        "start": now.date() - timedelta(days=days - 1),
        "glucose": journal.summarize_glucose(readings, days, now),
        "compare": journal.compare_periods(readings, days, now),
        "series": journal.daily_series(readings, days, now),
        "bp": journal.summarize_bp(readings, days, now),
        "weight": journal.weight_change(readings, days, now),
        "labs": labs[-8:],
        "medications": meds,
        "conditions": conditions,
        "questions": [q["text"] for q in store.list_doctor_questions(patient_id)],
        "appointment": store.get_appointment(patient_id),
    }


def glucose_chart_png(series, days, now, width=7.2, height=2.3):
    """Biểu đồ đường huyết theo ngày (mmol/L), dải mục tiêu trước ăn tô xanh, ngưỡng sau ăn và hạ đường huyết."""
    fig, ax = plt.subplots(figsize=(width, height), dpi=150)
    start = now.date() - timedelta(days=days - 1)
    ax.axhspan(journal.to_mmol(journal.PRE_MEAL_TARGET[0]), journal.to_mmol(journal.PRE_MEAL_TARGET[1]),
               color="#2e7d32", alpha=0.10, label="mục tiêu trước ăn 4,4–7,2")
    ax.axhline(journal.to_mmol(journal.POST_MEAL_MAX), color="#ef6c00", ls="--", lw=0.8, label="sau ăn < 10,0")
    ax.axhline(journal.to_mmol(journal.HYPO_1), color="#1565c0", ls=":", lw=0.8, label="hạ đường huyết < 3,9")
    marker = {"fasting": "o", "before_meal": "o", "after_meal": "^", "bedtime": "s", "random": "D"}
    names = {"fasting": "lúc đói", "before_meal": "trước ăn", "after_meal": "sau ăn", "bedtime": "trước ngủ",
             "random": "bất kỳ"}
    for ctx in journal.CONTEXTS:
        pts = [(t.replace(tzinfo=None), journal.to_mmol(v)) for t, v, c in series if c == ctx]
        if pts:
            ax.plot(*zip(*pts), marker[ctx], ms=4, label=names[ctx], alpha=0.85)
    ax.set_xlim(start, now.date() + timedelta(days=1))
    vals = [journal.to_mmol(v) for _, v, _ in series]
    ax.set_ylim(min([2.5] + [v - 0.5 for v in vals]), max([12.0] + [v + 1.0 for v in vals]))
    ax.set_ylabel("mmol/L", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m"))
    # chú thích đặt trên khung vẽ để không che điểm đo
    ax.legend(fontsize=6, ncol=8, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False,
              handletextpad=0.3, columnspacing=0.9)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _register_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    regular = font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans"))
    bold = font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight="bold"))
    pdfmetrics.registerFont(TTFont(FONT, regular))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, bold))


def _g(mgdl):
    return journal.fmt_glucose(mgdl).replace(" mmol/L", "")


def render_pdf(data):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    body = ParagraphStyle("b", fontName=FONT, fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7, leading=9, textColor=colors.HexColor("#555555"))
    h1 = ParagraphStyle("h1", fontName=FONT_BOLD, fontSize=13, leading=16, spaceAfter=2)
    h2 = ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=9.5, leading=12, spaceBefore=5, spaceAfter=2)

    def table(rows, widths):
        t = Table(rows, colWidths=widths)
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), 7.8), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#bbbbbb")),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        return t

    now, g = data["now"], data["glucose"]
    story = [Paragraph("Tóm tắt tự theo dõi đái tháo đường giữa hai lần khám", h1),
             Paragraph(f"Người bệnh: <b>{escape(data['name'])}</b> · Giai đoạn: {data['start']:%d/%m/%Y} – "
                       f"{now:%d/%m/%Y} ({data['days']} ngày) · Lập ngày {now:%d/%m/%Y %H:%M}", body)]
    appt = data.get("appointment")
    if appt:
        story.append(Paragraph(f"Lịch tái khám: {appt['date'][8:10]}/{appt['date'][5:7]}/{appt['date'][:4]}"
                               + (f" tại {escape(appt['place'])}" if appt.get("place") else ""), body))
    if data["conditions"]:
        story.append(Paragraph("Chẩn đoán, bệnh kèm (người bệnh tự khai): " + escape("; ".join(data["conditions"])), body))

    story.append(Paragraph("1. Đường huyết tự đo (mmol/L)", h2))
    if g["n"]:
        rows = [["Thời điểm đo", "Số lần", "Trung bình", "Thấp nhất – cao nhất", "Trong mục tiêu"]]
        for ctx, v in g["by_context"].items():
            rows.append([journal.CONTEXTS[ctx], v["n"], _g(v["mean_mgdl"]),
                         f"{_g(v['min_mgdl'])} – {_g(v['max_mgdl'])}", f"{v['in_target_pct']}%"])
        story.append(table(rows, [4.3 * cm, 1.4 * cm, 2.0 * cm, 3.9 * cm, 2.7 * cm]))
        line = (f"Tổng {g['n']} lần đo trong {g['days_measured']}/{data['days']} ngày; {g['in_target_pct']}% trong "
                f"mục tiêu. Hạ đường huyết (&lt; 3,9): <b>{g['hypo']}</b> lần. Rất cao (≥ 13,9): "
                f"<b>{g['very_high']}</b> lần.")
        cmp_ = data.get("compare")
        if cmp_:
            line += (f" Trung bình lúc đói/trước ăn {_g(cmp_['current_mgdl'])}, kỳ trước {_g(cmp_['previous_mgdl'])} "
                     f"({'+' if cmp_['delta_mgdl'] >= 0 else '−'}{_g(abs(cmp_['delta_mgdl']))}).")
        story += [Spacer(1, 3), Paragraph(line, body), Spacer(1, 3),
                  Image(io.BytesIO(glucose_chart_png(data["series"], data["days"], now)),
                        width=17.5 * cm, height=5.6 * cm)]
    else:
        story.append(Paragraph("Chưa có lần đo nào trong giai đoạn này.", body))

    story.append(Paragraph("2. Huyết áp và cân nặng", h2))
    bp, w = data["bp"], data["weight"]
    parts = []
    if bp:
        parts.append(f"Huyết áp trung bình {bp['systolic']:.0f}/{bp['diastolic']:.0f} mmHg ({bp['n']} lần đo, "
                     f"{bp['above_target']} lần từ 130/80 trở lên).")
    if w:
        parts.append(f"Cân nặng {w['first']:.1f} → {w['last']:.1f} kg ({w['delta']:+.1f} kg, {w['n']} lần cân).")
    story.append(Paragraph(" ".join(parts) or "Chưa ghi.", body))

    story.append(Paragraph("3. Xét nghiệm đã nhập", h2))
    if data["labs"]:
        rows = [["Ngày nhập", "Xét nghiệm", "Kết quả"]] + [
            [f"{r['date']:%d/%m/%Y}", LAB_LABELS[r["test"]], f"{r['value_std']:g} {r['unit_std']}"]
            for r in data["labs"]]
        story.append(table(rows, [2.6 * cm, 9.5 * cm, 3 * cm]))
    else:
        story.append(Paragraph("Chưa nhập.", body))

    story.append(Paragraph("4. Thuốc đang dùng (người bệnh tự khai)", h2))
    story.append(Paragraph(escape("; ".join(data["medications"])) or "Chưa ghi.", body))
    story.append(Paragraph("5. Câu hỏi muốn hỏi bác sĩ", h2))
    if data["questions"]:
        for i, q in enumerate(data["questions"], 1):
            story.append(Paragraph(f"{i}. {escape(q)}", body))
    else:
        story.append(Paragraph("(chưa có)", body))
    story += [Spacer(1, 8), Paragraph(
        "Số liệu do người bệnh tự ghi tại nhà bằng máy đo cá nhân. Mục tiêu tham khảo theo " + journal.SOURCE +
        " cho người lớn không mang thai; bác sĩ có thể đặt mục tiêu riêng. Bản này không phải chẩn đoán "
        "và không thay thế ý kiến bác sĩ. Lập bằng DiaCare.", small)]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.3 * cm,
                      bottomMargin=1.2 * cm, title="Tóm tắt tái khám", author="DiaCare").build(story)
    return buf.getvalue()


def build_visit_pdf(store, patient_id, days=28, now=None):
    return render_pdf(collect(store, patient_id, days, now))
