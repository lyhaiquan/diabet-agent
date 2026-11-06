import math

from diacare.llm import DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT
from diacare.kg import format_kg
from diacare.labs import format_labs
from diacare.memory import format_memory, has_diagnosis
from diacare.nutrition import format_table

CHARS_PER_TOKEN = 4.0          # đo thật trên Kaggle (qwen2.5) là ~4.64; giữ thấp hơn để ước lượng vẫn bảo thủ
ANSWER_RESERVE_TOKENS = DEFAULT_NUM_PREDICT  # chừa chỗ cho câu trả lời = giới hạn num_predict của LLM
SYSTEM_RESERVE_TOKENS = 250     # system prompt + nhãn tài liệu + dòng mức nguy cơ
HISTORY_TOKEN_BUDGET = 800
MEMORY_TOKEN_BUDGET = 150          # trí nhớ dài hạn về bệnh nhân, tính trước dinh dưỡng và tài liệu
DOC_LABEL_TOKENS = 10           # chi phí nhãn [tên_file] cho mỗi tài liệu
KG_TOKEN_BUDGET = 250           # tri thức từ đồ thị: tối đa 3 yếu tố, mỗi yếu tố một dòng


def estimate_tokens(text):
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def build_context(agent, state, num_ctx=DEFAULT_NUM_CTX):
    """Mỗi agent chỉ nhìn thấy phần state nó cần."""
    if agent == "predictor":
        return {"profile": state.profile}
    if agent == "advisor":
        history, history_tokens = [], 0
        for m in reversed(state.history):
            cost = estimate_tokens(m["content"])
            if history_tokens + cost > HISTORY_TOKEN_BUDGET:
                break
            history.insert(0, m)
            history_tokens += cost
        question_tokens = estimate_tokens(state.question)
        remaining = (num_ctx - ANSWER_RESERVE_TOKENS - SYSTEM_RESERVE_TOKENS
                     - question_tokens - history_tokens)
        memory_text, memory_tokens = "", 0
        if state.memory:  # ưu tiên cao nhất: bỏ sự kiện cũ nhất trước nếu vượt ngân sách
            facts = list(state.memory)
            while facts and estimate_tokens(format_memory(facts)) > MEMORY_TOKEN_BUDGET:
                facts.pop(0)
            if facts:
                memory_text = format_memory(facts)
                memory_tokens = estimate_tokens(memory_text)
                remaining -= memory_tokens
        lab_text, lab_tokens = "", 0
        if state.labs:  # kết quả xét nghiệm: ngay sau trí nhớ, trước dinh dưỡng và tài liệu
            lab_text = format_labs(state.labs)
            lab_tokens = estimate_tokens(lab_text)
            remaining -= lab_tokens
        nutrition_text, nutrition_tokens = "", 0
        if state.nutrition:  # ưu tiên cao hơn tài liệu truy xuất
            nutrition_text = format_table(state.nutrition)
            nutrition_tokens = estimate_tokens(nutrition_text)
            remaining -= nutrition_tokens
        kg_text, kg_tokens = "", 0
        if state.kg and state.kg.get("lines"):  # sau dinh dưỡng, trước tài liệu; bỏ dòng cuối nếu vượt ngân sách
            lines = list(state.kg["lines"])
            while lines and estimate_tokens(format_kg({**state.kg, "lines": lines})) > KG_TOKEN_BUDGET:
                lines.pop()
            if lines:
                kg_text = format_kg({**state.kg, "lines": lines})
                kg_tokens = estimate_tokens(kg_text)
                remaining -= kg_tokens
        docs, docs_tokens = [], 0
        if remaining > 0:
            for d in state.docs:
                cost = estimate_tokens(d["text"]) + DOC_LABEL_TOKENS
                if cost > remaining:
                    break
                docs.append(d)
                docs_tokens += cost
                remaining -= cost
        return {
            "question": state.question,
            "risk": state.risk,
            "docs": docs,
            "history": history,
            "memory_text": memory_text,
            "nutrition_text": nutrition_text,
            "lab_text": lab_text,
            "kg_text": kg_text,
            "est_tokens": (SYSTEM_RESERVE_TOKENS + question_tokens + history_tokens + memory_tokens
                           + lab_tokens + nutrition_tokens + kg_tokens + docs_tokens),
        }
    if agent == "rule":
        return {"risk": state.risk, "draft": state.draft, "profile": state.profile, "question": state.question,
                "diagnosed": has_diagnosis(state.memory), "labs": list(state.labs)}
    raise ValueError(f"unknown agent: {agent}")
