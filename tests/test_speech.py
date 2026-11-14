import io
import wave

import numpy as np
import pytest

from diacare.speech import (AudioError, DemoTranscriber, decode_wav, guess_context, make_transcriber,
                            parse_spoken_reading, words_to_numbers)


def wav_bytes(seconds=1.0, rate=16000, channels=1, amp=0.3, width=2):
    n = int(seconds * rate)
    tone = (amp * np.sin(2 * np.pi * 220 * np.arange(n) / rate) * 32767).astype("<i2")
    if channels == 2:
        tone = np.repeat(tone, 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(tone.tobytes() if width == 2 else (tone // 256).astype("i1").tobytes())
    return buf.getvalue()


def test_decode_wav_resamples_and_mixes_down():
    a = decode_wav(wav_bytes(1.0))
    assert a.dtype == np.float32 and len(a) == 16000 and 0.25 < np.abs(a).max() <= 0.31
    b = decode_wav(wav_bytes(1.0, rate=48000, channels=2))
    assert abs(len(b) - 16000) <= 1


@pytest.mark.parametrize("data,msg", [
    (b"not a wav", "không phải WAV"),
    (wav_bytes(0.1), "quá ngắn"),
    (wav_bytes(1.0, amp=0.0), "Không nghe thấy"),
    (wav_bytes(62), "dài quá"),
], ids=["rac", "ngan", "im-lang", "qua-dai"])  # id ngắn: pytest đưa id vào biến môi trường
def test_decode_wav_rejects(data, msg):
    with pytest.raises(AudioError, match=msg):
        decode_wav(data)


@pytest.mark.parametrize("spoken,expected", [
    ("sáu phẩy tám", "6.8"), ("bảy chấm hai", "7.2"), ("mười phẩy năm", "10.5"),
    ("một trăm hai mươi lăm", "125"), ("một trăm linh năm", "105"), ("hai mươi mốt", "21"),
    ("mười lăm", "15"), ("một trăm hai", "120"), ("hai trăm năm mươi", "250"), ("bảy rưỡi", "7.5"),
    ("6,8", "6.8"), ("6 phẩy 8", "6.8"),
    ("tôi không đo năm nay", "tôi không đo năm nay"),  # chữ đứng riêng không bị đổi thành số
])
def test_words_to_numbers(spoken, expected):
    assert words_to_numbers(spoken) == expected


def test_parse_glucose_with_context_and_unit():
    r = parse_spoken_reading("Đường huyết sáng nay lúc đói sáu phẩy tám")
    assert r == {"kind": "glucose", "value": 6.8, "unit": "mmol/L", "context": "fasting",
                 "summary": "Đường huyết 6,8 mmol/L"}
    r = parse_spoken_reading("đo đường sau ăn được mười phẩy hai")
    assert r["value"] == 10.2 and r["context"] == "after_meal"
    r = parse_spoken_reading("đường huyết một trăm hai mươi mi li gam")
    assert r["unit"] == "mg/dL" and r["value"] == 120 and "alternative" not in r
    assert parse_spoken_reading("đường huyết trước khi ngủ bảy rưỡi")["context"] == "bedtime"


def test_ambiguous_two_digit_glucose_offers_mmol_alternative():
    # "sáu tám" có thể là 68 mg/dL (hạ đường huyết) hoặc 6,8 mmol/L: không được tự chọn
    r = parse_spoken_reading("đường huyết sáu tám")
    assert r["value"] == 68 and r["unit"] == "mg/dL"
    assert r["alternative"]["value"] == 6.8 and r["alternative"]["unit"] == "mmol/L"


def test_parse_bp_weight_and_nothing():
    assert parse_spoken_reading("huyết áp một trăm ba mươi trên tám mươi lăm") == {
        "kind": "bp", "systolic": 130, "diastolic": 85, "summary": "Huyết áp 130/85 mmHg"}
    assert parse_spoken_reading("huyết áp 125/80")["systolic"] == 125
    assert parse_spoken_reading("cân nặng sáu mươi hai phẩy năm ký")["kg"] == 62.5
    assert parse_spoken_reading("huyết áp tám mươi trên một trăm") is None  # tâm trương lớn hơn tâm thu
    assert parse_spoken_reading("hôm nay tôi hơi mệt") is None
    assert parse_spoken_reading("bữa sáng ăn bánh mì có ổn không") is None


def test_guess_context():
    assert guess_context("sau bữa trưa") == "after_meal"
    assert guess_context("trước khi ăn tối") == "before_meal"
    assert guess_context("lúc mới ngủ dậy") == "fasting"
    assert guess_context("không rõ") is None


def test_demo_transcriber(monkeypatch):
    monkeypatch.setenv("DIACARE_ASR", "demo")
    monkeypatch.setenv("DIACARE_ASR_DEMO_TEXT", "huyết áp 120 trên 80")
    t = make_transcriber()
    assert isinstance(t, DemoTranscriber) and t(np.zeros(16000)) == "huyết áp 120 trên 80"
