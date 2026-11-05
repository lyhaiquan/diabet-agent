from diacare.rules import SafeStream
from diacare.typewriter import Typewriter


def make():
    frames, sleeps = [], []
    tw = Typewriter(frames.append, step_s=0.03, max_s=0.6, sleep=sleeps.append, cursor="|")
    return tw, frames, sleeps


def test_types_new_text_word_by_word():
    tw, frames, sleeps = make()
    tw("Ăn nhiều rau xanh.")
    assert frames == ["Ăn |", "Ăn nhiều |", "Ăn nhiều rau |", "Ăn nhiều rau xanh.|"]
    assert sleeps == [0.03] * 4


def test_only_new_part_is_typed_and_long_chunks_go_faster():
    tw, frames, sleeps = make()
    tw("Câu một.")
    frames.clear(); sleeps.clear()
    long = "Câu một." + " từ" * 60
    tw(long)
    assert frames[0] == "Câu một. từ |" and frames[-1] == long + "|"
    assert len(frames) == 60
    assert abs(sum(sleeps) - 0.6) < 1e-9  # đoạn dài gõ trong tối đa max_s


def test_replaced_text_is_redrawn_at_once():
    tw, frames, _ = make()
    tw("abc")
    frames.clear()
    tw("xyz khác hẳn")
    assert frames == ["xyz khác hẳn|"]


def test_finish_removes_cursor():
    tw, frames, _ = make()
    tw("Xong.")
    tw.finish()
    assert frames[-1] == "Xong."


def test_with_safestream_unsafe_sentence_never_rendered():
    tw, frames, _ = make()
    s = SafeStream(tw)
    for piece in ["Ăn rau. ", "Bạn nên ngừng ", "metformin. Đi bộ."]:
        s(piece)
    s.flush()
    assert all("metformin" not in f for f in frames)
    assert frames[-1] == "Ăn rau.|"
