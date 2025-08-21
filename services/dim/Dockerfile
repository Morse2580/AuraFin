FROM python:3.11-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY services/dim/requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Production stage
FROM python:3.11-slim

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

# Copy DIM service code
COPY services/dim/ ./services/dim/

# Change ownership to non-root user
RUN chown -R cashapp:cashapp /app
USER cashapp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8002/health').getcode()==200 else 1)"

# Expose port
EXPOSE 8002

# Run the full three-tier application for production
CMD ["uvicorn", "services.dim.main:app", "--host", "0.0.0.0", "--port", "8002"]
