import pytest
from streamlit.testing.v1 import AppTest

from pathlib import Path

from diacare.factory import open_store

APP = Path(__file__).resolve().parent.parent / "src" / "app.py"


@pytest.fixture
def env(tmp_path, monkeypatch):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ada.txt").write_text("Ăn nhiều rau xanh và hạn chế đường.", encoding="utf-8")
    monkeypatch.setenv("DIACARE_LLM", "demo")
    monkeypatch.setenv("DIACARE_EMBED", "hash")
    monkeypatch.setenv("DIACARE_KB", str(kb))
    monkeypatch.setenv("DIACARE_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("DIACARE_LOG", str(tmp_path / "runs.jsonl"))
    monkeypatch.setenv("DIACARE_DEV", "1")  # các test cũ kiểm tra chế độ nhà phát triển
    return tmp_path


@pytest.fixture
def user_env(env, monkeypatch):
    monkeypatch.delenv("DIACARE_DEV")
    return env


def new_app():
    return AppTest.from_file(str(APP), default_timeout=60)


def create_patient(at, name="An", diagnosed=False, page="Tư vấn"):
    at.sidebar.text_input[0].set_value(name)
    if diagnosed:
        at.sidebar.checkbox(key="f_diagnosed").check()
    at.sidebar.button[-1].click().run()  # nút lưu của form hồ sơ
    if page:
        at.radio(key="page").set_value(page).run()
    return at


def test_app_runs_and_shows_demo_banner(env):
    at = new_app().run()
    assert not at.exception
    assert any("demo" in i.value.lower() for i in at.info)
    assert list(at.radio(key="page").options) == ["Hôm nay", "Nhật ký", "Tư vấn", "Tái khám",
                                                  "Hoạt động agent", "Lịch sử", "Thống kê"]


def test_chat_input_pinned_at_top_level(env):
    # Streamlit chỉ ghim ô chat xuống đáy khi st.chat_input không nằm trong tab/cột/expander
    at = create_patient(new_app().run())
    assert len(at.tabs) == 0
    assert len(at.chat_input) == 1
    at.radio(key="page").set_value("Lịch sử").run()
    assert not at.exception
    assert len(at.chat_input) == 0
    at.radio(key="page").set_value("Hoạt động agent").run()
    assert not at.exception
    at.radio(key="page").set_value("Thống kê").run()
    assert not at.exception


def test_create_patient_and_chat(env):
    at = new_app().run()
    at.sidebar.text_input[0].set_value("An")
    at.sidebar.button[-1].click().run()  # form submit button
    at.radio(key="page").set_value("Tư vấn").run()
    assert not at.exception
    assert [p["name"] for p in open_store().list_patients()] == ["An"]
    at.chat_input[0].set_value("Nên ăn rau không?").run()
    assert not at.exception
    assistant = [m for m in at.chat_message if m.name == "assistant"]
    assert assistant and "Theo tài liệu [ada.txt]" in assistant[0].markdown[0].value
    assert len(open_store().runs()) == 1


def test_invalid_form_shows_error(env, monkeypatch):
    # The number_input widgets already clamp to the valid ranges, so force the validator to fail.
    monkeypatch.setattr("diacare.rules.validate_profile", lambda profile: ["BMI ngoài khoảng cho phép"])
    at = new_app().run()
    at.sidebar.button[-1].click().run()
    assert open_store().list_patients() == []
    assert any("BMI" in e.value for e in at.sidebar.error)


def test_assistant_message_shows_risk_sources_and_details(env):
    at = create_patient(new_app().run())
    at.chat_input[0].set_value("Nên ăn rau không?").run()
    assert not at.exception
    assert any("Nguy cơ theo hồ sơ #1 An" in m.value for m in at.markdown)
    assert any(e.label.startswith("Agent đã làm gì") for e in at.expander)
    assert any(c.value.startswith("Nguồn:") and "ada.txt" in c.value for c in at.caption)
    assert "Chi tiết kỹ thuật" in [e.label for e in at.expander]
    # hỏi tiếp câu thứ hai: tin nhắn trả lời thứ hai cũng phải có chi tiết
    at.chat_input[0].set_value("Còn tập thể dục thì sao?").run()
    assert not at.exception
    assert [e.label for e in at.expander].count("Chi tiết kỹ thuật") == 2


def test_sidebar_shows_and_deletes_memory(env):
    at = create_patient(new_app().run())
    at.chat_input[0].set_value("Tôi bị dị ứng tôm.").run()
    store = open_store()
    pid = store.list_patients()[0]["id"]
    assert [m["content"] for m in store.list_memories(pid)] == ["tôm"]
    at.run()
    assert any("dị ứng: tôm" in c.value for c in at.sidebar.caption)
    next(b for b in at.sidebar.button if b.label == "Xoá").click().run()
    assert open_store().list_memories(pid) == []


def test_greeting_shows_no_risk_line(env):
    at = create_patient(new_app().run())
    at.chat_input[0].set_value("chào bạn").run()
    assert not at.exception
    assistant = [m for m in at.chat_message if m.name == "assistant"]
    texts = " ".join(md.value for md in assistant[0].markdown)
    assert "Chào bạn" in texts and "Nguy cơ" not in texts


def test_import_lab_results_from_pasted_text(env):
    at = create_patient(new_app().run(), page="Nhật ký")
    at.text_area(key="lab_text").set_value("HbA1c: 6.8 %\nGlucose lúc đói: 5.0 mmol/L").run()
    at.button(key="lab_import").click().run()
    assert not at.exception
    assert any("Đã nhập 2 chỉ số" in s.value for s in at.success)
    table = next(d.value for d in at.dataframe if "Đối chiếu" in d.value.columns)
    assert "6.8 %" in list(table["Kết quả"]) and any("ngưỡng chẩn đoán" in v for v in table["Đối chiếu"])
    at.radio(key="page").set_value("Tư vấn").run()
    at.chat_input[0].set_value("Kết quả xét nghiệm của tôi thế nào?").run()
    assert not at.exception
    assert any("lab_diabetes_range" in m.value for m in at.markdown)


def test_import_without_values_warns(env):
    at = create_patient(new_app().run(), page="Nhật ký")
    at.text_area(key="lab_text").set_value("không có số liệu").run()
    at.button(key="lab_import").click().run()
    assert any("Không tìm thấy" in w.value for w in at.warning)


def test_agent_page_shows_trace_of_last_run(env):
    at = create_patient(new_app().run())
    at.chat_input[0].set_value("Nên ăn rau không?").run()
    at.radio(key="page").set_value("Hoạt động agent").run()
    assert not at.exception
    agents = list(at.dataframe[0].value["Agent"])
    assert agents[0] == "Memory" and agents[-1] == "Rules"
    assert {"Predictor", "Retriever", "Advisor"} <= set(agents)


def test_low_profile_with_diabetes_labs_explains_risk(env):
    at = create_patient(new_app().run())  # hồ sơ mặc định là hồ sơ nguy cơ thấp
    at.chat_input[0].set_value("HbA1c của tôi 8.5%, tôi khát nước và tiểu nhiều").run()
    assert not at.exception
    line = next(m.value for m in at.markdown if "Nguy cơ theo hồ sơ" in m.value)
    assert "thấp" in line and "ngưỡng tiểu đường" in line
    assert any("không dùng xét nghiệm hay triệu chứng" in c.value for c in at.caption)


# ---- chế độ người dùng (mặc định): Hôm nay, Nhật ký, Tư vấn, Tái khám ----

def test_user_mode_hides_technical_pages_and_details(user_env):
    at = new_app().run()
    assert list(at.radio(key="page").options) == ["Hôm nay", "Nhật ký", "Tư vấn", "Tái khám"]
    create_patient(at, diagnosed=True)
    store = open_store()
    pid = store.list_patients()[0]["id"]
    assert [m["content"] for m in store.list_memories(pid)] == ["đái tháo đường típ 2"]
    at.chat_input[0].set_value("Nên ăn rau không?").run()
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert "Chi tiết kỹ thuật" not in labels and not any(lb.startswith("Agent đã làm gì") for lb in labels)
    assert not any("Nguy cơ theo hồ sơ" in m.value for m in at.markdown)
    assert any(c.value.startswith("Nguồn:") and "ada.txt" in c.value for c in at.caption)
    # bật chế độ nhà phát triển thì hiện lại đủ 7 trang và chi tiết
    at.sidebar.toggle(key="dev_mode").set_value(True).run()
    assert len(at.radio(key="page").options) == 7
    assert "Chi tiết kỹ thuật" in [e.label for e in at.expander]
    at.radio(key="page").set_value("Thống kê").run()
    at.sidebar.toggle(key="dev_mode").set_value(False).run()
    assert not at.exception and at.radio(key="page").value == "Hôm nay"


def test_today_logs_glucose_and_warns_on_hypo(user_env):
    at = create_patient(new_app().run(), page=None)
    assert at.radio(key="page").value == "Hôm nay"
    assert any("chưa ghi đường huyết" in i.value for i in at.info)
    at.number_input(key="today_value").set_value(3.2)
    at.selectbox(key="today_unit").set_value("mmol/L")
    at.button[0].click()  # nút Lưu của form ghi đường huyết
    at.run()
    assert not at.exception
    assert any("Đã lưu 3,2 mmol/L" in w.value and "hạ đường huyết" in w.value for w in at.warning)
    assert any("15" in w.value for w in at.warning)
    rows = open_store().list_readings(1)
    assert len(rows) == 1 and rows[0]["value"] == pytest.approx(57.6)
    assert not any("chưa ghi đường huyết" in i.value for i in at.info)


def test_today_rejects_wrong_unit(user_env):
    at = create_patient(new_app().run(), page=None)
    at.number_input(key="today_value").set_value(120.0)
    at.selectbox(key="today_unit").set_value("mmol/L")
    at.button[0].click()
    at.run()
    assert any("đơn vị" in e.value for e in at.error)
    assert open_store().list_readings(1) == []


def test_journal_and_visit_pages(user_env):
    at = create_patient(new_app().run(), page="Nhật ký")
    assert not at.exception
    assert any("Chưa có lần đo" in c.value for c in at.caption)
    at.radio(key="page").set_value("Tái khám").run()
    assert not at.exception
    at.text_input(key="q_text").set_value("Có cần đổi giờ uống thuốc?")
    next(b for b in at.button if b.label == "Thêm").click()
    at.run()
    assert [q["text"] for q in open_store().list_doctor_questions(1)] == ["Có cần đổi giờ uống thuốc?"]
    at.text_input(key="appt_place").set_value("BV Bạch Mai")
    next(b for b in at.button if b.label == "Lưu lịch").click()
    at.run()
    assert open_store().get_appointment(1)["place"] == "BV Bạch Mai"
    at.button(key="visit_make").click().run()
    assert not at.exception
    pdf = at.session_state["visit_pdf"]
    assert pdf[0] == 1 and pdf[1].startswith(b"%PDF")
