# ── Stage 1: builder ─────────────────────────────────────────────────────────
# Installs Python packages in an isolated prefix so build tools (gcc, etc.)
# never reach the runtime image. All packages have pre-built wheels for
# python:3.11-slim/linux-amd64, so gcc is only a safety net.
FROM python:3.11-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
# Minimal image: no build tools, no compiler, no creds.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Force non-interactive matplotlib backend; the container has no display
    MPLBACKEND=Agg

# Non-root user for security
RUN useradd --create-home --shell /bin/bash --uid 1000 icn

# Copy installed packages from builder (no build tools come along)
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source with correct ownership
COPY --chown=icn:icn . .

# Safety net: strip any credential files that leaked into the build context
# despite .dockerignore.  Credentials are injected at runtime via volume mount.
RUN rm -rf fabric/creds \
    && mkdir -p output \
    && chown icn:icn output

USER icn

# Credentials are mounted at /fabric/creds at runtime:
#   docker run -v ./fabric/creds:/fabric/creds:ro ...
# Environment variables FABRIC_TLS_CERT_PATH, FABRIC_CERT_PATH,
# FABRIC_PRIVATE_KEY_PATH must point into that mount.
#
# Inside docker-compose the peer is reachable by its service name:
#   FABRIC_PEER_ENDPOINT=peer0.org1.example.com:7051

CMD ["python", "run_experiments.py", "--auth-mode", "with"]
