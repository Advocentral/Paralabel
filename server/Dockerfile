FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg build are avoided by using the binary wheel.
COPY pyproject.toml ./
COPY server ./server
COPY evals ./evals

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
