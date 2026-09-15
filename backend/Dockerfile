# Backend image for the Context Engine + Multi-Agent QA service.
# Uses the FastAPI reference implementation (app/main.py) on uvicorn.
#
# Build & run from repo root:
#   docker compose build backend
#   docker compose up backend
FROM python:3.11-slim

WORKDIR /app

# Don't write .pyc / buffer output (important for SSE streaming logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install core deps first for better layer caching.
# The offline demo only needs the "core" lines in requirements.txt.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application.
COPY . .

# Data is written under /app/data (kb.json + chat_history). We override the
# config to use this container path (config defaults already point at ./data).
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
