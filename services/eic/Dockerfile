FROM python:3.11-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY services/eic/requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Production stage
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r cashapp && useradd -r -g cashapp cashapp

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app"

# Set working directory
WORKDIR /app

# Copy shared utilities
COPY shared/ ./shared/

# Copy EIC service code
COPY services/eic/ ./services/eic/

# Change ownership to non-root user
RUN chown -R cashapp:cashapp /app
USER cashapp

# Health check
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1

# Expose port
EXPOSE 8003

# Run the application
CMD ["uvicorn", "services.eic.app.main:app", "--host", "0.0.0.0", "--port", "8003"]