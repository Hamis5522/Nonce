FROM python:3.12-slim

LABEL maintainer="Nonce.dev"
LABEL description="AI Agent Identity Infrastructure API"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create volume mount points
RUN mkdir -p /data/db /data/ca
ENV DB_PATH=/data/db/nonce.db
ENV CA_KEY_PATH=/data/ca/ca_key.pem
ENV CA_CERT_PATH=/data/ca/ca_cert.pem

# Non-root user for security
RUN useradd -r -s /bin/false nonce
RUN chown -R nonce:nonce /app /data
USER nonce

EXPOSE 8000

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python3", "server.py"]
