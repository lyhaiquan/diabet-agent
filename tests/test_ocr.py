import io

import fitz
from PIL import Image, ImageDraw

from diacare.kb import load_kb
from diacare.labs import parse_lab_file
from diacare.ocr import clean_ocr_text, extract_pdf_text, ocr_image


def _make_png(text="HbA1c: 7.2 %"):
    img = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(img).text((20, 40), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_scanned_pdf(png_bytes):
    doc = fitz.open()
    page = doc.new_page(width=400, height=120)
    page.insert_image(fitz.Rect(0, 0, 400, 120), stream=png_bytes)
    return doc.tobytes()


def _make_digital_pdf(text):
    doc = fitz.open()
    page = doc.new_page(width=400, height=120)
    page.insert_text((20, 50), text)
    return doc.tobytes()


def test_clean_ocr_text_fixes_common_unit_confusions():
    raw = "HbA1c: 7.2 0/0\nFPG: 130 mg/d1\nGlucose: 7.4 mmol/1"
    cleaned = clean_ocr_text(raw)
    assert "7.2 %" in cleaned
    assert "130 mg/dL" in cleaned
    assert "7.4 mmol/L" in cleaned


def test_ocr_image_uses_pluggable_ocr_fn_and_cleans_units():
    png = _make_png()
    out = ocr_image(png, ocr_fn=lambda b: "HbA1c: 6.8 o/o" if b else "")
    assert out == "HbA1c: 6.8 %"
    assert ocr_image(b"", ocr_fn=lambda b: "x") == ""


def test_extract_pdf_text_uses_text_layer_when_available():
    called = []
    pdf = _make_digital_pdf("HbA1c: 5.9 %")
    text = extract_pdf_text(pdf, ocr_fn=lambda b: (called.append(b), "OCR")[1])
    assert "5.9" in text
    assert called == []  # có lớp chữ thì không cần gọi OCR


def test_extract_pdf_text_falls_back_to_ocr_on_scanned_page():
    pdf = _make_scanned_pdf(_make_png())
    text = extract_pdf_text(pdf, ocr_fn=lambda b: "HbA1c: 7.4 0/0\nGlucose luc doi: 140 mg/d1")
    assert "7.4 %" in text and "140 mg/dL" in text


def test_parse_lab_file_reads_scanned_pdf_and_image_files():
    fake_ocr = lambda b: "HbA1c: 7.1 0/0\nDuong huyet luc doi: 7.8 mmol/1"
    png = _make_png()
    pdf = _make_scanned_pdf(png)
    from_pdf = {r["test"]: (r["value"], r["unit"]) for r in parse_lab_file("phieu_scan.pdf", pdf, ocr_fn=fake_ocr)}
    from_img = {r["test"]: (r["value"], r["unit"]) for r in parse_lab_file("phieu_chup.jpg", png, ocr_fn=fake_ocr)}
    expected = {"hba1c": (7.1, "%"), "fpg": (7.8, "mmol/l")}
    assert from_pdf == expected
    assert from_img == expected


def test_load_kb_reads_scanned_pdf_via_ocr(tmp_path):
    (tmp_path / "scan.pdf").write_bytes(_make_scanned_pdf(_make_png()))
    docs = dict(load_kb(tmp_path, ocr_fn=lambda b: "Tài liệu scan hướng dẫn kiểm soát đường huyết."))
    assert docs == {"scan.pdf": "Tài liệu scan hướng dẫn kiểm soát đường huyết."}
