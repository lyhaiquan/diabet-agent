from diacare.advisor import advise, build_messages

CTX = {
    "question": "Tôi nên ăn gì?",
    "risk": 0.62,
    "docs": [{"source": "ada.txt", "text": "Hạn chế đường hấp thu nhanh."}],
    "history": [{"role": "user", "content": "chào"}],
}


def test_messages_contain_docs_risk_and_question():
    msgs = build_messages(CTX)
    assert msgs[0]["role"] == "system"
    joined = "\n".join(m["content"] for m in msgs)
    assert "[ada.txt]" in joined
    assert "Hạn chế đường hấp thu nhanh." in joined
    assert "0.62" in joined
    assert "Tôi nên ăn gì?" in msgs[-1]["content"]


def test_advise_calls_llm_with_messages():
    seen = {}

    def fake_llm(messages):
        seen["messages"] = messages
        return "Hãy giảm đường [ada.txt]."

    assert advise(CTX, fake_llm) == "Hãy giảm đường [ada.txt]."
    assert seen["messages"][0]["role"] == "system"
