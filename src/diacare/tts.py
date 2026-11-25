"""Đọc to câu trả lời bằng giọng tiếng Việt chạy trên máy (Piper, giọng vi_VN-vais1000-medium, CC BY 4.0).

Vì sao không dùng giọng của trình duyệt (Web Speech API): máy phát triển (Windows) không có giọng tiếng Việt nào, nên
trình duyệt đọc bằng giọng tiếng Anh hoặc không đọc; Edge có giọng tiếng Việt nhưng là giọng trực tuyến, câu trả lời
(có thông tin sức khoẻ) bị gửi tới Microsoft. Piper chạy offline bằng onnxruntime, đo trên máy phát triển: khoảng 1 giây
để tạo 21 giây âm thanh (lần gọi đầu chậm hơn vì nạp mô hình).

Mô hình: biến DIACARE_TTS_MODEL (đường dẫn tệp .onnx, cạnh tệp .onnx.json), không có thì tìm trong bộ đệm Hugging Face
(rhasspy/piper-voices). Tải lần đầu (khoảng 61 MB):
    python -c "from huggingface_hub import hf_hub_download as d; [d('rhasspy/piper-voices', 'vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx' + e) for e in ('', '.json')]"
"""
import io
import os
import re
import threading
import wave

REPO = "rhasspy/piper-voices"
VOICE = "vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx"


class TTSUnavailable(RuntimeError):
    pass


def model_path():
    env = os.environ.get("DIACARE_TTS_MODEL")
    if env:
        return env if os.path.exists(env) else None
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return None
    path = try_to_load_from_cache(REPO, VOICE)
    return path if isinstance(path, str) and os.path.exists(path + ".json") else None


# ---- chuẩn hoá chữ trước khi đọc: đơn vị, số thập phân, ký hiệu ----
_UNITS = [
    (r"mmol\s*/\s*l\b", "mi li mol trên lít"), (r"mg\s*/\s*dl\b", "mi li gam trên đề xi lít"),
    (r"mmhg\b", "mi li mét thuỷ ngân"), (r"kcal\b", "ki lô ca lo"), (r"(?<=\d)\s*kg\b", " ki lô gam"),
    (r"(?<=\d)\s*g\b", " gam"), (r"(?<=\d)\s*ml\b", " mi li lít"), (r"hba1c", "h b a một c"),
]


def normalize(text):
    """Chữ để đọc: bỏ nhãn nguồn [tệp], chú thích, dấu markdown; đọc đơn vị, "6,8" thành "6 phẩy 8", "%" thành
    "phần trăm", khoảng "4,4–7,2" thành "4 phẩy 4 đến 7 phẩy 2"."""
    from diacare.present import split_disclaimer
    t, _ = split_disclaimer(text or "")  # lời miễn trừ vẫn hiện trên màn hình, không đọc lại mỗi câu
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰*_`#>|]", "", t)
    t = "\n".join(line for line in t.splitlines() if not line.strip().lower().startswith("nguồn"))
    for pat, rep in _UNITS:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    t = re.sub(r"(\d)\s*[–—-]\s*(\d)", r"\1 đến \2", t)
    t = re.sub(r"(\d)[,.](\d)", r"\1 phẩy \2", t)
    t = t.replace("%", " phần trăm").replace("/", " trên ")
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", t).strip()


class Speaker:
    def __init__(self, path=None):
        self.path = path or model_path()
        self._voice = None
        self._lock = threading.Lock()

    @property
    def available(self):
        return bool(self.path)

    def _load(self):
        if not self.path:
            raise TTSUnavailable("Chưa có giọng đọc tiếng Việt (Piper). Xem hướng dẫn tải trong src/diacare/tts.py.")
        try:
            from piper import PiperVoice
        except ImportError as e:
            raise TTSUnavailable("Chưa cài piper-tts (pip install piper-tts).") from e
        return PiperVoice.load(self.path)

    def wav(self, text):
        """WAV (bytes) đọc `text` đã chuẩn hoá. Chữ rỗng thì trả None."""
        clean = normalize(text)
        if not clean:
            return None
        with self._lock:
            if self._voice is None:
                self._voice = self._load()
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                self._voice.synthesize_wav(clean, w)
        return buf.getvalue()
