# Dịch vụ API DiaCare (FastAPI). Dựng: docker compose build api
# Ảnh chạy bằng CPU: LLM nằm ở dịch vụ Ollama riêng, ở đây chỉ có embedding, Predictor và nhận dạng giọng nói.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/hf-cache MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

# torch bản CPU (nhỏ hơn bản CUDA vài GB), cài trước để lớp này được dùng lại khi đổi mã nguồn
COPY requirements-api.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements-api.txt

COPY src ./src
COPY kb ./kb
COPY models ./models
COPY data/nutrition ./data/nutrition

# Chạy bằng người dùng thường; /app/var (khoá mã hoá DB, khoá ký token; SQLite nếu không dùng PostgreSQL) và /hf-cache là volume
RUN useradd --create-home --uid 10001 diacare \
    && mkdir -p /app/var /app/logs /hf-cache \
    && chown -R diacare:diacare /app/var /app/logs /hf-cache
USER diacare

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "api.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
