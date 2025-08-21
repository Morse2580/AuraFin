#!/usr/bin/env python3
"""
EIC Service - Minimal Version for Docker Testing
"""

import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from shared.health import HealthChecker
from shared.metrics import MetricsCollector
from shared.logging_config import get_logger

logger = get_logger(__name__)

# Global instances
health_checker = None
metrics = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown"""
    global health_checker, metrics
    
    logger.info("Starting ERP Integration Connectors...")
    
    # Initialize metrics
    metrics = MetricsCollector(service_name="eic")
    
    # Initialize health checker
    health_checker = HealthChecker(service_name="eic-test")
    
    logger.info("EIC service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down EIC service...")

# Create FastAPI app
app = FastAPI(
    title="ERP Integration Connectors (EIC)",
    description="Unified facade for multiple ERP systems",
    version="1.0.0",
    lifespan=lifespan
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    if health_checker is None:
        raise HTTPException(status_code=503, detail="Health checker not initialized")
    
    return await health_checker.check_health()

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "eic",
        "version": "1.0.0",
        "status": "healthy",
        "message": "ERP Integration Connectors service is running",
        "timestamp": time.time()
    }

@app.get("/metrics")
async def get_metrics():
    """Basic metrics endpoint"""
    if metrics is None:
        raise HTTPException(status_code=503, detail="Metrics not available")
    
    return {
        "service": "eic",
        "status": "active",
        "uptime": "testing"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main_minimal:app",
        host="0.0.0.0",
        port=8003,
        reload=True
    )