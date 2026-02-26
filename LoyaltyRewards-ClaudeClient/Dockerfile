# ─────────────────────────────────────────────────────────────────────────────
# LoyaltyRewards-ClaudeClient  –  Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL maintainer="LoyaltyRewards"
LABEL description="Claude AI client connecting to the LoyaltyRewards MCP Server"

# System deps (curl for health-check)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

EXPOSE 8002

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -f http://localhost:8002/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002", "--proxy-headers"]
