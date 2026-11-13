"""Ba màn hình cho người bệnh đã chẩn đoán ĐTĐ típ 2: Hôm nay, Nhật ký, Tái khám (dùng trong app.py)."""
from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from diacare import journal
from diacare.labs import classify
from diacare.memory import has_diagnosis
from diacare.visit_report import build_visit_pdf, glucose_chart_png

UNITS = ["mmol/L", "mg/dL"]
PERIODS = {7: "7 ngày", 14: "14 ngày", 30: "30 ngày", 90: "90 ngày"}


def _guess_context(now):
    h = now.hour
    if 4 <= h < 9:
        return "fasting"
    if 21 <= h or h < 4:
        return "bedtime"
    return "before_meal"


def _when(prefix):
    """Ô chọn ngày, giờ đo (mặc định là bây giờ, giờ Việt Nam); trả về datetime có múi giờ."""
    now = journal.now_vn()
    c1, c2 = st.columns(2)
    d = c1.date_input("Ngày đo", value=now.date(), max_value=now.date(), key=f"{prefix}_date", format="DD/MM/YYYY")
    t = c2.time_input("Giờ đo", value=time(now.hour, now.minute), key=f"{prefix}_time", step=300)
    return datetime.combine(d, t, tzinfo=journal.VN_TZ)


def _show_messages(items):
    for level, text in items:
        getattr(st, level)(text)


# ---- nhập liệu --------------------------------------------------------------

def _save_glucose(store, patient_id, prefix):
    """Chạy trước khi vẽ lại trang (callback), nên lời nhắc ở đầu trang Hôm nay thấy ngay lần đo vừa ghi."""
    ss = st.session_state
    value, unit, context = ss.get(f"{prefix}_value"), ss.get(f"{prefix}_unit"), ss.get(f"{prefix}_ctx")
    if value is None:
        ss[f"{prefix}_msg"] = [("warning", "Hãy nhập số đường huyết.")]
        return
    mgdl, err = journal.validate_glucose(value, unit)
    if err:
        ss[f"{prefix}_msg"] = [("error", err)]
        return
    when = datetime.combine(ss[f"{prefix}_date"], ss[f"{prefix}_time"], tzinfo=journal.VN_TZ)
    store.add_reading(patient_id, "glucose", mgdl, when, unit=unit, context=context,
                      note=(ss.get(f"{prefix}_note") or "").strip() or None)
    status = journal.classify_glucose(mgdl, context)
    level = {"in_target": "success", "above_target": "info", "below_target": "info"}.get(status, "warning")
    msgs = [(level, f"{journal.STATUS_ICON[status]} Đã lưu {journal.fmt_glucose(mgdl, unit)} "
                        f"({journal.CONTEXTS[context]}): {journal.STATUS_TEXT[status]}, "
                        f"{journal.target_text(context)}.")]
    if status in journal.ADVICE and prefix != "today":  # trang Hôm nay đã hiện cảnh báo này ở đầu trang
        msgs.append(journal.ADVICE[status])
    ss[f"{prefix}_msg"] = msgs


def glucose_form(store, patient_id, prefix="g"):
    with st.form(f"{prefix}_form", clear_on_submit=True):
        c1, c2 = st.columns([2, 1])
        c1.number_input("Đường huyết", min_value=0.0, max_value=700.0, value=None, step=0.1,
                        placeholder="vd 6,5", key=f"{prefix}_value")
        c2.selectbox("Đơn vị", UNITS, key=f"{prefix}_unit")
        st.selectbox("Đo lúc", list(journal.CONTEXTS), format_func=journal.CONTEXTS.get,
                     index=list(journal.CONTEXTS).index(_guess_context(journal.now_vn())), key=f"{prefix}_ctx")
        _when(prefix)
        st.text_input("Ghi chú (không bắt buộc)", placeholder="vd ăn phở sáng, quên thuốc tối qua",
                      key=f"{prefix}_note")
        st.form_submit_button("Lưu", type="primary", on_click=_save_glucose, args=(store, patient_id, prefix))
    _show_messages(st.session_state.pop(f"{prefix}_msg", []))


def bp_weight_forms(store, patient_id):
    c1, c2 = st.columns(2)
    with c1.form("bp_form", clear_on_submit=True):
        st.markdown("**Huyết áp**")
        a, b = st.columns(2)
        sys_ = a.number_input("Tâm thu", min_value=0, max_value=300, value=None, placeholder="vd 125", key="bp_sys")
        dia = b.number_input("Tâm trương", min_value=0, max_value=200, value=None, placeholder="vd 80", key="bp_dia")
        when = _when("bp")
        ok = st.form_submit_button("Lưu huyết áp")
    if ok:
        lo_s, hi_s = journal.PLAUSIBLE["systolic"]
        lo_d, hi_d = journal.PLAUSIBLE["diastolic"]
        if sys_ is None or dia is None or not (lo_s <= sys_ <= hi_s and lo_d <= dia <= hi_d) or dia >= sys_:
            c1.error("Số huyết áp chưa hợp lý (vd 125/80: tâm thu lớn hơn tâm trương).")
        else:
            store.add_reading(patient_id, "bp", sys_, when, value2=dia, unit="mmHg")
            status = journal.classify_bp(sys_, dia)
            c1.success(f"Đã lưu {sys_}/{dia} mmHg: {journal.STATUS_TEXT[status]} (mục tiêu dưới 130/80).")
            if status == "very_high":
                c1.error(journal.ADVICE["bp_very_high"][1])
    with c2.form("weight_form", clear_on_submit=True):
        st.markdown("**Cân nặng**")
        kg = st.number_input("Kg", min_value=0.0, max_value=300.0, value=None, step=0.1, placeholder="vd 62,5",
                             key="w_kg")
        when = _when("w")
        ok = st.form_submit_button("Lưu cân nặng")
    if ok:
        lo, hi = journal.PLAUSIBLE["weight"]
        if kg is None or not lo <= kg <= hi:
            c2.error("Cân nặng chưa hợp lý.")
        else:
            store.add_reading(patient_id, "weight", kg, when, unit="kg")
            c2.success(f"Đã lưu {kg:.1f} kg.")


# ---- Hôm nay ----------------------------------------------------------------

def render_today(store, patient_id):
    if patient_id is None:
        st.info("Hãy tạo hồ sơ ở thanh bên để bắt đầu.")
        return
    patient = store.get_patient(patient_id)
    now = journal.now_vn()
    st.subheader(f"Chào {patient['name']} · {now:%d/%m/%Y}")
    readings = store.list_readings(patient_id)
    _show_messages(journal.alerts(readings, now=now))
    _show_messages(journal.reminders(readings, store.get_appointment(patient_id), now=now))

    st.markdown("#### Ghi đường huyết")
    glucose_form(store, patient_id, prefix="today")
    readings = store.list_readings(patient_id)  # có thể vừa thêm

    st.markdown("#### 14 ngày qua")
    s = journal.summarize_glucose(readings, 14, now)
    glu = journal.glucose_rows(readings)
    c = st.columns(4)
    if glu:
        last = glu[-1]
        c[0].metric("Lần đo gần nhất", journal.fmt_glucose(last["value"]),
                    help=f"{journal.CONTEXTS.get(last['context'], '')}, "
                         f"{journal.to_vn(last['measured_at']):%H:%M %d/%m}")
    else:
        c[0].metric("Lần đo gần nhất", "-")
    c[1].metric("Trong mục tiêu", "-" if s["in_target_pct"] is None else f"{s['in_target_pct']}%",
                help="Tỉ lệ lần đo nằm trong mục tiêu chung ADA 2024")
    fasting = s["by_context"].get("fasting")
    c[2].metric("TB lúc đói", journal.fmt_glucose(fasting["mean_mgdl"]) if fasting else "-")
    hba1c = [r for r in store.list_labs(patient_id) if r["test"] == "hba1c"]
    c[3].metric("HbA1c gần nhất", f"{hba1c[-1]['value']:g}%" if hba1c else "-",
                help="Mục tiêu chung ADA 2024: dưới 7%, bác sĩ có thể đặt khác")
    if s["n"]:
        st.image(glucose_chart_png(journal.daily_series(readings, 14, now), 14, now), width="stretch")
    else:
        st.caption("Chưa có lần đo nào. Ghi lần đầu ở ô phía trên.")
    st.caption("Nhắc nhở chỉ hiện khi bạn mở ứng dụng. Mục tiêu tham khảo theo " + journal.SOURCE +
               "; bác sĩ có thể đặt mục tiêu riêng cho bạn.")


# ---- Nhật ký ----------------------------------------------------------------

def _glucose_table(readings):
    rows = []
    for r in reversed(journal.glucose_rows(readings)):
        status = journal.classify_glucose(r["value"], r["context"])
        rows.append({"id": r["id"], "Thời gian": journal.to_vn(r["measured_at"]).strftime("%d/%m %H:%M"),
                     "Đo lúc": journal.CONTEXTS.get(r["context"], r["context"]),
                     "mmol/L": round(journal.to_mmol(r["value"]), 1), "mg/dL": round(r["value"]),
                     "Đánh giá": journal.STATUS_ICON[status] + " " + journal.STATUS_TEXT[status],
                     "Ghi chú": r["note"] or ""})
    return rows


def _delete_box(store, patient_id, rows, key):
    if not rows:
        return
    with st.expander("Xoá một lần ghi nhầm"):
        rid = st.selectbox("Chọn lần ghi", [r["id"] for r in rows], key=f"{key}_del_sel",
                           format_func=lambda i: next(" · ".join(str(v) for k, v in r.items() if k != "id")
                                                      for r in rows if r["id"] == i))
        if st.button("Xoá", key=f"{key}_del_btn"):
            store.delete_reading(rid, patient_id)
            st.rerun()


def render_labs_panel(store, patient_id, import_fn):
    dates, labs = [], []
    for row in store.list_labs(patient_id):
        c = classify([{"test": row["test"], "value": row["value"], "unit": row["unit"]}])
        if c:  # classify bỏ giá trị không hợp lý, nên giữ ngày đi kèm từng dòng
            dates.append(journal.to_vn(row["created_at"]).strftime("%d/%m/%Y"))
            labs.append(c[0])
    diagnosed = has_diagnosis(store.list_memories(patient_id))

    def judge(r):
        if diagnosed and r["test"] == "hba1c":  # đã chẩn đoán: so với mục tiêu điều trị, không phải ngưỡng chẩn đoán
            return "đạt mục tiêu chung (< 7%)" if r["value_std"] < 7 else "cao hơn mục tiêu chung 7%"
        return r["level_text"]
    if labs:
        st.dataframe([{"Ngày nhập": d, "Xét nghiệm": r["label"], "Kết quả": f"{r['value_std']:g} {r['unit_std']}",
                       "Đối chiếu": judge(r)} for d, r in zip(dates, labs)][::-1], hide_index=True, width="stretch")
        a1c = [(d, r["value_std"]) for d, r in zip(dates, labs) if r["test"] == "hba1c"]
        if len(a1c) >= 2:
            st.caption(f"HbA1c: {a1c[-2][1]:g}% ({a1c[-2][0]}) → {a1c[-1][1]:g}% ({a1c[-1][0]}). "
                       "Mục tiêu chung dưới 7%.")
    else:
        st.caption("Chưa có kết quả. Chụp hoặc tải phiếu xét nghiệm lên, hoặc gõ thẳng vào ô dưới.")
    st.file_uploader("Ảnh hoặc file phiếu xét nghiệm (.png, .jpg, .pdf, .txt, .csv, .json)",
                     type=["txt", "csv", "json", "pdf", "png", "jpg", "jpeg"], key="lab_file")
    st.text_area("Hoặc gõ kết quả", key="lab_text", placeholder="HbA1c: 6.8 %\nGlucose lúc đói: 7.4 mmol/L")
    st.button("Nhập kết quả", key="lab_import", on_click=import_fn, args=(store, patient_id))
    msg = st.session_state.pop("lab_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])


def render_journal(store, patient_id, import_labs_fn):
    if patient_id is None:
        st.info("Hãy tạo hồ sơ ở thanh bên để bắt đầu.")
        return
    now = journal.now_vn()
    days = st.segmented_control("Khoảng thời gian", list(PERIODS), format_func=PERIODS.get, default=14,
                                key="journal_days") or 14
    t1, t2, t3 = st.tabs(["Đường huyết", "Huyết áp, cân nặng", "Xét nghiệm"])
    readings = store.list_readings(patient_id)
    with t1:
        with st.expander("Ghi thêm đường huyết"):
            glucose_form(store, patient_id, prefix="journal")
        readings = store.list_readings(patient_id)
        s = journal.summarize_glucose(readings, days, now)
        if not s["n"]:
            st.caption("Chưa có lần đo nào trong khoảng này.")
        else:
            st.image(glucose_chart_png(journal.daily_series(readings, days, now), days, now), width="stretch")
            st.caption(f"{s['n']} lần đo trong {s['days_measured']}/{days} ngày · {s['in_target_pct']}% trong mục "
                       f"tiêu · hạ đường huyết {s['hypo']} lần · rất cao {s['very_high']} lần")
            st.dataframe([{"Đo lúc": journal.CONTEXTS[c], "Số lần": v["n"],
                           "Trung bình": journal.fmt_glucose(v["mean_mgdl"]),
                           "Trong mục tiêu": f"{v['in_target_pct']}%"} for c, v in s["by_context"].items()],
                         hide_index=True)
        rows = _glucose_table(readings)
        if rows:
            st.dataframe(pd.DataFrame(rows).drop(columns="id"), hide_index=True, width="stretch")
        _delete_box(store, patient_id, rows, "glu")
    with t2:
        bp_weight_forms(store, patient_id)
        readings = store.list_readings(patient_id)
        bp = journal.summarize_bp(readings, days, now)
        w = journal.weight_change(readings, days, now)
        if bp:
            st.caption(f"Huyết áp trung bình {bp['systolic']:.0f}/{bp['diastolic']:.0f} mmHg qua {bp['n']} lần đo; "
                       f"{bp['above_target']} lần từ 130/80 trở lên.")
        if w:
            st.caption(f"Cân nặng {w['first']:.1f} → {w['last']:.1f} kg ({w['delta']:+.1f} kg).")
        start = now.date() - timedelta(days=days - 1)
        other = [r for r in readings if r["kind"] in ("bp", "weight") and journal._day(r) >= start]
        if other:
            df = pd.DataFrame([{"Thời gian": journal.to_vn(r["measured_at"]).replace(tzinfo=None),
                                "Tâm thu": r["value"] if r["kind"] == "bp" else None,
                                "Tâm trương": r["value2"] if r["kind"] == "bp" else None,
                                "Cân nặng (kg)": r["value"] if r["kind"] == "weight" else None} for r in other])
            if df["Tâm thu"].notna().any():
                st.line_chart(df.dropna(subset=["Tâm thu"]), x="Thời gian", y=["Tâm thu", "Tâm trương"], height=200)
            if df["Cân nặng (kg)"].notna().any():
                st.line_chart(df.dropna(subset=["Cân nặng (kg)"]), x="Thời gian", y="Cân nặng (kg)", height=200)
            rows = [{"id": r["id"], "Thời gian": journal.to_vn(r["measured_at"]).strftime("%d/%m %H:%M"),
                     "Loại": "huyết áp" if r["kind"] == "bp" else "cân nặng",
                     "Giá trị": f"{r['value']:.0f}/{r['value2']:.0f} mmHg" if r["kind"] == "bp"
                     else f"{r['value']:.1f} kg"} for r in reversed(other)]
            _delete_box(store, patient_id, rows, "bpw")
    with t3:
        render_labs_panel(store, patient_id, import_labs_fn)
        st.caption("Phiếu xét nghiệm được đối chiếu với ngưỡng tham khảo ADA 2024, không phải chẩn đoán.")


# ---- Tái khám ---------------------------------------------------------------

def _make_pdf(store, patient_id):
    days = st.session_state.get("visit_days", 28)
    st.session_state["visit_pdf"] = (patient_id, build_visit_pdf(store, patient_id, days=days))


def render_visit(store, patient_id):
    if patient_id is None:
        st.info("Hãy tạo hồ sơ ở thanh bên để bắt đầu.")
        return
    now = journal.now_vn()
    appt = store.get_appointment(patient_id)
    st.markdown("#### Lịch tái khám")
    with st.form("appt_form"):
        c1, c2 = st.columns([1, 2])
        default = datetime.fromisoformat(appt["date"]).date() if appt else now.date() + timedelta(days=30)
        d = c1.date_input("Ngày", value=default, key="appt_date", format="DD/MM/YYYY")
        place = c2.text_input("Nơi khám", value=(appt or {}).get("place") or "", placeholder="vd Bệnh viện Bạch Mai",
                              key="appt_place")
        if st.form_submit_button("Lưu lịch"):
            store.set_appointment(patient_id, d.isoformat(), place.strip() or None)
            st.rerun()
    if appt:
        left = (datetime.fromisoformat(appt["date"]).date() - now.date()).days
        st.caption(f"Lịch hiện tại: {appt['date'][8:10]}/{appt['date'][5:7]}/{appt['date'][:4]}"
                   + (f" tại {appt['place']}" if appt.get("place") else "")
                   + (f" · còn {left} ngày" if left > 0 else " · hôm nay" if left == 0 else " · đã qua"))

    st.markdown("#### Câu hỏi muốn hỏi bác sĩ")
    st.caption("Ghi lại ngay khi nghĩ ra; tới hôm khám các câu này nằm sẵn trong bản tóm tắt.")
    for q in store.list_doctor_questions(patient_id):
        c1, c2 = st.columns([6, 1])
        c1.write("• " + q["text"])
        if c2.button("Đã hỏi", key=f"q_done_{q['id']}"):
            store.mark_doctor_question(q["id"])
            st.rerun()
    with st.form("question_form", clear_on_submit=True):
        text = st.text_input("Câu hỏi mới", placeholder="vd Sáng hay bị hạ đường huyết, có cần đổi giờ uống thuốc?",
                             key="q_text")
        if st.form_submit_button("Thêm") and text.strip():
            store.add_doctor_question(patient_id, text)
            st.rerun()

    st.markdown("#### Bản tóm tắt mang đi khám")
    st.caption("Một trang A4: đường huyết theo thời điểm đo, biểu đồ, huyết áp, cân nặng, xét nghiệm, thuốc, câu hỏi. "
               "In ra hoặc mở trên điện thoại cho bác sĩ xem.")
    st.segmented_control("Tóm tắt", [14, 28, 90], format_func=lambda d: f"{d} ngày", default=28, key="visit_days",
                         label_visibility="collapsed")
    st.button("Tạo bản tóm tắt", key="visit_make", on_click=_make_pdf, args=(store, patient_id), type="primary")
    pdf = st.session_state.get("visit_pdf")
    if pdf and pdf[0] == patient_id:
        st.download_button("Tải PDF", pdf[1], file_name=f"tom_tat_tai_kham_{now:%Y%m%d}.pdf",
                           mime="application/pdf", key="visit_download")
