# Trade Pro & AraaBot Production Container
FROM python:3.11-slim

WORKDIR /app

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app

ENV DOCKER_CONTAINER=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5050

# Expose default application port
EXPOSE 5050

# Run via production Gunicorn WSGI entrypoint (supports $PORT override)
CMD ["sh", "-c", "gunicorn --workers 1 --threads 8 --timeout 120 --keep-alive 5 --bind 0.0.0.0:${PORT:-5050} run:app"]
