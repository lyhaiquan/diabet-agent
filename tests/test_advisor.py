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
    assert "cao" in joined
    assert "0.62" not in joined
    assert "Tôi nên ăn gì?" in msgs[-1]["content"]


def test_advise_calls_llm_with_messages():
    seen = {}

    def fake_llm(messages):
        seen["messages"] = messages
        return "Hãy giảm đường [ada.txt]."

    assert advise(CTX, fake_llm) == "Hãy giảm đường [ada.txt]."
    assert seen["messages"][0]["role"] == "system"


def test_risk_none_shows_chua_co():
    msgs = build_messages(dict(CTX, risk=None))
    assert "chưa có" in " ".join(m["content"] for m in msgs)


def test_trim_incomplete_drops_cut_sentence_and_hanging_heading():
    from diacare.advisor import trim_incomplete
    cut = ("Nên ăn nhiều rau [ada.txt].\n\n"
           "- **Kiểm tra đường huyết:** đo HbA1c định kỳ.\n"
           "- **Tham khảo ý kiến bác sĩ:** Đảm")
    assert trim_incomplete(cut) == "Nên ăn nhiều rau [ada.txt].\n\n- **Kiểm tra đường huyết:** đo HbA1c định kỳ."
    # câu dở trong cùng dòng: giữ tới dấu chấm cuối; số thập phân 7.8 không bị coi là hết câu
    assert trim_incomplete("Đường huyết 7.8 mmol/L là cao. Bạn nên đi kh") == "Đường huyết 7.8 mmol/L là cao."
    # tiêu đề treo không còn nội dung
    assert trim_incomplete("Ăn ít tinh bột.\n\n**Gợi ý thêm:**\n- Rau") == "Ăn ít tinh bột."
    # đã trọn câu thì giữ nguyên
    assert trim_incomplete("Uống đủ nước!") == "Uống đủ nước!"


def test_citation_reminder_is_last_and_uses_real_labels():
    from diacare.advisor import LENGTH_REMINDER, citation_reminder
    ctx = dict(CTX, docs=[{"source": "ada.txt", "text": "a"}, {"source": "who.txt", "text": "b"},
                          {"source": "ada.txt", "text": "c"}], nutrition_text="Cơm: 130 kcal [usda_fdc]")
    last = build_messages(ctx)[-1]["content"]
    assert last.rstrip().endswith(LENGTH_REMINDER)  # dặn độ dài là dòng cuối
    assert last.index("Câu hỏi:") < last.index("Yêu cầu trình bày") < last.index(LENGTH_REMINDER)
    assert '"... [ada.txt]."' in last and "[ada.txt], [who.txt], [usda_fdc]" in last
    assert citation_reminder(dict(CTX, docs=[])) == ""  # không có tài liệu thì không đòi trích


def test_voice_mode_asks_for_short_spoken_answer():
    from diacare.advisor import LENGTH_REMINDER, VOICE_REMINDER, build_messages
    ctx = {"docs": [{"source": "a.txt", "text": "x"}], "risk": None, "question": "Đi bộ bao lâu?", "history": []}
    assert LENGTH_REMINDER in build_messages(ctx)[-1]["content"]
    voice = build_messages(dict(ctx, voice=True))[-1]["content"]
    assert VOICE_REMINDER in voice and LENGTH_REMINDER not in voice and "[a.txt]" in voice
