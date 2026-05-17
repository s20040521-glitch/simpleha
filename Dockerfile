# SimpleHA Dockerfile
# Multi-stage build for optimized production image
# Based on Python 3.11 slim image

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (for caching)
COPY pyproject.toml ./

# Install dependencies to a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && \
    pip install build

# Build the package
RUN pip install .

# Stage 2: Runtime
FROM python:3.11-slim AS runtime

# Security: Run as non-root user
RUN groupadd -r simpleha && useradd -r -g simpleha simpleha

WORKDIR /app

# Copy only the installed package from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY --chown=simpleha:simpleha config/ /etc/simpleha/
COPY --chown=simpleha:simpleha src/ ./src/
COPY --chown=simpleha:simpleha pyproject.toml ./

# Expose API port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Switch to non-root user
USER simpleha

# Default command: start API server
CMD ["simpleha-api"]

# Labels
LABEL org.opencontainers.image.title="SimpleHA"
LABEL org.opencontainers.image.description="Simplified High Availability Cluster Manager"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.source="https://github.com/your-org/simpleha"
