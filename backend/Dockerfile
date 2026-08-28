FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY arbengine/ ./arbengine/

ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# Liveness: the API answers even while a scan is in flight.
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "arbengine.main"]
