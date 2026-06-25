# ── Backend image: FastAPI + CT-MIF + agents ────────────────────────
# Python 3.12 matches the env the model artifacts were pickled under.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + trained models (artifacts/*.pkl) + replay fallback sample.
# (.dockerignore keeps out the large arrays, raw CSVs, frontend, and .env.)
COPY . .

EXPOSE 8000

# Render (and most PaaS) inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
