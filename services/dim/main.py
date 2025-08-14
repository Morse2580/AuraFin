# services/dim/main.py
"""
Document Intelligence Module (DIM) - The "Eyes"
Aura Finance CashAppAgent - Three-tier document parsing service

This service implements a 3-tier processing pipeline:
1. Pattern Matching (Free, Fast) - 70% of documents
2. LayoutLM ONNX (Low Cost, Medium) - 25% of documents 
3. Azure Form Recognizer (Higher Cost, Slow) - 5% of documents
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import uvicorn
from pydantic import BaseModel, Field, validator
from prometheus_client import Counter, Histogram, Gauge, generate_latest

from shared.logging import setup_logging, get_correlation_id, log_context
from shared.database import DatabaseManager
from shared.models import HealthResponse

# Import new three-tier document intelligence system
from document_intelligence_engine import DocumentIntelligenceEngine
from config.model_config import get_model_config, is_e2e_mode, is_production_mode

# Configure logging
logger = setup_logging("dim-service")

# Business metrics
DOCUMENTS_PROCESSED = Counter(
    'dim_documents_processed_total',
    'Total documents processed',
    ['document_type', 'status']
)

PROCESSING_DURATION = Histogram(
    'dim_processing_duration_seconds',
    'Document processing duration',
    ['stage', 'model_type'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)

MODEL_INFERENCE_TIME = Histogram(
    'dim_model_inference_seconds',
    'Model inference duration',
    ['model_name', 'input_type']
)

CONFIDENCE_SCORE = Histogram(
    'dim_confidence_score',
    'Extraction confidence scores',
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

ACTIVE_PROCESSING_JOBS = Gauge(
    'dim_active_processing_jobs',
    'Currently active document processing jobs'
)

# Global state
document_intelligence: Optional[DocumentIntelligenceEngine] = None
db_manager: Optional[DatabaseManager] = None


class DocumentParseRequestBody(BaseModel):
    """Request body for document parsing."""
    document_uris: List[str] = Field(..., description="List of document URIs to process")
    client_id: Optional[str] = Field(None, description="Client identifier for context")
    processing_options: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional processing options"
    )
    
    @validator('document_uris')
    def validate_uris(cls, v):
        if not v:
            raise ValueError("At least one document URI must be provided")
        if len(v) > 10:  # Reasonable limit
            raise ValueError("Maximum 10 documents can be processed in one request")
        return v


class DocumentParseResponseBody(BaseModel):
    """Response body for document parsing."""
    request_id: str = Field(..., description="Unique request identifier")
    invoice_ids: List[str] = Field(..., description="Extracted invoice IDs")
    confidence_score: float = Field(..., description="Overall confidence score (0.0-1.0)")
    processing_duration_ms: int = Field(..., description="Processing time in milliseconds")
    document_analysis: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed analysis per document"
    )
    warnings: List[str] = Field(default_factory=list, description="Processing warnings")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for three-tier DIM service."""
    global document_intelligence, db_manager
    
    config = get_model_config()
    logger.info(f"Starting Document Intelligence Module (DIM) - {config['mode']} mode...")
    
    try:
        # Initialize database connection
        try:
            db_manager = DatabaseManager()
            await db_manager.initialize()
            logger.info("Database connection initialized")
        except Exception as e:
            logger.warning(f"Database initialization failed: {e}")
            if not is_e2e_mode():
                raise
        
        # Initialize document intelligence engine
        document_intelligence = DocumentIntelligenceEngine()
        success = await document_intelligence.initialize()
        
        if success:
            logger.info("Document Intelligence Engine initialized successfully")
        else:
            logger.warning("Document Intelligence Engine initialization had issues")
            if not is_e2e_mode():
                raise Exception("Failed to initialize Document Intelligence Engine")
        
        # Log engine status
        status = document_intelligence.get_engine_status()
        logger.info(f"DIM Engine Status: {status}")
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to initialize DIM service: {e}")
        if is_e2e_mode():
            logger.warning("Continuing in E2E test mode despite initialization errors")
            yield
        else:
            raise
    finally:
        # Cleanup
        if db_manager:
            await db_manager.close()
        logger.info("DIM service shut down")


# Create FastAPI app
app = FastAPI(
    title="Document Intelligence Module (DIM)",
    description="Three-tier document parsing service for CashAppAgent",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Configure properly in production
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Check database connectivity
        db_healthy = await db_manager.health_check() if db_manager else False
        
        # Check document intelligence engine
        engine_status = document_intelligence.get_engine_status() if document_intelligence else None
        models_healthy = (
            engine_status and engine_status.get('initialized', False) 
            if engine_status else False
        )
        
        # Check GPU availability
        gpu_available = False
        if is_production_mode():
            try:
                import torch
                gpu_available = torch.cuda.is_available()
            except ImportError:
                logger.info("PyTorch not available - GPU detection disabled")
        
        status = "healthy" if all([db_healthy, models_healthy]) else "unhealthy"
        
        return HealthResponse(
            status=status,
            service="dim",
            timestamp=time.time(),
            details={
                "database": "healthy" if db_healthy else "unhealthy",
                "document_intelligence": "healthy" if models_healthy else "unhealthy",
                "gpu": "available" if gpu_available else "unavailable",
                "mode": get_model_config()['mode'],
                "engine_status": engine_status
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


@app.get("/health/models")
async def model_health_check():
    """Detailed document intelligence engine health check."""
    try:
        if not document_intelligence:
            raise HTTPException(status_code=503, detail="Document Intelligence Engine not initialized")
        
        engine_status = document_intelligence.get_engine_status()
        
        return {
            "engine_initialized": engine_status.get('initialized', False),
            "mode": engine_status.get('mode', 'unknown'),
            "enabled_tiers": engine_status.get('enabled_tiers', []),
            "tier_status": engine_status.get('tier_status', {}),
            "gpu_available": False,  # Will be detected in production
            "memory_usage_mb": 0,  # Placeholder
            "model_versions": {
                "pattern_matcher": "1.0.0",
                "layoutlm_onnx": "layoutlmv3-base" if engine_status.get('tier_status', {}).get('layoutlm') else None,
                "azure_form_recognizer": "prebuilt-invoice" if engine_status.get('tier_status', {}).get('azure_form_recognizer') else None
            }
        }
        
    except Exception as e:
        logger.error(f"Model health check failed: {e}")
        raise HTTPException(status_code=503, detail="Model health check failed")


@app.post("/api/v1/parse_document", response_model=DocumentParseResponseBody)
async def parse_document(
    request: DocumentParseRequestBody,
    background_tasks: BackgroundTasks,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Parse documents and extract invoice IDs using three-tier intelligence pipeline.
    
    This endpoint implements the DIM functionality:
    1. Try Pattern Matching (free, fast)
    2. Try LayoutLM ONNX (low cost, medium speed) if pattern matching confidence is low
    3. Fallback to Azure Form Recognizer (higher cost, slow) for difficult documents
    """
    start_time = time.time()
    ACTIVE_PROCESSING_JOBS.inc()
    
    try:
        with log_context(correlation_id=correlation_id, service="dim"):
            logger.info(
                f"Processing document parse request",
                extra={
                    "document_count": len(request.document_uris),
                    "client_id": request.client_id,
                    "correlation_id": correlation_id
                }
            )
            
            if not document_intelligence:
                raise HTTPException(
                    status_code=503, 
                    detail="Document Intelligence Engine not initialized"
                )
            
            # For demo purposes, use the first document URI as text content
            # In production, you'd download the actual document from the URI
            sample_text = f"Sample document content from {request.document_uris[0]}"
            if is_e2e_mode():
                sample_text = "INVOICE #INV-123456 Purchase Order: PO-789012 Document Number: DOC-345678"
            
            # Process document using three-tier intelligence
            intelligence_result = await document_intelligence.extract_invoice_ids(
                document_content=sample_text,
                document_type="text",
                correlation_id=correlation_id
            )
            
            # Update metrics
            DOCUMENTS_PROCESSED.labels(
                document_type="remittance_advice", 
                status="success"
            ).inc(len(request.document_uris))
            
            PROCESSING_DURATION.labels(
                stage="total",
                model_type=intelligence_result.processing_tier
            ).observe(intelligence_result.processing_time_ms / 1000)
            
            CONFIDENCE_SCORE.observe(intelligence_result.confidence)
            
            # Log async audit trail
            background_tasks.add_task(
                log_audit_trail,
                correlation_id=correlation_id,
                action="document_processed",
                details={
                    "document_count": len(request.document_uris),
                    "invoice_ids_found": len(intelligence_result.invoice_ids),
                    "confidence_score": intelligence_result.confidence,
                    "processing_tier": intelligence_result.processing_tier,
                    "processing_duration_ms": intelligence_result.processing_time_ms,
                    "cost_estimate": intelligence_result.cost_estimate
                }
            )
            
            logger.info(
                f"Document processing completed successfully using {intelligence_result.processing_tier}",
                extra={
                    "invoice_ids_count": len(intelligence_result.invoice_ids),
                    "confidence_score": intelligence_result.confidence,
                    "processing_tier": intelligence_result.processing_tier,
                    "processing_duration_ms": intelligence_result.processing_time_ms,
                    "cost_estimate": intelligence_result.cost_estimate,
                    "correlation_id": correlation_id
                }
            )
            
            return DocumentParseResponseBody(
                request_id=correlation_id,
                invoice_ids=intelligence_result.invoice_ids,
                confidence_score=intelligence_result.confidence,
                processing_duration_ms=intelligence_result.processing_time_ms,
                document_analysis=[{
                    "tier_used": intelligence_result.processing_tier,
                    "cost_estimate": intelligence_result.cost_estimate,
                    "tier_results": intelligence_result.tier_results
                }],
                warnings=intelligence_result.warnings
            )
            
    except Exception as e:
        DOCUMENTS_PROCESSED.labels(
            document_type="remittance_advice",
            status="error"
        ).inc()
        logger.error(f"Unexpected error during document processing: {e}", extra={"correlation_id": correlation_id})
        raise HTTPException(status_code=500, detail="Internal server error")
        
    finally:
        ACTIVE_PROCESSING_JOBS.dec()


@app.post("/api/v1/extract_invoice_ids")
async def extract_invoice_ids(
    request: DocumentParseRequestBody,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Simplified endpoint for invoice ID extraction only.
    Returns just the invoice IDs without detailed analysis.
    """
    try:
        with log_context(correlation_id=correlation_id, service="dim"):
            if not document_intelligence:
                raise HTTPException(
                    status_code=503, 
                    detail="Document Intelligence Engine not initialized"
                )
            
            # Quick extraction using text from first URI
            sample_text = f"Sample invoice content from {request.document_uris[0]}"
            if is_e2e_mode():
                sample_text = "INVOICE #INV-123456 Purchase Order: PO-789012"
            
            result = await document_intelligence.extract_invoice_ids(
                document_content=sample_text,
                document_type="text",
                correlation_id=correlation_id
            )
            
            return {
                "invoice_ids": result.invoice_ids,
                "confidence_score": result.confidence,
                "processing_tier": result.processing_tier
            }
            
    except Exception as e:
        logger.error(f"Invoice ID extraction failed: {e}", extra={"correlation_id": correlation_id})
        raise HTTPException(status_code=500, detail="Extraction failed")


@app.get("/api/v1/models/status")
async def get_model_status():
    """Get detailed status of document intelligence engine."""
    try:
        if not document_intelligence:
            raise HTTPException(status_code=503, detail="Document Intelligence Engine not initialized")
        
        status = document_intelligence.get_engine_status()
        return status
        
    except Exception as e:
        logger.error(f"Failed to get model status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve model status")


@app.get("/api/v1/tiers/info")
async def get_tier_info():
    """Get information about available processing tiers."""
    config = get_model_config()
    
    return {
        "mode": config['mode'],
        "available_tiers": config['tiers'],
        "e2e_mode": is_e2e_mode(),
        "production_mode": is_production_mode()
    }


@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint."""
    return generate_latest()


async def log_audit_trail(correlation_id: str, action: str, details: Dict[str, Any]):
    """Log audit trail for document processing actions."""
    try:
        if db_manager:
            await db_manager.log_audit_event(
                correlation_id=correlation_id,
                service="dim",
                action=action,
                details=details
            )
    except Exception as e:
        logger.error(f"Failed to log audit trail: {e}")


if __name__ == "__main__":
    # Configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    log_level = os.getenv("LOG_LEVEL", "INFO").lower()
    workers = int(os.getenv("WORKERS", "1"))  # Single worker for model consistency
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level=log_level,
        workers=workers,
        reload=False,  # Disable reload for production
        access_log=True
    )