import io
import wave

import pytest

from diacare import tts


def test_normalize_reads_units_numbers_and_drops_markup():
    t = tts.normalize("**Đường huyết** 6,8 mmol/L [medlineplus_blood_sugar.txt] trong mục tiêu 4,4–7,2.¹\n"
                      "Nguồn: MedlinePlus\n- HbA1c dưới 7%")
    assert "6 phẩy 8 mi li mol trên lít" in t and "4 phẩy 4 đến 7 phẩy 2" in t
    assert "7 phần trăm" in t and "h b a một c" in t.lower()
    assert "[" not in t and "*" not in t and "MedlinePlus" not in t and "¹" not in t


def test_speaker_without_model_raises_clear_error(monkeypatch):
    monkeypatch.setenv("DIACARE_TTS_MODEL", "khong_co.onnx")
    sp = tts.Speaker()
    assert not sp.available
    with pytest.raises(tts.TTSUnavailable):
        sp.wav("xin chào")
    assert sp.wav("") is None  # chữ rỗng: không cần mô hình


@pytest.mark.skipif(not tts.model_path(), reason="chưa tải giọng Piper vi_VN")
def test_piper_voice_speaks_vietnamese():
    pytest.importorskip("piper")
    data = tts.Speaker().wav("Đường huyết của bạn 6,8 mmol/L.")
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnchannels() == 1 and w.getnframes() / w.getframerate() > 1.0


def test_disclaimer_not_read_aloud():
    from diacare.rules import DISCLAIMER
    t = tts.normalize("Bạn nên đi bộ 30 phút mỗi ngày." + chr(10) * 2 + DISCLAIMER)
    assert t.startswith("Bạn nên đi bộ") and DISCLAIMER[:20] not in t
