"""Phát hiện prompt injection ở đầu vào: câu hỏi của người dùng và đoạn tài liệu truy hồi từ kho.

Đây là lớp phụ. Lớp chính vẫn là Rules chạy trên ĐẦU RA (rules.apply_rules): dù prompt bị lái thế nào, câu khuyên đổi
thuốc vẫn bị loại và câu miễn trừ vẫn được thêm. Lớp này làm hai việc mà Rules không làm:

- Tài liệu trong kho chứa câu ra lệnh cho mô hình ("ignore previous instructions", "bỏ qua mọi hướng dẫn") bị loại
  trước khi tới Advisor (cờ `kb_injection_filtered`). Tài liệu y khoa thật không có những câu này.
- Câu hỏi có dấu hiệu lái mô hình được gắn cờ `prompt_injection_suspected` để ghi log và thống kê. Câu hỏi vẫn được
  trả lời: so khớp mẫu có thể nhầm, và người hỏi không mất gì khi các rào chắn khác vẫn chạy.

So khớp mẫu chỉ bắt được cách nói đã biết; xem tests/test_injection.py cho các trường hợp lọt đã ghi nhận.
"""
import re
import unicodedata

_PATTERNS = (
    ("ignore_instructions",
     r"(?:bỏ qua|phớt lờ|quên(?: hết| đi)?|đừng (?:theo|tuân theo)|không cần (?:theo|tuân theo))"
     r"(?:\W+\w+){0,3}?\W+(?:hướng dẫn|chỉ dẫn|chỉ thị|quy tắc|luật|lời nhắc|nguyên tắc)"
     r"|(?:ignore|disregard|forget|override)(?:\W+\w+){0,3}?\W+(?:instructions?|rules?|prompts?|guidelines?)"),
    ("role_override",
     r"(?:bây giờ|từ giờ|từ bây giờ) (?:bạn|mày|cậu) (?:là|sẽ là|hãy là|đóng vai)"
     r"|you are now|act as (?:a|an|my)\b|pretend (?:to be|you are)|đóng vai (?:một |là )?(?:bác sĩ|dược sĩ|chuyên gia)"),
    ("system_prompt",
     r"system prompt|lời nhắc hệ thống|prompt hệ thống|(?:^|\n)\s*(?:system|assistant|developer)\s*:"
     r"|<\s*/?\s*(?:system|instructions?)\s*>|\[\s*(?:system|inst)\s*\]"),
    ("jailbreak",
     r"jailbreak|developer mode|chế độ (?:nhà phát triển|không giới hạn|tự do)|\bDAN\b|không (?:bị|có) giới hạn"),
    ("drop_safeguards",
     r"(?:không cần|đừng|bỏ|khỏi)(?:\W+\w+){0,3}?\W+(?:miễn trừ|disclaimer|cảnh báo|lời nhắc (?:đi khám|hỏi bác sĩ))"
     r"|(?:without|no|skip the) (?:any )?(?:disclaimer|warnings?)"),
)
_RX = [(name, re.compile(p, re.IGNORECASE)) for name, p in _PATTERNS]


def injection_signals(text):
    """Danh sách tên mẫu khớp (rỗng = không thấy dấu hiệu)."""
    t = unicodedata.normalize("NFC", text or "")
    return [name for name, rx in _RX if rx.search(t)]


def filter_docs(docs):
    """Tách các đoạn tài liệu có câu ra lệnh cho mô hình. Trả (giữ lại, bị loại)."""
    kept, dropped = [], []
    for d in docs:
        (dropped if injection_signals(d.get("text", "")) else kept).append(d)
    return kept, dropped
