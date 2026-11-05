import math

from diacare.llm import DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT

CHARS_PER_TOKEN = 4.0          # đo thật trên Kaggle (qwen2.5) là ~4.64; giữ thấp hơn để ước lượng vẫn bảo thủ
ANSWER_RESERVE_TOKENS = DEFAULT_NUM_PREDICT  # chừa chỗ cho câu trả lời = giới hạn num_predict của LLM
SYSTEM_RESERVE_TOKENS = 250     # system prompt + nhãn tài liệu + dòng mức nguy cơ
HISTORY_TOKEN_BUDGET = 800
DOC_LABEL_TOKENS = 10           # chi phí nhãn [tên_file] cho mỗi tài liệu


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
            "est_tokens": SYSTEM_RESERVE_TOKENS + question_tokens + history_tokens + docs_tokens,
        }
    if agent == "rule":
        return {"risk": state.risk, "draft": state.draft, "profile": state.profile, "question": state.question}
    raise ValueError(f"unknown agent: {agent}")
