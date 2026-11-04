from pathlib import Path

from pypdf import PdfReader


def load_kb(kb_dir):
    docs = []
    for path in sorted(Path(kb_dir).iterdir()):
        if path.suffix in (".txt", ".md"):
            docs.append((path.name, path.read_text(encoding="utf-8")))
        elif path.suffix == ".pdf":
            pages = [p.extract_text() or "" for p in PdfReader(path).pages]
            docs.append((path.name, "\n".join(pages)))
    return docs
