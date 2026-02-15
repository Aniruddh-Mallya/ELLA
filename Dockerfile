FROM python:3.11-slim

WORKDIR /app

# 1. Install system deps needed by psycopg2-binary
#    (slim image is missing some libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copy app files
COPY ports.py domain.py outbound_adapters.py inbound_adapters.py index.html ./

# 4. Create data directory for SQLite fallback
RUN mkdir -p /app/data

# 5. Port 8000 — Azure WEBSITES_PORT must match this
EXPOSE 8000
CMD ["uvicorn", "inbound_adapters:app", "--host", "0.0.0.0", "--port", "8000"]
