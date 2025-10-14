# ----------------------------------------
# Builder stage (Go 1.24) -> build Go tools
# ----------------------------------------
FROM golang:1.24-bullseye AS builder

ENV GOPATH=/go
ENV PATH=$GOPATH/bin:/usr/local/go/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git curl build-essential \
    python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Go tools (subfinder, httpx, assetfinder, subzy)
RUN go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest \
 && go install github.com/projectdiscovery/httpx/cmd/httpx@latest \
 && go install github.com/tomnomnom/assetfinder@latest \
 && go install github.com/PentestPad/subzy@latest


# ----------------------------------------
# Final image (Python runtime + Go binaries)
# ----------------------------------------
FROM python:3.11-slim

ENV PATH=/usr/local/bin:/root/.local/bin:/go/bin:$PATH
ENV DEBIAN_FRONTEND=noninteractive

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Go binaries from builder
COPY --from=builder /go/bin /usr/local/bin

# Working dir
WORKDIR /app
RUN mkdir -p /tools

# Copy your main script
COPY r4d4r.py /app/r4d4r.py

# Clone Python-based tools
RUN set -eux; \
    cd /tools; \
    git clone --depth 1 https://github.com/s0md3v/Corsy.git || true; \
    git clone --depth 1 https://github.com/CyberCommands/Broken-Link-Hijacker.git blh || true; \
    python3 -m pip install --upgrade pip setuptools wheel; \
    cd /tools/Corsy && if [ -f requirements.txt ]; then pip install -r requirements.txt; fi; \
    cd /tools/blh && if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

# ---- Create stable wrappers ----
RUN set -eux; \
    # Corsy wrapper
    printf '#!/usr/bin/env bash\npython3 /tools/Corsy/corsy.py "$@"\n' > /usr/local/bin/corsy; \
    chmod +x /usr/local/bin/corsy; \
    # BLH wrapper (script name in repo is Broken-Link-Hijacker.py)
    printf '#!/usr/bin/env bash\npython3 /tools/blh/blh.py "$@"\n' > /usr/local/bin/blh; \
    chmod +x /usr/local/bin/blh

# Sanity check
RUN which subfinder && which assetfinder && which httpx && which subzy && which corsy && which blh

ENTRYPOINT ["python3", "/app/r4d4r.py"]
