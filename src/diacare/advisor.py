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
    user = (
        f"{memory_block}"
        f"{lab_block}"
        f"Mức nguy cơ tiểu đường ước tính của người dùng: {band}\n\n"
        f"{nutrition_block}"
        f"Tài liệu tham khảo:\n{docs}\n\n"
        f"Câu hỏi: {ctx['question']}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, *ctx["history"],
            {"role": "user", "content": user}]


def advise(ctx, llm):
    return llm(build_messages(ctx))
