import os

import matplotlib
import pandas as pd
import streamlit as st

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from diacare.factory import build_orchestrator, open_store  # noqa: E402
from diacare.memory import KIND_LABELS  # noqa: E402
from diacare.orchestrator import Orchestrator  # noqa: E402
from diacare.rules import BINARY_FEATURES, FEATURE_RANGES, risk_band, validate_profile  # noqa: E402
from diacare.samples import HIGH_RISK, LOW_RISK  # noqa: E402
from diacare.state import State  # noqa: E402

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
PAGES = ("Tư vấn", "Lịch sử", "Thống kê")


@st.cache_resource
def load_parts(kb, db, llm_kind, embed_kind, log, features):
    """Build predictor/retriever/llm/store once per configuration (args are cache keys; config is read from env)."""
    store = open_store()
    return build_orchestrator(store=store), store


def new_orchestrator(base, store, session_id):
    return Orchestrator(base.predictor, base.retriever, base.llm, log_path=base.log_path,
                        store=store, session_id=session_id,
                        nutrition_agent=getattr(base, "nutrition_agent", None),
                        memory_agent=getattr(base, "memory_agent", None),
                        summarizer_llm=getattr(base, "summarizer_llm", None))


def _env_key():
    return tuple(os.environ.get(k, "") for k in
                 ("DIACARE_KB", "DIACARE_DB", "DIACARE_LLM", "DIACARE_EMBED", "DIACARE_LOG", "DIACARE_FEATURES"))


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

def _render_meta(meta):
    flags = meta.get("flags", [])
    if "small_talk" in flags:  # câu chào: không dự đoán, không hiện nguy cơ
        return
    risk = meta.get("risk")
    band = risk_band(risk) if risk is not None else "chưa tính"
    badges = " ".join(f":orange-badge[{f}]" for f in flags) or "không có cờ"
    st.markdown(f"Nguy cơ (theo hồ sơ ở thanh bên): :blue-badge[{band}] · Cờ: {badges}")
    sources = meta.get("sources", [])
    st.caption("Nguồn: " + (", ".join(sources) if sources else "(không có)"))
    with st.expander("Chi tiết kỹ thuật"):
        if "context_near_limit" in flags:
            st.warning("Ngữ cảnh gần chạm giới hạn num_ctx, câu trả lời có thể bị cắt.")
        st.markdown("**Bản nháp của mô hình**")
        st.write(meta.get("draft") or "(trống)")
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


def _ask(store, base, patient, question):
    sid = st.session_state["session_id"]
    history = store.get_history(sid)
    assistant_index = len(history) + 1  # chỉ số tin nhắn trả lời sau khi lưu
    orch = new_orchestrator(base, store, sid)
    with st.spinner("Đang xử lý..."):
        state = orch.run(State(question=question, profile=patient["profile"], history=history,
                                 patient_id=patient["id"]))
    store.add_message(sid, "user", question)
    store.add_message(sid, "assistant", state.final)
    st.session_state.setdefault("meta", {})[assistant_index] = {
        "risk": state.risk, "flags": list(state.flags), "sources": [d["source"] for d in state.docs],
        "draft": state.draft, "usage": dict(state.usage), "nutrition": state.nutrition,
    }


def render_chat(store, base, patient_id):
    if patient_id is None:
        st.info("Hãy tạo hoặc chọn một bệnh nhân ở thanh bên để bắt đầu tư vấn.")
        return
    patient = store.get_patient(patient_id)
    st.caption(f"Bệnh nhân: #{patient['id']} {patient['name']} · Phiên {st.session_state['session_id']}")
    question = st.chat_input("Nhập câu hỏi về phòng ngừa tiểu đường...")
    if question:
        _ask(store, base, patient, question)
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


def main():
    st.set_page_config(page_title="DiaCare-MAS", layout="wide")
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
    elif page == "Lịch sử":
        render_history(store)
    else:
        render_stats(store)


main()
