FROM python:3.11.9-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# DB init happens at runtime (not build time) so the volume-mounted path exists
CMD ["python", "-c", "from utils.db import init_db; init_db(); print('DB ready')"]
