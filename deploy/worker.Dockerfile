# Worker container with Mullvad VPN inside
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies including Docker CLI for container management
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    iproute2 \
    iptables \
    redis-tools \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Mullvad VPN
RUN curl -fsSLo /usr/share/keyrings/mullvad-keyring.asc https://repository.mullvad.net/deb/mullvad-keyring.asc \
    && echo "deb [signed-by=/usr/share/keyrings/mullvad-keyring.asc] https://repository.mullvad.net/deb/stable jammy main" > /etc/apt/sources.list.d/mullvad.list \
    && apt-get update \
    && apt-get install -y mullvad-vpn \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy app code
COPY app/ ./app/
COPY worker.py .

# Copy startup script
COPY deploy/worker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Environment variables (override in docker-compose)
ENV WORKER_ID=worker1
ENV NITTER_URL=http://nitter-1:8080
ENV REDIS_URL=redis://redis-queue:6379
ENV MULLVAD_ACCOUNT=""
ENV GEMINI_API_KEY=""

ENTRYPOINT ["/entrypoint.sh"]

