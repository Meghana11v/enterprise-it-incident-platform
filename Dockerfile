FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/incidents.db

WORKDIR /app

# Install dependencies first so Docker can cache this layer between code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user; it owns the data directory (mount a volume here).
RUN useradd --create-home --uid 10001 opsdesk \
    && mkdir -p /app/data \
    && chown -R opsdesk:opsdesk /app/data
USER opsdesk

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.getenv('PORT', '8000'), timeout=3)"]

# `exec` lets uvicorn receive stop signals; PORT defaults to 8000 outside Render.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
