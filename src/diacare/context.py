MAX_HISTORY_TURNS = 6
MAX_DOC_CHARS = 3000


def build_context(agent, state):
    """Mỗi agent chỉ nhìn thấy phần state nó cần."""
    if agent == "predictor":
        return {"profile": state.profile}
    if agent == "advisor":
        docs, used = [], 0
        for d in state.docs:
            if used + len(d["text"]) > MAX_DOC_CHARS:
                break
            docs.append(d)
            used += len(d["text"])
        return {
            "question": state.question,
            "risk": state.risk,
            "docs": docs,
            "history": state.history[-MAX_HISTORY_TURNS:],
        }
    if agent == "rule":
        return {"risk": state.risk, "draft": state.draft, "profile": state.profile, "question": state.question}
    raise ValueError(f"unknown agent: {agent}")
