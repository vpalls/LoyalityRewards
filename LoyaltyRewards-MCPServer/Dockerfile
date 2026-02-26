FROM python:3.12-slim

LABEL maintainer="loyalty-rewards"
LABEL description="MCP Loyalty Rewards Server"

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

# Data volume
RUN mkdir -p /data
VOLUME ["/data"]

ENV DB_PATH=/data/loyalty.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py"]
