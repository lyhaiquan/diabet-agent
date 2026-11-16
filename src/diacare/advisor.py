import re

from diacare.rules import risk_band

SYSTEM_PROMPT = (
    "Bạn là trợ lý thông tin sức khỏe về bệnh tiểu đường. "
    "Chỉ dùng tài liệu được cung cấp và trích nguồn dạng [tên_file]. "
    "Nếu tài liệu không đủ, hãy nói rõ là chưa đủ thông tin. "
    "Không kê đơn, không hướng dẫn thay đổi liều thuốc hoặc insulin."
    " Không nêu điểm nguy cơ dưới dạng phần trăm hay xác suất; chỉ nói mức thấp, trung bình hoặc cao."
    " Cân nhắc thông tin đã biết về người dùng; nếu người dùng đang dùng thuốc thì không đề xuất thay đổi thuốc."
    " Khi dùng số liệu dinh dưỡng, trích nguồn [usda_fdc] và nói rõ khẩu phần là ước lượng."
    " Khi có kết quả xét nghiệm, giải thích chỉ số so với ngưỡng tham khảo, trích nguồn [ada_2024],"
    " nói rõ đây không phải chẩn đoán và cần bác sĩ xác nhận."
    " Khi có nhật ký tự theo dõi, dựa vào số liệu trong đó để trả lời sát với người dùng (nêu con số cụ thể),"
    " giữ nguyên nhận định có sẵn trong nhật ký (cao hơn, thấp hơn hay trong mục tiêu), không tự so sánh lại,"
    " nhắc rằng bác sĩ có thể đặt mục tiêu riêng; không suy ra hay đề xuất liều thuốc từ nhật ký."
    " Nếu nhật ký có hạ đường huyết hoặc chỉ số rất cao, khuyên người dùng báo bác sĩ."
)


def build_messages(ctx):
    docs = "\n\n".join(f"[{d['source']}]\n{d['text']}" for d in ctx["docs"]) or "(không có tài liệu)"
    band = risk_band(ctx["risk"]) if ctx["risk"] is not None else "chưa có"
    nutrition = ctx.get("nutrition_text") or ""
    nutrition_block = f"{nutrition}\n\n" if nutrition else ""
    memory = ctx.get("memory_text") or ""
    memory_block = f"{memory}\n\n" if memory else ""
    labs = ctx.get("lab_text") or ""
    lab_block = f"{labs}\n\n" if labs else ""
    journal = ctx.get("journal_text") or ""
    journal_block = f"{journal}\n\n" if journal else ""
    kg = ctx.get("kg_text") or ""
    kg_block = f"{kg}\n\n" if kg else ""
    rl = ctx.get("rl_text") or ""
    rl_block = f"{rl}\n\n" if rl else ""
    user = (
        f"{memory_block}"
        f"{lab_block}"
        f"{journal_block}"
        f"Mức nguy cơ tiểu đường ước tính của người dùng: {band}\n\n"
        f"{nutrition_block}"
        f"{kg_block}"
        f"{rl_block}"
        f"Tài liệu tham khảo:\n{docs}\n\n"
        f"Câu hỏi: {ctx['question']}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, *ctx["history"],
            {"role": "user", "content": user}]


_SENT_END = re.compile(r"[.!?…](?:\*\*|\*|\)|\"|”)*(?=\s|$)")


def trim_incomplete(text):
    """Bỏ phần cuối bị cắt khi LLM chạm giới hạn token: giữ tới hết câu trọn vẹn cuối cùng.

    Dòng cuối dở dang: giữ tới dấu kết thúc câu cuối trong dòng, không có thì bỏ cả dòng. Sau đó bỏ các dòng tiêu đề
    còn treo ở cuối (kết thúc bằng dấu hai chấm, hoặc chỉ là chữ in đậm) vì phần nội dung của chúng đã bị cắt."""
    lines = text.rstrip().split("\n")
    last = lines[-1]
    ends = list(_SENT_END.finditer(last))
    if ends and ends[-1].end() == len(last.rstrip()):
        return text.rstrip()  # đã kết thúc trọn câu
    lines[-1] = last[:ends[-1].end()] if ends else ""
    while lines and (not lines[-1].strip() or lines[-1].rstrip().rstrip("*").endswith(":")
                     or re.fullmatch(r"\s*(?:[-*+]|\d+\.)?\s*\*\*[^*]+\*\*\s*", lines[-1])):
        lines.pop()
    return "\n".join(lines).rstrip()


def advise(ctx, llm, on_token=None):
    if on_token is None:  # LLM giả trong test có thể không nhận on_token
        return llm(build_messages(ctx))
    return llm(build_messages(ctx), on_token=on_token)
