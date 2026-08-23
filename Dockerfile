FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Used by both the `web` and `printer_worker` services -- the command differs
# per-service via docker-compose.yml's `command:` override.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
