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
    return tmp_path


def new_app():
    return AppTest.from_file(str(APP), default_timeout=60)


def test_app_runs_and_shows_demo_banner(env):
    at = new_app().run()
    assert not at.exception
    assert any("demo" in i.value.lower() for i in at.info)
    assert list(at.radio(key="page").options) == ["Tư vấn", "Lịch sử", "Thống kê"]


def test_chat_input_pinned_at_top_level(env):
    # Streamlit chỉ ghim ô chat xuống đáy khi st.chat_input không nằm trong tab/cột/expander
    at = new_app().run()
    at.sidebar.text_input[0].set_value("An")
    at.sidebar.button[-1].click().run()
    assert len(at.tabs) == 0
    assert len(at.chat_input) == 1
    at.radio(key="page").set_value("Lịch sử").run()
    assert not at.exception
    assert len(at.chat_input) == 0
    at.radio(key="page").set_value("Thống kê").run()
    assert not at.exception


def test_create_patient_and_chat(env):
    at = new_app().run()
    at.sidebar.text_input[0].set_value("An")
    at.sidebar.button[-1].click().run()  # form submit button
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
    at = new_app().run()
    at.sidebar.text_input[0].set_value("An")
    at.sidebar.button[-1].click().run()
    at.chat_input[0].set_value("Nên ăn rau không?").run()
    assert not at.exception
    assert any("Nguy cơ:" in m.value for m in at.markdown)
    assert any(c.value.startswith("Nguồn:") and "ada.txt" in c.value for c in at.caption)
    assert "Chi tiết kỹ thuật" in [e.label for e in at.expander]
    # hỏi tiếp câu thứ hai: tin nhắn trả lời thứ hai cũng phải có chi tiết
    at.chat_input[0].set_value("Còn tập thể dục thì sao?").run()
    assert not at.exception
    assert [e.label for e in at.expander].count("Chi tiết kỹ thuật") == 2


def test_sidebar_shows_and_deletes_memory(env):
    at = new_app().run()
    at.sidebar.text_input[0].set_value("An")
    at.sidebar.button[-1].click().run()
    at.chat_input[0].set_value("Tôi bị dị ứng tôm.").run()
    store = open_store()
    pid = store.list_patients()[0]["id"]
    assert [m["content"] for m in store.list_memories(pid)] == ["tôm"]
    at.run()
    assert any("dị ứng: tôm" in c.value for c in at.sidebar.caption)
    next(b for b in at.sidebar.button if b.label == "Xoá").click().run()
    assert open_store().list_memories(pid) == []
