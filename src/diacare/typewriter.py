"""Hiệu ứng gõ chữ cho câu trả lời đang stream.

SafeStream chỉ nhả từng câu đã qua kiểm tra an toàn, nên nếu vẽ thẳng thì chữ hiện theo từng cục cả câu.
Typewriter nhận phần văn bản đã được phép hiện và gõ phần mới ra màn hình từng từ một với nhịp đều,
nên người dùng thấy chữ chảy liên tục mà bộ lọc an toàn vẫn giữ nguyên.
"""
import re
import time

_WORD = re.compile(r"\s*\S+\s*|\s+")  # khoảng trắng đầu đi cùng từ kế tiếp, không thành một khung riêng


class Typewriter:
    """render(text) vẽ văn bản; gọi tw(approved) mỗi khi phần được phép hiện dài thêm.

    step_s: nhịp tối đa giữa hai từ. max_s: thời gian tối đa để gõ một đoạn mới, đoạn dài thì gõ nhanh hơn
    để không chậm hơn tốc độ model sinh chữ.
    """

    def __init__(self, render, step_s=0.035, max_s=0.9, sleep=time.sleep, cursor=" ▌"):
        self.render, self.step_s, self.max_s, self.sleep, self.cursor = render, step_s, max_s, sleep, cursor
        self.shown = ""

    def __call__(self, approved):
        if not approved.startswith(self.shown):  # văn bản bị thay hẳn: vẽ lại ngay
            self.shown = approved
            self.render(self.shown + self.cursor)
            return
        words = _WORD.findall(approved[len(self.shown):])
        if not words:
            return
        delay = min(self.step_s, self.max_s / len(words))
        for w in words:
            self.shown += w
            self.render(self.shown + self.cursor)
            if delay > 0:
                self.sleep(delay)

    def finish(self):
        """Bỏ con trỏ nhấp nháy khi đã xong."""
        self.render(self.shown)
