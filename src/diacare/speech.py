"""Giọng nói: giải mã WAV từ trình duyệt, nhận dạng tiếng Việt (PhoWhisper của VinAI), đọc số đo trong câu nói.

- Âm thanh KHÔNG được lưu: nhận bytes, chuyển thành chữ trong bộ nhớ rồi bỏ đi.
- Trình duyệt tự ghi WAV PCM 16 bit, 16 kHz, nên máy chủ không cần ffmpeg.
- Mô hình: vinai/PhoWhisper-small (BSD-3), chạy CPU. Đặt DIACARE_ASR=demo để dùng bộ nhận dạng giả lập (test, demo).
- Số đo nghe được chỉ là ĐỀ XUẤT: giao diện luôn hỏi lại người dùng trước khi lưu, vì nhận dạng có thể nghe nhầm
  ("ba phẩy tám" thành "tám phẩy ba").
"""
import io
import os
import re
import threading
import unicodedata
import wave

import numpy as np

SAMPLE_RATE = 16000
MAX_SECONDS = 60
DEFAULT_MODEL = "vinai/PhoWhisper-small"
GENERATE = {"language": "vi", "task": "transcribe", "max_new_tokens": 160, "num_beams": 1}  # 60 giây nói ~ dưới 160 token


class AudioError(ValueError):
    pass


# ---- âm thanh ---------------------------------------------------------------------

def decode_wav(data):
    """WAV PCM 16 bit (mono hoặc stereo, tần số bất kỳ) -> mảng float32 mono 16 kHz trong [-1, 1]."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if width != 2:
                raise AudioError("Chỉ nhận WAV PCM 16 bit.")
            if n / max(rate, 1) > MAX_SECONDS + 1:
                raise AudioError(f"Đoạn ghi âm dài quá {MAX_SECONDS} giây.")
            raw = w.readframes(n)
    except (wave.Error, EOFError) as exc:
        raise AudioError("Tệp âm thanh không phải WAV hợp lệ.") from exc
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(audio):
        t_new = np.arange(int(len(audio) * SAMPLE_RATE / rate)) / SAMPLE_RATE
        audio = np.interp(t_new, np.arange(len(audio)) / rate, audio).astype(np.float32)
    if len(audio) < SAMPLE_RATE * 0.3:
        raise AudioError("Đoạn ghi âm quá ngắn, hãy giữ nút lâu hơn một chút.")
    if float(np.abs(audio).max()) < 0.01:
        raise AudioError("Không nghe thấy tiếng. Kiểm tra micro rồi thử lại.")
    return audio


class Transcriber:
    """Nạp mô hình ở lần dùng đầu tiên (mất vài giây), sau đó dùng lại. Một lượt nhận dạng mỗi lúc."""

    def __init__(self, model=None):
        self.model_id = model or os.environ.get("DIACARE_ASR_MODEL") or DEFAULT_MODEL
        self._pipe = None
        self._lock = threading.Lock()

    def _load(self):
        from transformers import pipeline
        from transformers.utils import logging as hf_logging
        hf_logging.set_verbosity_error()  # bỏ cảnh báo cấu hình của checkpoint, không ảnh hưởng kết quả
        pipe = pipeline("automatic-speech-recognition", model=self.model_id, device=-1)
        pipe({"raw": np.zeros(SAMPLE_RATE, dtype=np.float32), "sampling_rate": SAMPLE_RATE},
             generate_kwargs=GENERATE)  # chạy nháp một lần: lượt đầu của người dùng không phải chờ khởi động
        return pipe

    def __call__(self, audio):
        with self._lock:
            if self._pipe is None:
                self._pipe = self._load()
            out = self._pipe({"raw": audio, "sampling_rate": SAMPLE_RATE}, generate_kwargs=GENERATE)
        return clean_transcript(out["text"])


class DemoTranscriber:
    """Không cần mô hình: trả lại câu cố định (đặt bằng DIACARE_ASR_DEMO_TEXT)."""
    model_id = "demo"

    def __init__(self, text=None):
        self.text = text or os.environ.get("DIACARE_ASR_DEMO_TEXT") or "Đường huyết sáng nay lúc đói sáu phẩy tám"

    def __call__(self, audio):
        return self.text


def make_transcriber(kind=None):
    kind = (kind or os.environ.get("DIACARE_ASR") or "phowhisper").lower()
    return DemoTranscriber() if kind == "demo" else Transcriber()


def clean_transcript(text):
    text = unicodedata.normalize("NFC", text or "").strip()
    return re.sub(r"\s+", " ", text)


# ---- số đọc bằng chữ -> chữ số ------------------------------------------------------

_DIGITS = {"không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "lăm": 5, "nhăm": 5,
           "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9}
_TENS = {"mười": "ten", "mươi": "x10"}
_FILLER = {"linh", "lẻ"}
_DECIMAL = {"phẩy", "chấm"}
_NUMBER_WORDS = set(_DIGITS) | set(_TENS) | _FILLER | _DECIMAL | {"trăm", "rưỡi"}
_TOKEN = re.compile(r"\d+(?:[.,]\d+)?|[^\W\d_]+|[^\s\w]", re.UNICODE)


def _int_of(tokens):
    """Phần nguyên đọc bằng chữ: 'một trăm hai mươi lăm' -> 125, 'sáu tám' -> 68, 'một trăm hai' -> 120."""
    hundreds, cur, prev = 0, 0, None
    after_hundred = []
    for t in tokens:
        if t == "trăm":
            hundreds += (cur or 1) * 100
            cur, prev = 0, "trăm"
            continue
        if hundreds:
            after_hundred.append(t)
        if t in _FILLER:
            prev = t
        elif t == "mười":
            cur += 10
            prev = t
        elif t == "mươi":
            cur = (cur or 1) * 10
            prev = t
        else:
            d = _DIGITS[t] if t in _DIGITS else int(t)
            if prev in ("digit",) and t in _DIGITS:
                cur = cur * 10 + d  # đọc từng chữ số: "sáu tám" = 68
            else:
                cur += d
            prev = "digit"
    # "một trăm hai" (không có "mươi") nghĩa là 120 trong cách nói thường ngày
    if hundreds and len(after_hundred) == 1 and after_hundred[0] in _DIGITS:
        cur *= 10
    return hundreds + cur


def _run_to_number(run):
    if len(run) == 1 and run[0] in ("không", "năm", "tư", "ba", "một", "lăm", "mốt") and not run[0].isdigit():
        return None  # một chữ đứng riêng hay là chữ thường ("không đo", "năm nay"), không đổi
    words = list(run)
    half = words[-1] == "rưỡi"
    if half:
        words = words[:-1]
    if any(w in _DECIMAL for w in words):
        i = next(i for i, w in enumerate(words) if w in _DECIMAL)
        int_part, frac = words[:i], words[i + 1:]
        if not int_part or not frac:
            return None
        if all(w in _DIGITS or w.isdigit() for w in frac):
            frac_s = "".join(str(_DIGITS[w]) if w in _DIGITS else w for w in frac)
        else:
            frac_s = str(_int_of(frac))
        return f"{_int_of(int_part)}.{frac_s}"
    if not words:
        return None
    value = _int_of(words)
    return f"{value}.5" if half else str(value)


def words_to_numbers(text):
    """Đổi số đọc bằng chữ trong câu thành chữ số: 'sáu phẩy tám' -> '6.8'; '6,8' -> '6.8'."""
    tokens = _TOKEN.findall(unicodedata.normalize("NFC", text).lower())
    out, run = [], []

    def flush():
        if run:
            num = _run_to_number(run)
            out.extend([num] if num is not None else run)
            run.clear()

    for t in tokens:
        is_digit_token = bool(re.fullmatch(r"\d+", t))
        if t in _NUMBER_WORDS or is_digit_token:
            run.append(t)
        elif re.fullmatch(r"\d+[.,]\d+", t):
            flush()
            out.append(t.replace(",", "."))
        else:
            flush()
            out.append(t)
    flush()
    return " ".join(out)


# ---- đọc số đo trong câu ---------------------------------------------------------------

_NUM = r"(\d+(?:\.\d+)?)"
_BP = re.compile(r"(?:huyết áp|áp huyết)\D{0,25}?" + _NUM + r"\s*(?:trên|/|-|và)\s*" + _NUM)
_WEIGHT = re.compile(r"(?:cân nặng|nặng|cân được|cân)\D{0,20}?" + _NUM + r"\s*(kg|ký|kí|ki lô|cân|kilogram)?")
_GLUCOSE = re.compile(r"(?:đường huyết|đường máu|đường trong máu|glucose|chỉ số đường|đo đường|đường)\D{0,30}?" + _NUM
                      + r"\s*(mmol|mi li mol|mg|mi li gam)?")
_CONTEXTS = [
    ("after_meal", re.compile(r"sau (?:khi )?(?:ăn|bữa)")),
    ("before_meal", re.compile(r"trước (?:khi )?(?:ăn|bữa)")),
    ("bedtime", re.compile(r"(?:trước khi|lúc|trước lúc) (?:đi )?ngủ|đi ngủ")),
    ("fasting", re.compile(r"lúc đói|khi đói|bụng đói|chưa ăn|nhịn ăn|mới (?:ngủ )?dậy|sáng sớm|buổi sáng|sáng nay")),
]


def guess_context(text):
    t = unicodedata.normalize("NFC", text).lower()
    return next((ctx for ctx, rx in _CONTEXTS if rx.search(t)), None)


def parse_spoken_reading(text):
    """Tìm một số đo trong câu nói. Trả về dict (kind, value, ...) hoặc None. Chỉ là đề xuất để người dùng xác nhận."""
    t = words_to_numbers(text)
    m = _BP.search(t)
    if m:
        sys_, dia = float(m.group(1)), float(m.group(2))
        if 60 <= sys_ <= 260 and 30 <= dia <= 160 and dia < sys_:
            return {"kind": "bp", "systolic": int(sys_), "diastolic": int(dia),
                    "summary": f"Huyết áp {int(sys_)}/{int(dia)} mmHg"}
    m = _GLUCOSE.search(t)
    if m:
        value, unit_word = float(m.group(1)), m.group(2) or ""
        unit = "mg/dL" if unit_word.startswith(("mg", "mi li gam")) or (not unit_word and value > 35) else "mmol/L"
        ctx = guess_context(text)
        shown = f"{value:g}".replace(".", ",")
        out = {"kind": "glucose", "value": value, "unit": unit, "context": ctx,
               "summary": f"Đường huyết {shown} {unit}"}
        # "đường huyết sáu tám" không nói đơn vị: có thể là 68 mg/dL (hạ đường huyết) hoặc 6,8 mmol/L.
        # Không tự chọn: đưa cả hai để người dùng bấm đúng cái mình định nói.
        if not unit_word and 20 <= value < 100 and value == int(value):
            out["alternative"] = {"value": value / 10, "unit": "mmol/L",
                                  "summary": f"Đường huyết {f'{value / 10:g}'.replace('.', ',')} mmol/L"}
        return out
    m = _WEIGHT.search(t)
    if m:
        kg = float(m.group(1))
        if 20 <= kg <= 300:
            return {"kind": "weight", "kg": kg, "summary": f"Cân nặng {f'{kg:g}'.replace('.', ',')} kg"}
    return None
