"""OCR cho phiếu xét nghiệm dạng ảnh và tài liệu PDF dạng ảnh chụp (scanned PDF).

Chiến lược đọc PDF (`extract_pdf_text`):
1. Ưu tiên đọc lớp chữ có sẵn trên từng trang bằng `pypdf` (nhanh, chính xác 100%).
2. Với trang trống lớp chữ (PDF scan/chụp ảnh), kết xuất trang sang ảnh PNG bằng PyMuPDF (`fitz`),
   `pypdfium2`, hoặc lấy ảnh nhúng trong `page.images`, rồi chạy `ocr_image`.

Thứ tự backend `ocr_image` (tự động chọn cái có sẵn trên máy, hoặc nhận `ocr_fn` giả lập khi test):
1. `rapidocr_onnxruntime` (nếu cài)
2. `tesseract` CLI / `pytesseract` (nếu cài)
3. `Windows.Media.Ocr.OcrEngine` có sẵn trên Windows 10/11 (không cần cài thêm thư viện ngoài).

Chặn tệp tải lên làm treo máy chủ (`UploadRejected`):
- Ảnh: kiểm tra kích thước điểm ảnh từ phần đầu tệp (Pillow chưa giải nén) trước khi đưa vào bất kỳ bộ OCR nào.
  Một PNG 20000x20000 chỉ nặng vài KB nhưng giải nén ra hàng GB.
- PDF: giới hạn số trang (`max_pages`, phiếu xét nghiệm chỉ 1-3 trang) và kết xuất trang thành ảnh với độ phân giải
  tự hạ để không quá `MAX_RENDER_PIXELS` (một trang khai báo khổ 200 inch ở 200 dpi ra ảnh 40000x40000).
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")
MAX_IMAGE_PIXELS = 50_000_000    # 50 MP: đủ cho ảnh chụp điện thoại độ phân giải cao
MAX_RENDER_PIXELS = 12_000_000   # một trang A4 ở 200 dpi khoảng 3,9 MP
RENDER_DPI = 200


class UploadRejected(ValueError):
    """Tệp hợp lệ về định dạng nhưng vượt giới hạn xử lý; thông điệp viết cho người dùng."""

# Lỗi nhận dạng đơn vị xét nghiệm thường gặp khi OCR đọc phiếu in mờ:
# "7.2 %" -> "7.2 0/0" hoặc "7.2 o/o"; "mg/dL" -> "mg/d1" hoặc "mg/di"; "mmol/L" -> "mmol/1"
_OCR_PERCENT = re.compile(r"(?<=\d)\s*[0oO]\s*/\s*[0oO]\b")
_OCR_MGDL = re.compile(r"\bmg\s*/\s*d[1ilI]\b", re.IGNORECASE)
_OCR_MMOLL = re.compile(r"\bmmol\s*/\s*[1ilI]\b", re.IGNORECASE)

_WIN_OCR_PS = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($op, $t) {
    $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op))
    $task.Wait()
    return $task.Result
}
$fs = [System.IO.File]::OpenRead($env:OCR_IMG_PATH)
try {
    $stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fs)
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    $res = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    foreach ($line in $res.Lines) { Write-Output $line.Text }
} finally {
    $fs.Dispose()
}
"""


def clean_ocr_text(text):
    """Chuẩn hóa các lỗi ký tự đơn vị phổ biến do OCR gây ra."""
    if not text:
        return ""
    text = _OCR_PERCENT.sub(" %", text)
    text = _OCR_MGDL.sub("mg/dL", text)
    text = _OCR_MMOLL.sub("mmol/L", text)
    return text


def check_image_size(raw):
    """Đọc kích thước ảnh từ phần đầu tệp (chưa giải nén điểm ảnh); quá MAX_IMAGE_PIXELS thì từ chối."""
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(raw)) as img:
            width, height = img.size
    except Image.DecompressionBombError as exc:
        raise UploadRejected("Ảnh quá lớn để xử lý.") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise UploadRejected("Không nhận ra định dạng ảnh.") from exc
    if width * height > MAX_IMAGE_PIXELS:
        raise UploadRejected(f"Ảnh quá lớn ({width}x{height} điểm ảnh); tối đa {MAX_IMAGE_PIXELS // 1_000_000} "
                             "triệu điểm ảnh. Hãy chụp lại hoặc giảm kích thước ảnh.")
    return width, height


def _to_png_bytes(data):
    """Đảm bảo dữ liệu ảnh ở định dạng PNG hợp lệ trước khi đưa vào công cụ OCR.
    Kiểm tra kích thước nằm ngoài khối try: lỗi quá cỡ không được nuốt mất rồi để bộ OCR tự giải nén ảnh."""
    raw = Path(data).read_bytes() if isinstance(data, (str, Path)) else bytes(data)
    check_image_size(raw)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as img:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return raw


def _rapidocr(png_bytes):
    from rapidocr_onnxruntime import RapidOCR
    res, _ = RapidOCR()(png_bytes)
    return "\n".join(line[1] for line in (res or []))


def _tesseract_ocr(png_bytes):
    exe = shutil.which("tesseract")
    if not exe:
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png_bytes)
        path = f.name
    try:
        for lang in ("vie+eng", "eng"):
            proc = subprocess.run([exe, path, "stdout", "-l", lang], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        return ""
    finally:
        Path(path).unlink(missing_ok=True)


def _windows_ocr(png_bytes):
    if sys.platform != "win32":
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png_bytes)
        path = f.name
    try:
        env = {**os.environ, "OCR_IMG_PATH": path}
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", _WIN_OCR_PS],
                              env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:
        return ""
    finally:
        Path(path).unlink(missing_ok=True)


def default_ocr_image(data):
    """Chạy OCR trên dữ liệu ảnh bằng backend khả dụng trên máy."""
    png_bytes = _to_png_bytes(data)
    try:
        return _rapidocr(png_bytes)
    except Exception:
        pass
    tess = _tesseract_ocr(png_bytes)
    if tess is not None:
        return tess
    return _windows_ocr(png_bytes)


def ocr_image(data, ocr_fn=None):
    """Nhận diện chữ từ ảnh (`bytes` hoặc `Path`), trả về chuỗi văn bản đã làm sạch đơn vị."""
    fn = ocr_fn or default_ocr_image
    raw = Path(data).read_bytes() if isinstance(data, (str, Path)) else bytes(data)
    if not raw:
        return ""
    return clean_ocr_text(fn(raw) or "")


def render_scale(width_pt, height_pt, dpi=RENDER_DPI, max_pixels=MAX_RENDER_PIXELS):
    """Hệ số phóng (điểm ảnh trên 1 point PDF) ở `dpi`, tự hạ để ảnh kết xuất không quá `max_pixels`."""
    scale = dpi / 72
    area = max(float(width_pt), 1.0) * max(float(height_pt), 1.0)
    if area * scale * scale > max_pixels:
        scale = (max_pixels / area) ** 0.5
    return scale


def render_pdf_page(pdf_bytes, page_index, reader_page=None):
    """Kết xuất trang `page_index` của PDF sang danh sách ảnh PNG (`bytes`) để chạy OCR."""
    try:
        import fitz
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if 0 <= page_index < len(doc):
                page = doc[page_index]
                s = render_scale(page.rect.width, page.rect.height)
                return [page.get_pixmap(matrix=fitz.Matrix(s, s)).tobytes("png")]
    except Exception:
        pass
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_bytes)
        if 0 <= page_index < len(doc):
            page = doc[page_index]
            pil_img = page.render(scale=render_scale(*page.get_size())).to_pil()
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return [buf.getvalue()]
    except Exception:
        pass
    if reader_page is not None:
        try:
            return [img.data for img in reader_page.images if getattr(img, "data", None)]
        except Exception:
            pass
    return []


def extract_pdf_text(pdf_source, ocr_fn=None, max_pages=None):
    """Trích văn bản từ PDF (`bytes` hoặc `Path`). Trang không có lớp chữ sẽ tự động chuyển qua OCR.
    max_pages: từ chối PDF dài hơn (tệp người dùng tải lên); None = không giới hạn (tài liệu trong kho kiến thức)."""
    pdf_bytes = Path(pdf_source).read_bytes() if isinstance(pdf_source, (str, Path)) else bytes(pdf_source)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if max_pages is not None and len(reader.pages) > max_pages:
        raise UploadRejected(f"PDF có {len(reader.pages)} trang; phiếu xét nghiệm tối đa {max_pages} trang.")
    pages = []
    for idx, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if not text:
            chunks = [ocr_image(img, ocr_fn=ocr_fn) for img in render_pdf_page(pdf_bytes, idx, page)]
            text = "\n".join(c for c in chunks if c)
        pages.append(text)
    return "\n".join(p for p in pages if p)
