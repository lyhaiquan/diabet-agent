from pathlib import Path

from diacare.ocr import extract_pdf_text


def load_kb(kb_dir, ocr_fn=None):
    kb_path = Path(kb_dir)
    if not kb_path.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục tri thức: {kb_path}")
    docs = []
    for path in sorted(kb_path.iterdir()):
        suffix = path.suffix.lower()
        if suffix in (".txt", ".md"):
            docs.append((path.name, path.read_text(encoding="utf-8")))
        elif suffix == ".pdf":
            docs.append((path.name, extract_pdf_text(path, ocr_fn=ocr_fn)))
    return docs
