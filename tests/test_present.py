"""Trình bày câu trả lời cho người bệnh (diacare.present). Câu mẫu lấy từ bản nháp thật của qwen2.5:3b."""
from diacare.present import present, sources_line, split_disclaimer, streaming_view
from diacare.rules import DISCLAIMER

REAL = ("Tối nay, bạn nên ưu tiên các thực phẩm giàu chất xơ và protein. [medlineplus_diabetic_diet.txt] "
        "Bạn cũng nên ăn rau xanh và hạt. [medlineplus_diabetic_diet.txt] Đừng quên uống đủ nước. "
        "[medlineplus_diabetic_diet.txt]\n\n"
        "Lưu ý: chỉ điều chỉnh liều thuốc theo hướng dẫn của bác sĩ.\n\n" + DISCLAIMER)


def test_repeated_labels_in_one_paragraph_become_one_footnote():
    body, notes, disclaimer = present(REAL)
    assert "[" not in body and ".txt" not in body
    assert body.count("¹") == 1 and body.split("\n\n")[0].endswith("nước.¹")
    assert notes == [(1, "MedlinePlus – Chế độ ăn cho người đái tháo đường")]
    assert disclaimer and DISCLAIMER not in body
    assert body.endswith("hướng dẫn của bác sĩ.")


def test_comma_joined_and_mixed_sources_numbered_in_order():
    text = ("Đường làm tăng đường huyết nhanh. [medlineplus_diabetes.txt], [medlineplus_blood_sugar.txt]\n\n"
            "Một ly cà phê có khoảng 40 g đường [usda_fdc]. Ngưỡng HbA1c là 6,5% [ada_2024].")
    body, notes, _ = present(text)
    assert body.startswith("Đường làm tăng đường huyết nhanh.¹²")
    assert "40 g đường³." in body and "6,5%⁴." in body
    assert [n for n, _ in notes] == [1, 2, 3, 4]
    assert sources_line(notes).startswith("Nguồn: ¹ MedlinePlus – Bệnh đái tháo đường; ² MedlinePlus – Đường huyết")


def test_different_sources_in_a_paragraph_each_keep_their_footnote():
    body, _, _ = present("Ý một [medlineplus_diabetes.txt]. Ý hai [who_diabetes_factsheet.txt]. "
                         "Ý ba [medlineplus_diabetes.txt].")
    assert body == "Ý một¹. Ý hai². Ý ba¹."


def test_unknown_brackets_left_alone():
    text = "Xem [tài liệu nội bộ] và [abc.txt]; mục [1] trong danh sách."
    body, notes, disclaimer = present(text)
    assert body == text and notes == [] and not disclaimer


def test_disclaimer_only_removed_at_the_end():
    assert split_disclaimer("Câu.\n\n" + DISCLAIMER + "\n") == ("Câu.", True)
    middle = DISCLAIMER + " Nhưng còn câu sau."
    assert split_disclaimer(middle) == (middle, False)


def test_streaming_hides_labels_and_half_typed_label():
    assert streaming_view("Ăn rau xanh. [medlineplus_diabetic_diet.txt] Uống nước") == "Ăn rau xanh. Uống nước"
    assert streaming_view("Ăn rau xanh. [medlineplus_diab") == "Ăn rau xanh."
    assert streaming_view("Mục [1] ở trên") == "Mục [1] ở trên"
