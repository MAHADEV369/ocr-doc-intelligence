FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch \
    PADDLE_HOME=/models/paddle

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng poppler-utils libgl1 libglib2.0-0 \
    libgomp1 ghostscript qpdf curl ca-certificates build-essential python3-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
# CPU-only torch keeps the API/worker image from pulling multi-GB CUDA wheels.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    torch==2.9.1 torchvision==0.24.1
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

RUN useradd --create-home --uid 10001 app && \
    mkdir -p /app/data /app/company_datasets /app/reports /models && \
    chown -R app:app /app /models
USER app

COPY --chown=app:app . .
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
