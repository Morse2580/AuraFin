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
COPY services/orchestrator/requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Production stage
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
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

# Copy orchestrator service code
COPY services/orchestrator/ ./services/orchestrator/

# Change ownership to non-root user
RUN chown -R cashapp:cashapp /app
USER cashapp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8005/health || exit 1

# Expose port
EXPOSE 8005

# Create startup script that runs both worker and API
RUN echo '#!/bin/bash\n\
echo "Starting Temporal Worker in background..."\n\
cd /app/services/orchestrator && python temporal_worker.py &\n\
WORKER_PID=$!\n\
echo "Starting FastAPI server..."\n\
cd /app/services/orchestrator && python main.py &\n\
API_PID=$!\n\
echo "Both services started. Worker PID: $WORKER_PID, API PID: $API_PID"\n\
wait\n' > /app/start.sh && chmod +x /app/start.sh

# Run both the temporal worker and FastAPI server
CMD ["/app/start.sh"]