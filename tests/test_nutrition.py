import json

import pytest
from diacare.advisor import SYSTEM_PROMPT, build_messages
from diacare.bench import cited
from diacare.context import (ANSWER_RESERVE_TOKENS, DOC_LABEL_TOKENS, SYSTEM_RESERVE_TOKENS,
                             build_context, estimate_tokens)
from diacare.factory import FEATURES_ALL, ROOT, build_orchestrator, parse_features
from diacare.llm import DemoLLM, hash_embed_fn
from diacare.nutrition import (NutritionAgent, format_table, has_diacritics, is_nutrition_question,
                               load_foods, strip_accents)
from diacare.orchestrator import Orchestrator
from diacare.samples import LOW_RISK
from diacare.state import State

FOODS = load_foods(ROOT / "data" / "nutrition" / "vn_foods.json")
BY_NAME = {f["name"]: f for f in FOODS}
AGENT = NutritionAgent(FOODS)
KEYS = ("kcal", "carb_g", "fiber_g", "sugar_g", "protein_g", "fat_g")


def names(question):
    return [f["name"] for f, _, _ in AGENT.find_foods(question)]


def test_strip_accents_and_has_diacritics():
    assert strip_accents("Đường cơm trắng") == "Duong com trang"
    assert strip_accents("đ") == "d"
    assert has_diacritics("cơm") and has_diacritics("đường")
    assert not has_diacritics("com trang")


def test_find_foods_accented_and_unaccented():
    assert names("2 bát cơm trắng") == ["cơm trắng"]
    assert names("2 bat com trang") == ["cơm trắng"]
    assert names("Tôi ăn 1 quả chuối và 1 quả cam") == ["chuối", "cam"]


def test_cam_on_guard_and_word_boundary():
    assert names("cảm ơn bạn") == []
    assert names("tôi mua camera mới") == []
    assert names("camera moi") == []
    assert names("1 quả cam") == ["cam"]


def test_unaccented_alias_not_used_in_accented_question():
    # "com" là alias không dấu của cơm trắng; câu có dấu thì không dùng
    assert names("món com của tôi, có dấu: được") == []


def test_longest_match_blocks_inner_names():
    assert names("1 miếng dưa hấu") == ["dưa hấu"]
    assert names("100g thịt gà") == ["thịt gà"]
    assert names("1 ly nước cam vắt") == ["nước cam"]


def test_multiword_ascii_alias_in_accented_question():
    # gốc lỗi: alias ASCII "khoai lang" bị loại vì tên chính "khoai lang luộc" có dấu
    for q in ("Tôi uống 2 ly sữa đậu nành và ăn 150g khoai lang", "ăn khoai lang", "150 g khoai lang"):
        assert "khoai lang luộc" in names(q), q
    assert names("Tôi uống 2 ly sữa đậu nành và ăn 150g khoai lang") == ["sữa đậu nành", "khoai lang luộc"]
    assert first("ăn 150g khoai lang")["grams"] == 150


def test_each_food_at_most_once():
    assert names("cơm trắng, rồi lại cơm trắng") == ["cơm trắng"]


def test_duong_nutrient_query_is_not_food():
    assert names("Một lon nước ngọt có ga chứa bao nhiêu đường?") == ["nước ngọt có ga"]
    assert names("ăn gì để ổn định đường huyết") == []
    assert names("1 thìa đường") == ["đường"]


@pytest.mark.parametrize("question", [
    # câu thật trong benchmark Kaggle lần 3: bảng dinh dưỡng bị chèn sai vào các câu này
    "Bữa sáng nào phù hợp cho người có nguy cơ tiểu đường?",
    "Tôi nên làm gì để giảm nguy cơ mắc tiểu đường?",
    "Tôi đã được chẩn đoán đái tháo đường típ 2 năm ngoái.",
    "Tôi muốn bỏ thuốc tiểu đường có được không?",
    "Giá vàng hôm nay là bao nhiêu?",
    # các nghĩa khác thường gặp
    "bệnh dai thao duong",
    "con đường đi bộ gần nhà",
    "đánh giá chế độ ăn của tôi",
    "giá cả thực phẩm dạo này",
    "theo ý kiến cá nhân",
    "tôi cam kết tập thể dục",
    "giữ tinh thần lạc quan",
    "liên lạc với bác sĩ",
    "đọc nhãn thuốc và nhãn dinh dưỡng",
])
def test_other_word_senses_are_not_food(question):
    assert names(question) == []


@pytest.mark.parametrize("question,expected", [
    ("1 thìa đường", ["đường"]),
    ("cho đường vào cà phê", ["đường"]),
    ("1 đĩa giá đỗ xào", ["giá đỗ"]),
    ("ăn rau giá có tốt không", ["giá đỗ"]),
    ("100g cá", ["cá rô phi"]),
    ("1 quả cam", ["cam"]),
    ("1 nắm lạc rang", ["đậu phộng"]),
    ("ăn 10 quả nhãn", ["nhãn"]),
])
def test_food_senses_still_found(question, expected):
    assert names(question) == expected


def first(question):
    return AGENT.analyze(question)["items"][0]


def test_quantity_portions_and_grams():
    it = first("2 bát cơm trắng")
    assert it["grams"] == 2 * BY_NAME["cơm trắng"]["portion"]["grams"] == 300
    assert it["from_portion"] is True
    for q in ("200g bún", "200 g bún", "200 gram bún", "200 gr bún"):
        it = first(q)
        assert it["grams"] == 200 and it["from_portion"] is False
    assert first("1 lon nước ngọt")["grams"] == 330
    assert first("1,5 bát cơm trắng")["grams"] == 225
    assert first("0.5 quả chuối")["grams"] == 60
    assert first("ăn cơm trắng")["grams"] == 150  # không có số -> 1 khẩu phần
    assert first("2 bat com trang")["grams"] == 300
    assert first("hai bát cơm trắng")["grams"] == 150  # chữ không phải số: 1 khẩu phần


def test_fractions():
    assert first("Tôi ăn 1 đĩa rau muống và nửa quả xoài")["grams"] == 100
    res = AGENT.analyze("Tôi ăn 1 đĩa rau muống và nửa quả xoài")
    assert res["items"][1]["grams"] == 100  # 0.5 x 200
    assert first("nửa quả xoài")["grams"] == 100
    assert first("nửa xoài")["grams"] == 100
    assert first("1 bát rưỡi cơm trắng")["grams"] == 225
    assert first("1 bat ruoi com trang")["grams"] == 225
    assert first("nua bat com trang")["grams"] == 75
    assert first("rưỡi bát cơm trắng")["grams"] == 150  # "rưỡi" không có số: bỏ qua


def test_alias_display_name():
    it = first("1 bát phở")
    assert it["name"] == "phở" and it["food"] == "bún" and it["grams"] == 200
    it = first("1 bat pho")
    assert it["name"] == "phở" and it["food"] == "bún"
    it = first("2 bat com trang")
    assert it["name"] == "cơm trắng" and it["food"] == "cơm trắng"
    assert first("1 bat com")["name"] == "cơm"
    assert first("1 quả chuối")["name"] == "chuối" and first("1 quả chuối")["food"] == "chuối"
    text = format_table(AGENT.analyze("1 bat pho va nua qua xoai"))
    assert "- phở (số liệu của bún): 200 g (1 bát (phần bánh)) ->" in text
    assert "- xoài: 100 g" in text


def test_analyze_none_when_no_food():
    assert AGENT.analyze("Tập thể dục bao nhiêu là đủ?") is None


def test_totals_arithmetic_from_table():
    res = AGENT.analyze("2 bát cơm trắng và 1 quả chuối")
    assert res["source"] == "usda_fdc"
    rice, banana = BY_NAME["cơm trắng"], BY_NAME["chuối"]
    it = {i["name"]: i for i in res["items"]}
    for key in KEYS:
        exp_r = None if rice["per_100g"][key] is None else round(rice["per_100g"][key] * 300 / 100, 1)
        exp_b = None if banana["per_100g"][key] is None else round(banana["per_100g"][key] * 120 / 100, 1)
        assert it["cơm trắng"][key] == exp_r and it["chuối"][key] == exp_b
        vals = [v for v in (exp_r, exp_b) if v is not None]
        assert res["totals"][key] == (round(sum(vals), 1) if vals else None)


def test_none_nutrient_stays_none_and_skipped():
    res = AGENT.analyze("1 bìa đậu phụ và 1 quả chuối")
    tofu = next(i for i in res["items"] if i["name"] == "đậu phụ")
    assert BY_NAME["đậu phụ"]["per_100g"]["sugar_g"] is None and tofu["sugar_g"] is None
    banana = BY_NAME["chuối"]["per_100g"]["sugar_g"] * 120 / 100
    assert res["totals"]["sugar_g"] == round(banana, 1)
    only = AGENT.analyze("1 bìa đậu phụ")
    assert only["totals"]["sugar_g"] is None
    assert "không có số liệu" in format_table(only)


def test_format_table():
    text = format_table(AGENT.analyze("2 bát cơm trắng và 1 quả chuối"))
    assert text.splitlines()[0] == ("Bảng dinh dưỡng [usda_fdc] (USDA FoodData Central; "
                                    "khẩu phần là ước lượng):")
    assert "[usda_fdc]" in text and "ước lượng" in text
    assert "- cơm trắng: 300 g (2 × 1 bát) ->" in text
    assert "Tổng" in text.splitlines()[-1]


@pytest.mark.parametrize("q", [
    "Ăn gì để giảm cân?", "Thực đơn cho người tiểu đường", "Bữa tối nên thế nào", "1 bát cơm bao nhiêu carb",
    "Uống nước ngọt có sao không", "Tinh bột là gì", "khẩu phần hợp lý", "chế độ ăn nào tốt",
    "an gi de giam can", "thuc don tuan nay", "an uong the nao", "bao nhieu calo",
])
def test_is_nutrition_question_positive(q):
    assert is_nutrition_question(q, AGENT.analyze(q))


@pytest.mark.parametrize("q", [
    "Tập thể dục bao nhiêu là đủ?", "Tôi bị chóng mặt, phải làm sao?", "Viết bài thơ mùa thu",
    "chan thuong co sao khong", "Cảm ơn bạn", "Chăn ấm đắp thế nào",
])
def test_is_nutrition_question_negative(q):
    assert not is_nutrition_question(q, AGENT.analyze(q))


def test_is_nutrition_question_true_with_analysis_only():
    q = "1 quả chuối"
    assert is_nutrition_question(q, AGENT.analyze(q))


# ---------- context / advisor ----------

def state_with(nutrition, docs=()):
    return State(question="Q", profile={"BMI": 30}, docs=list(docs), nutrition=nutrition)


def test_state_default_nutrition_none():
    assert State(question="q", profile={}).nutrition is None


def test_context_without_nutrition_is_unchanged():
    ctx = build_context("advisor", state_with(None))
    assert ctx["nutrition_text"] == ""
    assert ctx["est_tokens"] == SYSTEM_RESERVE_TOKENS + estimate_tokens("Q")


def test_context_counts_nutrition_tokens():
    res = AGENT.analyze("2 bát cơm trắng")
    ctx = build_context("advisor", state_with(res))
    text = format_table(res)
    assert ctx["nutrition_text"] == text
    assert ctx["est_tokens"] == SYSTEM_RESERVE_TOKENS + estimate_tokens("Q") + estimate_tokens(text)


def test_nutrition_has_priority_over_docs():
    res = AGENT.analyze("2 bát cơm trắng")
    n_tokens = estimate_tokens(format_table(res))
    docs = [{"source": "a.txt", "text": "x" * 400}]
    doc_cost = estimate_tokens(docs[0]["text"]) + DOC_LABEL_TOKENS
    # cửa sổ đủ cho bảng dinh dưỡng nhưng không đủ cho tài liệu
    num_ctx = ANSWER_RESERVE_TOKENS + SYSTEM_RESERVE_TOKENS + estimate_tokens("Q") + n_tokens + doc_cost - 1
    ctx = build_context("advisor", state_with(res, docs), num_ctx=num_ctx)
    assert ctx["nutrition_text"] and ctx["docs"] == []
    # còn đủ chỗ thì giữ cả hai
    ctx = build_context("advisor", state_with(res, docs), num_ctx=num_ctx + 1)
    assert ctx["docs"] == docs


def test_advisor_message_contains_table_before_docs():
    res = AGENT.analyze("2 bát cơm trắng")
    ctx = build_context("advisor", state_with(res, [{"source": "a.txt", "text": "Ăn rau."}]))
    user = build_messages(ctx)[-1]["content"]
    assert format_table(res) in user
    assert user.index("Bảng dinh dưỡng") < user.index("Tài liệu tham khảo:")
    assert "[usda_fdc]" in SYSTEM_PROMPT and "ước lượng" in SYSTEM_PROMPT
    plain = build_messages(build_context("advisor", state_with(None)))[-1]["content"]
    assert "Bảng dinh dưỡng" not in plain


# ---------- orchestrator ----------

class FakePredictor:
    def predict(self, profile):
        return 0.1


class FakeRetriever:
    def search(self, query, k=4):
        return [{"source": "ada.txt", "text": "Hạn chế đường."}]


def make_orch(tmp_path, agent=AGENT):
    calls = []

    def llm(messages):
        calls.append(messages)
        return "ok"

    orch = Orchestrator(FakePredictor(), FakeRetriever(), llm, log_path=tmp_path / "r.jsonl",
                        nutrition_agent=agent)
    return orch, calls


def test_orchestrator_puts_table_in_prompt_and_logs(tmp_path):
    orch, calls = make_orch(tmp_path)
    state = orch.run(State(question="2 bát cơm trắng và 1 quả chuối có bao nhiêu carb?", profile=LOW_RISK))
    assert state.nutrition and "[usda_fdc]" in calls[0][-1]["content"]
    orch.run(State(question="Tập thể dục bao nhiêu là đủ?", profile=LOW_RISK))
    assert "Bảng dinh dưỡng" not in calls[1][-1]["content"]
    rec = [json.loads(line) for line in (tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rec[0]["nutrition_items"] == ["cơm trắng", "chuối"]
    assert rec[1]["nutrition_items"] == []


def test_orchestrator_keyword_only_has_no_table(tmp_path):
    orch, calls = make_orch(tmp_path)
    state = orch.run(State(question="Ăn gì để giảm cân?", profile=LOW_RISK))
    assert state.nutrition is None and "Bảng dinh dưỡng" not in calls[0][-1]["content"]


def test_orchestrator_without_agent(tmp_path):
    orch, calls = make_orch(tmp_path, agent=None)
    state = orch.run(State(question="2 bát cơm trắng", profile=LOW_RISK))
    assert state.nutrition is None and "Bảng dinh dưỡng" not in calls[0][-1]["content"]


# ---------- bench.cited ----------

def test_cited_with_usda_fdc():
    res = AGENT.analyze("1 quả chuối")
    assert cited(State(question="q", profile={}, nutrition=res, draft="Theo [usda_fdc] ..."))
    assert not cited(State(question="q", profile={}, nutrition=res, draft="không trích"))
    assert not cited(State(question="q", profile={}, nutrition=None, draft="Theo [usda_fdc] ..."))


# ---------- feature flags ----------

def test_parse_features(monkeypatch):
    from diacare.factory import FEATURES_DEFAULT
    monkeypatch.delenv("DIACARE_FEATURES", raising=False)
    assert parse_features() == set(FEATURES_DEFAULT) == {"nutrition", "memory", "labs"}  # hybrid tắt mặc định
    assert parse_features("v2") == set(FEATURES_DEFAULT)
    assert parse_features("all") == set(FEATURES_ALL)
    for v in ("v1", "none", "", " V1 "):
        assert parse_features(v) == set()
    assert parse_features("nutrition") == {"nutrition"}
    with pytest.raises(ValueError):
        parse_features("nutrition,foo")
    monkeypatch.setenv("DIACARE_FEATURES", "v1")
    assert parse_features() == set()
    monkeypatch.setenv("DIACARE_FEATURES", "nutrition")
    assert parse_features() == {"nutrition"}


def test_build_orchestrator_features(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ada.txt").write_text("Ăn nhiều rau xanh và hạn chế đường.", encoding="utf-8")

    def build(features):
        return build_orchestrator(kb_dir=kb, model_dir=ROOT / "models", log_path=tmp_path / "r.jsonl",
                                  llm=DemoLLM(), embed_fn=hash_embed_fn(), features=features)

    assert build("v1").nutrition_agent is None
    orch = build("nutrition")
    assert isinstance(orch.nutrition_agent, NutritionAgent)
    state = orch.run(State(question="1 quả chuối có bao nhiêu carb?", profile=LOW_RISK))
    assert state.nutrition and "system_error" not in state.flags
