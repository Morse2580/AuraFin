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
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Production stage
FROM python:3.11-slim

# Create non-root user
RUN groupadd -r cashapp && useradd -r -g cashapp cashapp

# Install runtime tools for healthcheck
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app"

# Set working directory
WORKDIR /app

# Copy shared utilities
COPY shared/ ./shared/

# Copy CLE service code
COPY services/cle/ ./services/cle/

# Change ownership to non-root user
RUN chown -R cashapp:cashapp /app
USER cashapp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Expose port
EXPOSE 8001

# Run the application
CMD ["uvicorn", "services.cle.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
