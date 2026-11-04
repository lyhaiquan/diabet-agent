from pathlib import Path

from pypdf import PdfReader


def load_kb(kb_dir):
    kb_path = Path(kb_dir)
    if not kb_path.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục tri thức: {kb_path}")
    docs = []
    for path in sorted(kb_path.iterdir()):
        suffix = path.suffix.lower()
        if suffix in (".txt", ".md"):
            docs.append((path.name, path.read_text(encoding="utf-8")))
        elif suffix == ".pdf":
            pages = [p.extract_text() or "" for p in PdfReader(path).pages]
            docs.append((path.name, "\n".join(pages)))
    return docs
