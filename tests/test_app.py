import pytest
from streamlit.testing.v1 import AppTest

from pathlib import Path

from diacare.factory import open_store
from diacare.rules import DISCLAIMER

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
    assert list(at.radio(key="page").options) == ["Hôm nay", "Nhật ký", "Bữa ăn", "Tư vấn", "Tái khám",
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
    assert any("Đã lưu 2 chỉ số" in s.value for s in at.success)
    table = next(d.value for d in at.dataframe if "Đối chiếu" in d.value.columns)
    assert "6.8 %" in list(table["Kết quả"]) and any("ngưỡng chẩn đoán" in v for v in table["Đối chiếu"])
    at.radio(key="page").set_value("Tư vấn").run()
    at.chat_input[0].set_value("Kết quả xét nghiệm của tôi thế nào?").run()
    assert not at.exception
    assert any("lab_diabetes_range" in m.value for m in at.markdown)


def test_lab_file_saved_as_soon_as_chosen(env):
    # lỗi 2026-11-25: chọn tệp phiếu xét nghiệm, không bấm nút, chuyển trang rồi quay lại thì kết quả mất
    at = create_patient(new_app().run(), page="Nhật ký")
    sheet = "HbA1c: 6.8 %\nGlucose lúc đói: 7.4 mmol/L".encode("utf-8")
    at.file_uploader(key="lab_file").set_value(("phieu.txt", sheet, "text/plain")).run()
    assert not at.exception
    assert any("Đã lưu 2 chỉ số từ tệp phieu.txt" in s.value for s in at.success)
    at.radio(key="page").set_value("Tư vấn").run()
    at.radio(key="page").set_value("Nhật ký").run()
    table = next(d.value for d in at.dataframe if "Đối chiếu" in d.value.columns)
    assert len(table) == 2 and "6.8 %" in list(table["Kết quả"])
    at.button(key="lab_import").click().run()  # ô chữ trống: không nhập lại tệp lần nữa
    table = next(d.value for d in at.dataframe if "Đối chiếu" in d.value.columns)
    assert len(table) == 2


def test_lab_file_without_values_warns(env):
    at = create_patient(new_app().run(), page="Nhật ký")
    at.file_uploader(key="lab_file").set_value(("ghi_chu.txt", "không có số".encode("utf-8"), "text/plain")).run()
    assert any("chưa lưu gì" in w.value for w in at.warning)


def test_chat_photo_of_lab_sheet_is_saved_as_lab(tmp_path, monkeypatch):
    from ui_common import photo_labs

    class Photo:
        name = "phieu.jpg"

        def getvalue(self):
            return b"anh"
    store = open_store(str(tmp_path / "s.db"))
    pid = store.save_patient("An", {})
    monkeypatch.setattr("diacare.labs.ocr_image", lambda data, ocr_fn=None: "HbA1c: 7.2 %")
    assert [r["test"] for r in photo_labs(store, pid, Photo())] == ["hba1c"]
    assert [r["value"] for r in store.list_labs(pid)] == [7.2]
    monkeypatch.setattr("diacare.labs.ocr_image", lambda data, ocr_fn=None: "Cơm tấm sườn bì chả")
    assert photo_labs(store, pid, Photo()) is None  # ảnh bữa ăn: để nhận diện món ăn xử lý


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


# ---- chế độ người dùng (mặc định): Hôm nay, Nhật ký, Bữa ăn, Tư vấn, Tái khám ----

def test_user_mode_hides_technical_pages_and_details(user_env):
    at = new_app().run()
    assert list(at.radio(key="page").options) == ["Hôm nay", "Nhật ký", "Bữa ăn", "Tư vấn", "Tái khám"]
    create_patient(at, diagnosed=True)
    store = open_store()
    pid = store.list_patients()[0]["id"]
    assert [m["content"] for m in store.list_memories(pid)] == ["đái tháo đường típ 2"]
    at.chat_input[0].set_value("Nên ăn rau không?").run()
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert "Chi tiết kỹ thuật" not in labels and not any(lb.startswith("Agent đã làm gì") for lb in labels)
    assert not any("Nguy cơ theo hồ sơ" in m.value for m in at.markdown)
    # LLM giả không ghi nhãn nguồn: kể tài liệu đã tra (nhãn lạ thì giữ tên tệp); lời miễn trừ in nhỏ dưới bài
    assert any(c.value.startswith("Tài liệu đã tham khảo:") and "ada.txt" in c.value for c in at.caption)
    assert any(c.value == DISCLAIMER for c in at.caption)
    assert not any(DISCLAIMER in m.value for m in at.markdown)
    assert not any("Trọng tâm tư vấn do agent" in c.value for c in at.caption)  # dòng RL chỉ cho nhà phát triển
    # bật chế độ nhà phát triển thì hiện lại đủ 8 trang và chi tiết
    at.sidebar.toggle(key="dev_mode").set_value(True).run()
    assert len(at.radio(key="page").options) == 8
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


def test_visit_page_sets_and_resets_custom_targets(user_env):
    at = create_patient(new_app().run(), page="Tái khám")
    assert any("mục tiêu chung (ADA 2024)" in c.value for c in at.caption)
    at.number_input(key="tg_lo").set_value(3.0)   # thấp hơn ngưỡng hạ đường huyết: bị từ chối
    next(b for b in at.button if b.label == "Lưu mục tiêu").click()
    at.run()
    assert any("3,9" in e.value for e in at.error) and open_store().get_targets(1) is None
    at.number_input(key="tg_lo").set_value(5.0)
    at.number_input(key="tg_hi").set_value(8.3)
    at.number_input(key="tg_post").set_value(11.0)
    at.text_input(key="tg_note").set_value("BS Minh")
    next(b for b in at.button if b.label == "Lưu mục tiêu").click()
    at.run()
    assert not at.exception
    row = open_store().get_targets(1)
    assert row["pre_lo"] == pytest.approx(90.0) and row["pre_hi"] == pytest.approx(149.4) and row["note"] == "BS Minh"
    assert any("mục tiêu bác sĩ đặt: trước ăn 5,0 mmol/L–8,3 mmol/L" in c.value for c in at.caption)
    next(b for b in at.button if b.label == "Dùng lại mục tiêu chung").click()
    at.run()
    assert open_store().get_targets(1) is None


def _assistant_texts(at):
    return [" ".join(md.value for md in m.markdown) for m in at.chat_message if m.name == "assistant"]


def test_checkin_opener_once_and_reading_saved_after_confirm(user_env):
    from diacare.journal import now_vn
    at = create_patient(new_app().run(), name="Lan", diagnosed=True)
    assert not at.exception
    texts = _assistant_texts(at)
    assert len(texts) == 1 and texts[0].startswith("Chào Lan!") and "đường huyết" in texts[0]
    store = open_store()
    pid = store.list_patients()[0]["id"]
    assert store.get_checkin(pid, now_vn().date())["status"] == "open"
    at.run()  # chạy lại trang: không hỏi lại
    at.radio(key="page").set_value("Hôm nay").run()
    at.radio(key="page").set_value("Tư vấn").run()
    assert len(_assistant_texts(at)) == 1

    at.chat_input[0].set_value("6,5 lúc đói").run()
    assert not at.exception
    assert open_store().list_readings(pid) == []  # chưa bấm Lưu thì chưa ghi
    assert at.selectbox(key="ci_ctx_1").value == "fasting"
    at.button(key="ci_save_1").click().run()
    assert not at.exception
    rows = open_store().list_readings(pid)
    assert len(rows) == 1 and abs(rows[0]["value"] - 6.5 * 18.0) < 1.5 and rows[0]["context"] == "fasting"
    texts = _assistant_texts(at)
    assert "Mình đã ghi 6,5 mmol/L" in texts[-1] and "trong mục tiêu" in texts[-1]
    assert open_store().get_checkin(pid, now_vn().date())["status"] == "done"
    assert len(open_store().runs()) == 0  # không gọi pipeline tư vấn


def test_checkin_not_yet_and_question_go_their_way(user_env):
    at = create_patient(new_app().run(), name="Lan", diagnosed=True)
    at.chat_input[0].set_value("chưa đo").run()
    assert "Không sao" in _assistant_texts(at)[-1]
    assert len(open_store().runs()) == 0
    at.chat_input[0].set_value("Đường huyết 8,5 lúc đói có cao không?").run()
    assert not at.exception
    assert len(open_store().runs()) == 1  # câu hỏi có số vẫn đi pipeline tư vấn, không thành thẻ lưu
    assert "checkin_card" not in at.session_state


def test_no_checkin_for_undiagnosed(user_env):
    at = create_patient(new_app().run(), name="An")
    assert _assistant_texts(at) == []


# ---- trang Bữa ăn (agent bữa ăn, Calo Khay) ----

def _fake_scan(at, needs_confirm):
    from diacare import meal_scan
    items = [{"cls": "rice", "name": "cơm trắng", "grams": 228, "conf": 0.99, "needs_confirm": False,
              "suggestions": [], "gram_method": "rice_mean", "gram_source": "model"},
             {"cls": "stir_fried_vegetables", "name": "rau xào thập cẩm", "grams": 54, "conf": 0.49,
              "needs_confirm": needs_confirm, "suggestions": ["pork_broccoli"], "gram_method": "area",
              "gram_source": "model"}]
    at.session_state["meal_scan"] = {"n": 1, "items": items, "warnings": [], "image": None}
    return meal_scan


def test_meal_page_save_needs_every_dish_checked(user_env):
    at = create_patient(new_app().run(), page="Bữa ăn")
    assert not at.exception
    _fake_scan(at, needs_confirm=True)
    at.run()
    assert not at.exception
    assert any("cơm" in i.value for i in at.info)              # nhắc sửa gram cơm
    assert any("tinh bột" in m.value for m in at.markdown)
    assert at.button(key="meal_save_1").disabled                # còn món chưa xác nhận


def test_meal_page_saves_meal(user_env):
    at = create_patient(new_app().run(), page="Bữa ăn")
    _fake_scan(at, needs_confirm=False)
    at.run()
    at.button(key="meal_save_1").click().run()
    assert not at.exception
    store = open_store()
    meals = store.list_meals(store.list_patients()[0]["id"])
    assert len(meals) == 1 and [it["name"] for it in meals[0]["items"]] == ["cơm trắng", "rau xào thập cẩm"]
    assert meals[0]["carb_low"] < meals[0]["carb_g"] < meals[0]["carb_high"]
    assert any("Đã lưu bữa ăn" in s.value for s in at.success)
    assert "meal_scan" not in at.session_state



def test_meal_page_manual_entry_without_photo(user_env):
    at = create_patient(new_app().run(), page="Bữa ăn")
    at.button(key="meal_manual_btn").click().run()
    assert not at.exception
    assert "meal_scan" in at.session_state and at.session_state["meal_scan"]["items"] == []
    assert at.button(key="meal_save_1").disabled                # chưa có món nào
    assert at.button(key="meal_drop_1").label == "Huỷ"
    at.button(key="meal_drop_1").click().run()
    assert "meal_scan" not in at.session_state

# ---- trợ lý chủ động hỏi: trả lời bằng giọng nói ----

def _wav(seconds=1.0, rate=16000):
    import io
    import wave

    import numpy as np
    t = np.arange(int(seconds * rate)) / rate
    pcm = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return ("ghi_am.wav", buf.getvalue(), "audio/wav")


def test_checkin_voice_reading_goes_to_confirm_card(user_env, monkeypatch):
    monkeypatch.setenv("DIACARE_ASR", "demo")
    monkeypatch.setenv("DIACARE_ASR_DEMO_TEXT", "sáu phẩy năm")
    at = create_patient(new_app().run(), name="Lan", diagnosed=True)
    assert at.audio_input(key="ci_voice").label == "Hoặc trả lời bằng giọng nói"
    at.audio_input(key="ci_voice").set_value(_wav()).run()
    assert not at.exception
    assert at.text_input(key="ci_heard_text_1").value == "sáu phẩy năm"   # chữ nghe được: sửa được trước khi gửi
    at.button(key="ci_heard_send_1").click().run()
    assert not at.exception
    store = open_store()
    pid = store.list_patients()[0]["id"]
    assert store.list_readings(pid) == []                 # chưa Lưu thì chưa ghi
    at.button(key="ci_save_1").click().run()
    assert not at.exception
    rows = open_store().list_readings(pid)
    assert len(rows) == 1 and abs(rows[0]["value"] - 6.5 * 18.0) < 1.5
    at.run()  # đoạn ghi âm cũ còn trong ô: không xử lý lại, không thêm thẻ mới
    assert len(open_store().list_readings(pid)) == 1 and "checkin_card" not in at.session_state


def test_checkin_voice_question_goes_to_pipeline(user_env, monkeypatch):
    monkeypatch.setenv("DIACARE_ASR", "demo")
    monkeypatch.setenv("DIACARE_ASR_DEMO_TEXT", "đường huyết bao nhiêu là tốt")
    at = create_patient(new_app().run(), name="Lan", diagnosed=True)
    at.audio_input(key="ci_voice").set_value(_wav()).run()
    assert len(open_store().runs()) == 0                  # chưa bấm Gửi: không gửi câu nghe được cho pipeline
    at.text_input(key="ci_heard_text_1").set_value("đường huyết bao nhiêu là tốt?")
    at.button(key="ci_heard_send_1").click().run()
    assert not at.exception
    assert len(open_store().runs()) == 1
    assert not at.audio_input  # lượt hỏi đã đóng: không còn ô ghi âm


def test_checkin_voice_too_short_warns(user_env, monkeypatch):
    monkeypatch.setenv("DIACARE_ASR", "demo")
    at = create_patient(new_app().run(), name="Lan", diagnosed=True)
    at.audio_input(key="ci_voice").set_value(_wav(0.1)).run()
    assert any("quá ngắn" in w.value for w in at.warning)
    assert len(open_store().runs()) == 0


def test_chat_input_parts_text_photo_audio():
    """Ô chat nhận chữ, ảnh bữa ăn và ghi âm (Streamlit >= 1.5x trả ChatInputValue khi bật tệp/ghi âm)."""
    import sys
    sys.path.insert(0, str(APP.parent))
    from ui_common import chat_parts as _chat_parts
    assert _chat_parts(None) == (None, None, None)
    assert _chat_parts("Ăn chuối được không?") == ("Ăn chuối được không?", None, None)
    assert _chat_parts({"text": "  ", "files": ["anh"], "audio": None}) == (None, "anh", None)
    assert _chat_parts({"text": "", "files": [], "audio": "wav"}) == (None, None, "wav")


def test_serial_store_survives_concurrent_sessions(tmp_path):
    """Hai tab Streamlit = hai luồng dùng chung một Store (cache_resource). Không khoá thì sqlite3 đọc nhầm con trỏ
    của nhau (IndexError / InterfaceError, đã gặp khi chạy thật)."""
    import sys
    import threading
    sys.path.insert(0, str(APP.parent))
    from ui_common import SerialStore
    from diacare.db import Store
    raw = Store(tmp_path / "t.db")
    pid = raw.save_patient("A", {})
    for _ in range(30):
        raw.add_lab(pid, "hba1c", 6.5, "%")
    store, errs = SerialStore(raw), []

    def run():
        try:
            for _ in range(200):
                assert len(store.list_labs(pid)) == 30
                store.list_patients()
        except Exception as e:  # noqa: BLE001
            errs.append(type(e).__name__)
    ts = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errs == []


def test_voice_mode_mounts_big_mic_and_speaks_card_prompt(user_env, monkeypatch):
    """Bật "Trò chuyện bằng giọng nói": trang Tư vấn gắn nút micro to (CCv2) mà không lỗi; khi có thẻ số đo đang chờ,
    lượt sau chuẩn bị câu đọc to nhắc kiểm tra thẻ."""
    monkeypatch.setenv("DIACARE_ASR", "demo")
    monkeypatch.setenv("DIACARE_TTS_MODEL", "khong_co.onnx")  # không có giọng: vẫn chạy, chỉ báo chú thích
    at = create_patient(new_app().run(), page="Tư vấn")
    at.toggle(key="voice_mode").set_value(True).run()
    assert not at.exception
    at.session_state["checkin_card"] = {"n": 1, "reading": {"kind": "glucose", "value": 6.5, "unit": "mmol/L",
                                                            "context": "fasting", "summary": "Đường huyết 6,5 mmol/L"},
                                        "when": "2026-11-25T07:00:00+07:00"}
    at.session_state["speak_after"] = 10 ** 6
    at.run()
    assert not at.exception
    reply = at.session_state["voice_reply"]
    assert reply["audio"] is None and "giọng đọc tiếng Việt" in reply["note"]
