FROM python:3.12-slim

WORKDIR /app

# Metadata + source. Build context is the repo root.
COPY pyproject.toml README.md ./
COPY server ./server
COPY evals ./evals

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

EXPOSE 8000

# Railway (and most PaaS) inject $PORT at runtime; fall back to 8000 locally.
CMD ["sh", "-c", "uvicorn server.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
