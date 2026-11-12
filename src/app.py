import os

import matplotlib
import pandas as pd
import streamlit as st

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from diacare.factory import build_orchestrator, open_store  # noqa: E402
from diacare.flowviz import flow_html  # noqa: E402
from diacare.kg import subgraph_dot, subgraph_edges  # noqa: E402
from diacare.labs import (LABELS as LAB_LABELS, LabAgent, classify, parse_lab_file,  # noqa: E402
                          parse_lab_text, worst_level)
from diacare.memory import KIND_LABELS  # noqa: E402
from diacare.orchestrator import Orchestrator  # noqa: E402
from diacare.rules import BINARY_FEATURES, FEATURE_RANGES, SafeStream, risk_band, validate_profile  # noqa: E402
from diacare.samples import HIGH_RISK, LOW_RISK  # noqa: E402
from diacare.state import State  # noqa: E402
from diacare.typewriter import Typewriter  # noqa: E402

LABELS = {
    "HighBP": "huyết áp cao",
    "HighChol": "cholesterol cao",
    "CholCheck": "đã kiểm tra cholesterol trong 5 năm",
    "BMI": "chỉ số BMI",
    "Smoker": "từng hút ít nhất 100 điếu thuốc",
    "Stroke": "từng bị đột quỵ",
    "HeartDiseaseorAttack": "bệnh mạch vành hoặc nhồi máu cơ tim",
    "PhysActivity": "có vận động trong 30 ngày qua",
    "Fruits": "ăn trái cây hằng ngày",
    "Veggies": "ăn rau hằng ngày",
    "HvyAlcoholConsump": "uống rượu nhiều",
    "AnyHealthcare": "có bảo hiểm y tế",
    "NoDocbcCost": "không đi khám vì chi phí",
    "GenHlth": "sức khỏe chung từ 1 (rất tốt) đến 5 (kém)",
    "MentHlth": "số ngày sức khỏe tinh thần kém trong 30 ngày",
    "PhysHlth": "số ngày sức khỏe thể chất kém trong 30 ngày",
    "DiffWalk": "khó đi bộ hoặc leo cầu thang",
    "Sex": "giới tính",
    "Age": "nhóm tuổi 1-13",
    "Education": "trình độ học vấn 1-6",
    "Income": "thu nhập 1-8",
}
FIELDS = tuple(FEATURE_RANGES)
PAGES = ("Tư vấn", "Hoạt động agent", "Lịch sử", "Thống kê")


@st.cache_resource
def load_parts(kb, db, llm_kind, embed_kind, log, features, kg_kind=""):
    """Build predictor/retriever/llm/store once per configuration (args are cache keys; config is read from env)."""
    store = open_store()
    return build_orchestrator(store=store), store


def new_orchestrator(base, store, session_id):
    return Orchestrator(base.predictor, base.retriever, base.llm, log_path=base.log_path,
                        store=store, session_id=session_id,
                        nutrition_agent=getattr(base, "nutrition_agent", None),
                        memory_agent=getattr(base, "memory_agent", None),
                        summarizer_llm=getattr(base, "summarizer_llm", None),
                        lab_agent=getattr(base, "lab_agent", None),
                        graph_agent=getattr(base, "graph_agent", None),
                        rl_agent=getattr(base, "rl_agent", None))


def _env_key():
    return tuple(os.environ.get(k, "") for k in
                 ("DIACARE_KB", "DIACARE_DB", "DIACARE_LLM", "DIACARE_EMBED",
                  "DIACARE_LOG", "DIACARE_FEATURES", "DIACARE_KG"))


# ---- sidebar ----------------------------------------------------------------

def _default(f, sample):
    if f == "BMI":
        return float(sample[f])
    if f in BINARY_FEATURES and f != "Sex":
        return bool(sample[f])
    return sample[f]


def _load_sample(sample):
    for f in FIELDS:
        st.session_state[f"f_{f}"] = _default(f, sample)


def _save_patient(store):
    profile = {}
    for f in FIELDS:
        v = st.session_state[f"f_{f}"]
        profile[f] = float(v) if f == "BMI" else int(v)
    errors = validate_profile(profile)
    if errors:
        st.session_state["form_errors"] = errors
        return
    st.session_state["form_errors"] = []
    name = (st.session_state.get("f_name") or "").strip() or "Bệnh nhân mới"
    st.session_state["patient_sel"] = store.save_patient(name, profile)


def _form_field(f):
    lo, hi = FEATURE_RANGES[f]
    label = f"{f}: {LABELS[f]}"
    key = f"f_{f}"
    if f == "Sex":
        st.selectbox(label, [0, 1], format_func=lambda v: "Nam" if v else "Nữ", key=key)
    elif f in BINARY_FEATURES:
        st.checkbox(label, key=key)
    elif f == "BMI":
        st.number_input(label, min_value=float(lo), max_value=float(hi), step=0.1, key=key)
    else:
        st.number_input(label, min_value=int(lo), max_value=int(hi), step=1, key=key)


def start_new_session(store, patient_id):
    st.session_state["session_id"] = store.start_session(patient_id)
    st.session_state["session_patient"] = patient_id
    st.session_state["meta"] = {}


def _render_memories(store, patient_id):
    facts = store.list_memories(patient_id)
    if not facts:
        return
    st.subheader("Thông tin đã biết")
    for fact in facts:
        c1, c2 = st.columns([4, 1])
        c1.caption(f"{KIND_LABELS.get(fact['kind'], fact['kind'])}: {fact['content']}")
        if c2.button("Xoá", key=f"del_mem_{fact['id']}"):
            store.deactivate_memory(fact["id"])
            st.rerun()


LEVEL_ICON = {"normal": "🟢", "prediabetes": "🟡", "diabetes": "🔴", "low": "🔵", "unclassified": "⚪"}


def _import_labs(store, patient_id):
    results = []
    upload = st.session_state.get("lab_file")
    try:
        if upload is not None:
            results += parse_lab_file(upload.name, upload.getvalue())
        results += parse_lab_text(st.session_state.get("lab_text", ""))
    except Exception as exc:  # file hỏng / không đọc được
        st.session_state["lab_msg"] = ("error", f"Không đọc được file: {type(exc).__name__}")
        return
    saved = LabAgent(store).import_results(patient_id, results, source="import")
    if saved:
        names = ", ".join(LAB_LABELS[r["test"]] for r in saved)
        st.session_state["lab_msg"] = ("success", f"Đã nhập {len(saved)} chỉ số: {names}.")
        st.session_state["lab_text"] = ""
    else:
        st.session_state["lab_msg"] = (
            "warning", "Không tìm thấy chỉ số hợp lệ. Hỗ trợ: HbA1c, đường huyết lúc đói, "
                       "đường huyết 2 giờ (OGTT), đường huyết bất kỳ.")


def _render_labs(store, patient_id):
    st.subheader("Kết quả xét nghiệm")
    labs = classify([{"test": r["test"], "value": r["value"], "unit": r["unit"]}
                     for r in store.latest_labs(patient_id)])
    for r in labs:
        st.caption(f"{LEVEL_ICON[r['level']]} {r['label']}: {r['value_std']:g} {r['unit_std']} · {r['level_text']}")
    if not labs:
        st.caption("Chưa có kết quả. Có thể nhập file hoặc gõ thẳng vào chat, vd \"HbA1c của tôi 6.8%\".")
    with st.expander("Nhập kết quả xét nghiệm", expanded=not labs):
        st.file_uploader("File kết quả (.txt, .csv, .json, .pdf có chữ/scan, .png, .jpg)",
                         type=["txt", "csv", "json", "pdf", "png", "jpg", "jpeg"],
                         key="lab_file")
        st.text_area("Hoặc dán nội dung phiếu xét nghiệm", key="lab_text",
                     placeholder="HbA1c: 6.8 %\nGlucose lúc đói: 7.4 mmol/L")
        st.button("Nhập kết quả", key="lab_import", on_click=_import_labs, args=(store, patient_id))
        msg = st.session_state.pop("lab_msg", None)
        if msg:
            getattr(st, msg[0])(msg[1])
        st.caption("Chỉ đối chiếu với ngưỡng tham khảo ADA 2024, không phải chẩn đoán.")
    if labs and st.button("Xoá kết quả xét nghiệm", key="lab_clear"):
        store.clear_labs(patient_id)
        st.rerun()


def render_sidebar(store):
    for f in FIELDS:
        st.session_state.setdefault(f"f_{f}", _default(f, LOW_RISK))
    with st.sidebar:
        st.header("Bệnh nhân")
        patients = store.list_patients()
        patient_id = None
        if patients:
            ids = [p["id"] for p in patients]
            if st.session_state.get("patient_sel") not in ids:
                st.session_state["patient_sel"] = ids[0]
            names = {p["id"]: f"#{p['id']} {p['name']}" for p in patients}
            patient_id = st.selectbox("Chọn bệnh nhân", ids, format_func=names.get, key="patient_sel")
        else:
            st.caption("Chưa có bệnh nhân. Hãy tạo hồ sơ mới bên dưới.")
        if patient_id is not None and (
            "session_id" not in st.session_state or st.session_state.get("session_patient") != patient_id
        ):
            start_new_session(store, patient_id)
        if patient_id is not None and st.button("Bắt đầu phiên mới"):
            start_new_session(store, patient_id)
        if patient_id is not None:
            _render_labs(store, patient_id)
            _render_memories(store, patient_id)
        st.divider()
        st.subheader("Tạo hồ sơ mới")
        c1, c2 = st.columns(2)
        c1.button("Nạp hồ sơ mẫu thấp", on_click=_load_sample, args=(LOW_RISK,))
        c2.button("Nạp hồ sơ mẫu cao", on_click=_load_sample, args=(HIGH_RISK,))
        with st.form("patient_form"):
            st.text_input("Tên bệnh nhân", key="f_name")
            for f in FIELDS:
                _form_field(f)
            st.form_submit_button("Lưu hồ sơ", on_click=_save_patient, args=(store,))
        for err in st.session_state.get("form_errors", []):
            st.error(err)
    return patient_id


# ---- chat -------------------------------------------------------------------

BAND_COLOR = {"thấp": "green", "trung bình": "orange", "cao": "red"}
LAB_BADGE = {"low": ("blue", "hạ đường huyết"), "diabetes": ("red", "ngưỡng tiểu đường"),
             "prediabetes": ("orange", "tiền tiểu đường"), "normal": ("green", "bình thường")}


def _trace_line(e):
    return f"**{e['agent']}** · {e['detail']} · `{e['ms']:.0f} ms`"


def _render_trace(trace):
    if not trace:
        st.caption("(không có dữ liệu)")
        return
    st.dataframe([{"Bước": i + 1, "Agent": e["agent"], "Đã làm gì": e["detail"], "ms": e["ms"]}
                  for i, e in enumerate(trace)], hide_index=True, width="stretch")


KG_REL_LABEL = {"claims_risk": "tài liệu nói", "associated_with": "dữ liệu BRFSS đo", "shares_genes": "gen chung (PrimeKG)"}


def _render_kg(kg):
    """Đồ thị con mà Graph agent đã đọc cho câu hỏi này: yếu tố -> ĐTĐ típ 2, ba loại cạnh, có nguồn."""
    if not kg or not kg.get("factors"):
        return
    facts = kg.get("facts") or []
    with st.expander(f"Đồ thị tri thức đã dùng ({len(kg['factors'])} yếu tố, {kg.get('backend', 'kg')})"):
        if facts:
            st.graphviz_chart(subgraph_dot(facts), width="stretch")
            st.caption("Nét đứt cam: tài liệu nêu là yếu tố nguy cơ · nét liền xanh dương: tỉ số chênh BRFSS sau "
                       "hiệu chỉnh · chấm xanh lá: số gen chung với ĐTĐ típ 2 theo PrimeKG (cơ chế chung, "
                       "không phải mức nguy cơ).")
            st.dataframe([{"Yếu tố": r["factor"], "Cạnh": KG_REL_LABEL[r["rel"]], "Nguồn": r["source"],
                           "Nội dung": r["detail"]} for r in subgraph_edges(facts)],
                         hide_index=True, width="stretch")
        st.markdown("**Khối ngữ cảnh gửi cho LLM**")
        for line in kg.get("lines") or []:
            st.caption("- " + line)
        if kg.get("query"):
            st.markdown("**Truy vấn Cypher đã chạy trên Neo4j** (mỗi yếu tố một lần, `$fid` = " +
                        ", ".join(f"`{f}`" for f in kg["factors"]) + ")")
            st.code(kg["query"], language="cypher")


def _render_meta(meta):
    flags = meta.get("flags", [])
    if "small_talk" in flags:  # câu chào: không dự đoán, không hiện nguy cơ
        return
    risk = meta.get("risk")
    parts = []
    if risk is not None:
        band = risk_band(risk)
        who = meta.get("patient") or "hồ sơ"
        parts.append(f"Nguy cơ theo hồ sơ {who}: :{BAND_COLOR[band]}-badge[{band} · {risk:.1%}]")
    else:
        parts.append("Nguy cơ: :gray-badge[chưa tính]")
    lab_level = meta.get("lab_level")
    if lab_level in LAB_BADGE:
        color, text = LAB_BADGE[lab_level]
        parts.append(f"Xét nghiệm: :{color}-badge[{text}]")
    badges = " ".join(f":orange-badge[{f}]" for f in flags) or "không có cờ"
    st.markdown(" · ".join(parts) + f" · Cờ: {badges}")
    if risk is not None and risk_band(risk) != "cao" and (
            lab_level in ("diabetes", "low") or "symptom_referral" in flags):
        st.caption("Mức nguy cơ chỉ do mô hình tính từ 21 câu hỏi lối sống trong hồ sơ (dữ liệu BRFSS), "
                   "không dùng xét nghiệm hay triệu chứng. Hai thứ đó được xét riêng bằng cờ ở trên, "
                   "và chúng quan trọng hơn: hãy đi khám.")
    sources = meta.get("sources", [])
    st.caption("Nguồn: " + (", ".join(sources) if sources else "(không có)"))
    trace = meta.get("trace") or []
    if trace:
        with st.expander(f"Agent đã làm gì ({len(trace)} bước, {sum(e['ms'] for e in trace) / 1000:.1f} s)"):
            for e in trace:
                st.markdown(_trace_line(e))
    _render_kg(meta.get("kg"))
    with st.expander("Chi tiết kỹ thuật"):
        if "context_near_limit" in flags:
            st.warning("Ngữ cảnh gần chạm giới hạn num_ctx, câu trả lời có thể bị cắt.")
        st.markdown("**Bản nháp của mô hình**")
        st.write(meta.get("draft") or "(trống)")
        rl = meta.get("rl")
        if rl and rl.get("action"):
            st.markdown(f"**Chính sách RL (V3):** `{rl['action']}` · {rl['label']} (Q = {rl['q_value']:+.2f})")
        nutrition = meta.get("nutrition")
        if nutrition:
            st.markdown("**Bảng dinh dưỡng (USDA, khẩu phần ước lượng)**")
            st.dataframe([{"Món": i["name"], "Gram": i["grams"], "kcal": i["kcal"], "Carb (g)": i["carb_g"],
                           "Xơ (g)": i["fiber_g"], "Đường (g)": i["sugar_g"]} for i in nutrition["items"]],
                         hide_index=True)
        u = meta.get("usage") or {}
        cols = st.columns(5)
        for col, (label, key) in zip(cols, [
            ("Prompt tokens", "prompt_tokens"), ("Completion tokens", "completion_tokens"),
            ("Giây", "seconds"), ("num_ctx", "num_ctx"), ("Ước lượng prompt", "est_prompt_tokens"),
        ]):
            col.metric(label, u.get(key, "-"))


def _ask(store, base, patient, question, status=None, box=None):
    """status: khung tiến trình agent (st.status); box: chỗ hiện chữ đang stream (st.empty)."""
    sid = st.session_state["session_id"]
    history = store.get_history(sid)
    assistant_index = len(history) + 1  # chỉ số tin nhắn trả lời sau khi lưu
    orch = new_orchestrator(base, store, sid)
    on_step = (lambda e: status.markdown(_trace_line(e))) if status is not None else None
    # Chỉ hiện từng câu đã qua bộ lọc an toàn: lời khuyên đổi thuốc không kịp hiện ra dù một giây.
    # Typewriter gõ phần đã được duyệt ra từng từ một để chữ chảy đều thay vì nhảy cả câu.
    typer = Typewriter(box.markdown) if box is not None else None
    stream = SafeStream(typer) if box is not None else None
    state = orch.run(State(question=question, profile=patient["profile"], history=history,
                           patient_id=patient["id"]), on_token=stream, on_step=on_step)
    if stream is not None:
        stream.flush()
        typer.finish()
    if status is not None:
        total = sum(e["ms"] for e in state.trace) / 1000
        status.update(label=f"Các agent đã xong: {len(state.trace)} bước, {total:.1f} s",
                      state="error" if "system_error" in state.flags else "complete", expanded=False)
    store.add_message(sid, "user", question)
    store.add_message(sid, "assistant", state.final)
    st.session_state.setdefault("meta", {})[assistant_index] = {
        "risk": state.risk, "flags": list(state.flags), "sources": [d["source"] for d in state.docs],
        "draft": state.draft, "usage": dict(state.usage), "nutrition": state.nutrition,
        "kg": state.kg, "rl": state.rl,
        "trace": list(state.trace), "lab_level": worst_level(state.labs),
        "patient": f"#{patient['id']} {patient['name']}",
    }


def render_chat(store, base, patient_id):
    if patient_id is None:
        st.info("Hãy tạo hoặc chọn một bệnh nhân ở thanh bên để bắt đầu tư vấn.")
        return
    patient = store.get_patient(patient_id)
    band = risk_band(base.predictor.predict(patient["profile"]))
    st.caption(f"Bệnh nhân: #{patient['id']} {patient['name']} · hồ sơ nguy cơ {band} · "
               f"Phiên {st.session_state['session_id']} · Đổi bệnh nhân hoặc lưu hồ sơ mới ở thanh bên")
    question = st.chat_input("Nhập câu hỏi về phòng ngừa tiểu đường...")
    _render_messages(store)
    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            status = st.status("Các agent đang xử lý...", expanded=True)
            box = st.empty()
            _ask(store, base, patient, question, status, box)
        st.rerun()  # vẽ lại từ lịch sử để có câu trả lời cuối (đã qua Rules) và phần chi tiết


def _render_messages(store):
    meta = st.session_state.get("meta", {})
    for i, m in enumerate(store.get_history(st.session_state["session_id"])):
        with st.chat_message(m["role"]):
            info = meta.get(i)
            flags = info["flags"] if info else []
            if "system_error" in flags:
                st.error(m["content"])
            else:
                st.write(m["content"])
            if "invalid_input" in flags:
                st.warning("Dữ liệu hồ sơ chưa hợp lệ.")
            if m["role"] == "assistant" and info:
                _render_meta(info)


def render_history(store):
    rows = store.runs(limit=100)
    if not rows:
        st.info("Chưa có lượt chạy nào.")
        return
    df = pd.DataFrame([{
        "Thời gian": r["ts"], "Câu hỏi": r["question"],
        "Nguy cơ": risk_band(r["risk"]) if r["risk"] is not None else "",
        "Cờ": ", ".join(r["flags"]), "Nguồn": ", ".join(r["sources"]), "Lỗi": r["error"] or "",
    } for r in rows])
    st.dataframe(df, width="stretch")


def render_agents(store):
    """Xem lại log từng bước agent của các lượt chạy (lưu trong bảng runs, cột trace_json)."""
    rows = [r for r in store.runs(limit=200) if r["trace"]]
    if not rows:
        st.info("Chưa có lượt chạy nào có log agent. Hãy hỏi một câu ở trang Tư vấn.")
        return
    label = {r["id"]: f"#{r['id']} · {r['ts'][:19].replace('T', ' ')} · {(r['question'] or '')[:60]}" for r in rows}
    run_id = st.selectbox("Chọn lượt chạy", list(label), format_func=label.get, key="agent_run")
    run = next(r for r in rows if r["id"] == run_id)
    st.subheader("Sơ đồ phát lại lượt chạy")
    st.caption("Phát lại từ log thật (trace_json): chấm sáng đi từ Orchestrator tới từng agent theo đúng thứ tự "
               "và thời gian đã ghi. Agent mờ là agent không chạy ở lượt này.")
    # st.iframe: st.html lọc mất SVG và script. Dữ liệu log chỉ được gán bằng textContent trong sơ đồ.
    st.iframe(flow_html(run["trace"], run["question"], run["draft"], run["final"], run["flags"],
                        uid=f"dcflow{run['id']}", page=True), height="content")
    st.subheader("Bảng từng bước")
    c = st.columns(3)
    c[0].metric("Số bước", len(run["trace"]))
    c[1].metric("Tổng thời gian (s)", f"{sum(e['ms'] for e in run['trace']) / 1000:.2f}")
    c[2].metric("Cờ", len(run["flags"]))
    _render_trace(run["trace"])
    with st.expander("Câu hỏi, bản nháp và câu trả lời cuối"):
        st.markdown(f"**Câu hỏi:** {run['question']}")
        st.markdown("**Bản nháp của Advisor:**")
        st.write(run["draft"] or "(trống)")
        st.markdown("**Sau Rules:**")
        st.write(run["final"] or "(trống)")
    st.subheader("Thời gian trung bình mỗi agent")
    totals = {}
    for r in rows:
        for e in r["trace"]:
            totals.setdefault(e["agent"], []).append(e["ms"])
    avg = {a: sum(v) / len(v) for a, v in totals.items()}
    fig, ax = plt.subplots(figsize=(5, 2.5))
    ax.barh(list(avg), list(avg.values()))
    ax.set_xlabel("ms (trung bình)")
    ax.invert_yaxis()
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption(f"Tính trên {len(rows)} lượt chạy gần nhất. Advisor gồm cả thời gian LLM viết câu trả lời.")


def render_stats(store):
    stats = store.run_stats()

    def fmt(v):
        return "-" if v is None else f"{v:.1f}"

    c = st.columns(5)
    c[0].metric("Số lượt chạy", stats["runs"])
    c[1].metric("Số lỗi", stats["errors"])
    c[2].metric("Prompt tokens TB", fmt(stats["avg_prompt_tokens"]))
    c[3].metric("Completion tokens TB", fmt(stats["avg_completion_tokens"]))
    c[4].metric("Giây TB", fmt(stats["avg_seconds"]))
    counts = stats["flag_counts"]
    if counts:
        fig, ax = plt.subplots(figsize=(5, 2.5))
        ax.bar(list(counts), list(counts.values()))
        ax.set_ylabel("Số lần")
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)


_NO_TRANSLATE_JS = """<script>
(() => {  // IIFE: script chạy lại mỗi lần rerun, khai báo const toàn cục sẽ báo lỗi "already declared"
const d = window.parent.document;
d.documentElement.lang = "vi";
d.documentElement.setAttribute("translate", "no");
d.documentElement.classList.add("notranslate");
if (!d.querySelector('meta[name="google"]')) {
  const m = d.createElement("meta"); m.name = "google"; m.content = "notranslate"; d.head.appendChild(m);
}
})();
</script>"""


def _no_auto_translate():
    """Streamlit khai báo trang là tiếng Anh nên Chrome tự 'dịch' chữ Việt ("Chi tiết kỹ thuật" -> "Chim ™").
    Đặt lang=vi và translate=no cho trang cha để trình duyệt không dịch."""
    st.html(_NO_TRANSLATE_JS, unsafe_allow_javascript=True)


def main():
    st.set_page_config(page_title="DiaCare-MAS", layout="wide")
    _no_auto_translate()
    st.title("DiaCare-MAS")
    st.warning("Công cụ hỗ trợ học tập, không thay thế bác sĩ.")
    if os.environ.get("DIACARE_LLM") == "demo" or os.environ.get("DIACARE_EMBED") == "hash":
        st.info("Chế độ demo đang bật: mô hình ngôn ngữ giả lập hoặc embedding băm, chỉ dùng để thử giao diện.")
    base, store = load_parts(*_env_key())
    patient_id = render_sidebar(store)
    # Dùng nút chọn trang thay cho st.tabs: st.chat_input chỉ được ghim xuống đáy màn hình
    # (kiểu ChatGPT) khi nằm ở cấp ngoài cùng, không ở trong tab/cột/expander.
    page = st.radio("Trang", PAGES, horizontal=True, key="page", label_visibility="collapsed")
    if page == "Tư vấn":
        render_chat(store, base, patient_id)
    elif page == "Hoạt động agent":
        render_agents(store)
    elif page == "Lịch sử":
        render_history(store)
    else:
        render_stats(store)


main()
