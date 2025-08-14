# services/dim/main.py
"""
Document Intelligence Module (DIM) - The "Eyes"
Aura Finance CashAppAgent - ML-powered document parsing service

This service implements a 2-stage ML pipeline:
1. OCR & Layout Analysis (LayoutLMv3)
2. Contextual Comprehension & Extraction (Llama-3-8B)
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from pathlib import Path

# Temporarily disabled for E2E testing
# import torch
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import uvicorn
from pydantic import BaseModel, Field, validator
from prometheus_client import Counter, Histogram, Gauge, generate_latest
# from prometheus_fastapi_instrumentator import Instrumentator

from shared.logging import setup_logging, get_correlation_id, log_context
from shared.database import DatabaseManager
from shared.models import DocumentParseRequest, DocumentParseResponse, InvoiceExtractionResult
from shared.exceptions import DIMError, ModelLoadError, DocumentProcessingError
from shared.health import health_check_endpoint
from shared.metrics import DIM_METRICS

from ml_pipeline import MLPipeline
from document_processor import DocumentProcessor
from services.dim.models.model_manager import ModelManager
from azure_storage import AzureBlobStorageClient

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
ml_pipeline: Optional[MLPipeline] = None
document_processor: Optional[DocumentProcessor] = None
model_manager: Optional[ModelManager] = None
storage_client: Optional[AzureBlobStorageClient] = None
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


class ModelHealthStatus(BaseModel):
    """Model health status response."""
    layoutlmv3_loaded: bool
    llama_loaded: bool
    gpu_available: bool
    memory_usage_mb: float
    model_versions: Dict[str, str]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global ml_pipeline, document_processor, model_manager, storage_client, db_manager
    
    logger.info("Starting Document Intelligence Module (DIM)...")
    
    try:
        # Initialize database
        db_manager = DatabaseManager()
        await db_manager.initialize()
        
        # Initialize Azure storage client
        storage_client = AzureBlobStorageClient()
        
        # Initialize model manager
        model_manager = ModelManager()
        await model_manager.initialize()
        
        # Initialize ML pipeline
        ml_pipeline = MLPipeline(model_manager)
        await ml_pipeline.initialize()
        
        # Initialize document processor
        document_processor = DocumentProcessor(
            ml_pipeline=ml_pipeline,
            storage_client=storage_client,
            db_manager=db_manager
        )
        
        logger.info("DIM service initialized successfully")
        yield
        
    except Exception as e:
        logger.error(f"Failed to initialize DIM service: {e}")
        raise
    finally:
        # Cleanup
        if ml_pipeline:
            await ml_pipeline.cleanup()
        if db_manager:
            await db_manager.close()
        logger.info("DIM service shut down")


# Create FastAPI app
app = FastAPI(
    title="Document Intelligence Module (DIM)",
    description="ML-powered document parsing service for CashAppAgent",
    version="1.0.0",
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

# Setup Prometheus metrics
# instrumentator = Instrumentator()
# instrumentator.instrument(app).expose(app)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Check database connectivity
        db_healthy = await db_manager.health_check() if db_manager else False
        
        # Check model availability
        models_healthy = (
            ml_pipeline.is_healthy() if ml_pipeline else False
        )
        
        # Check GPU availability
        gpu_available = torch.cuda.is_available()
        
        status = "healthy" if all([db_healthy, models_healthy]) else "unhealthy"
        
        return {
            "status": status,
            "timestamp": time.time(),
            "service": "dim",
            "version": "1.0.0",
            "checks": {
                "database": "healthy" if db_healthy else "unhealthy",
                "models": "healthy" if models_healthy else "unhealthy",
                "gpu": "available" if gpu_available else "unavailable"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


@app.get("/health/models", response_model=ModelHealthStatus)
async def model_health_check():
    """Detailed model health check."""
    try:
        if not ml_pipeline:
            raise HTTPException(status_code=503, detail="ML pipeline not initialized")
        
        status = await ml_pipeline.get_health_status()
        return ModelHealthStatus(**status)
        
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
    Parse documents and extract invoice IDs using ML pipeline.
    
    This endpoint implements the core DIM functionality:
    1. Download documents from Azure Blob Storage
    2. Run OCR & layout analysis (LayoutLMv3)
    3. Extract invoice IDs using contextual understanding (Llama-3-8B)
    4. Return structured results with confidence scores
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
            
            if not document_processor:
                raise HTTPException(
                    status_code=503, 
                    detail="Document processor not initialized"
                )
            
            # Process documents
            result = await document_processor.process_documents(
                document_uris=request.document_uris,
                client_id=request.client_id,
                processing_options=request.processing_options,
                correlation_id=correlation_id
            )
            
            # Calculate processing duration
            processing_duration_ms = int((time.time() - start_time) * 1000)
            
            # Update metrics
            DOCUMENTS_PROCESSED.labels(
                document_type="remittance_advice", 
                status="success"
            ).inc(len(request.document_uris))
            
            PROCESSING_DURATION.labels(
                stage="total",
                model_type="combined"
            ).observe(time.time() - start_time)
            
            CONFIDENCE_SCORE.observe(result.confidence_score)
            
            # Log async audit trail
            background_tasks.add_task(
                log_audit_trail,
                correlation_id=correlation_id,
                action="document_processed",
                details={
                    "document_count": len(request.document_uris),
                    "invoice_ids_found": len(result.invoice_ids),
                    "confidence_score": result.confidence_score,
                    "processing_duration_ms": processing_duration_ms
                }
            )
            
            logger.info(
                f"Document processing completed successfully",
                extra={
                    "invoice_ids_count": len(result.invoice_ids),
                    "confidence_score": result.confidence_score,
                    "processing_duration_ms": processing_duration_ms,
                    "correlation_id": correlation_id
                }
            )
            
            return DocumentParseResponseBody(
                request_id=correlation_id,
                invoice_ids=result.invoice_ids,
                confidence_score=result.confidence_score,
                processing_duration_ms=processing_duration_ms,
                document_analysis=result.document_analysis,
                warnings=result.warnings
            )
            
    except DocumentProcessingError as e:
        DOCUMENTS_PROCESSED.labels(
            document_type="remittance_advice",
            status="processing_error"
        ).inc()
        logger.error(f"Document processing error: {e}", extra={"correlation_id": correlation_id})
        raise HTTPException(status_code=422, detail=str(e))
        
    except ModelLoadError as e:
        DOCUMENTS_PROCESSED.labels(
            document_type="remittance_advice",
            status="model_error"
        ).inc()
        logger.error(f"Model error: {e}", extra={"correlation_id": correlation_id})
        raise HTTPException(status_code=503, detail="ML model unavailable")
        
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
            if not document_processor:
                raise HTTPException(
                    status_code=503, 
                    detail="Document processor not initialized"
                )
            
            # Quick extraction mode
            result = await document_processor.extract_invoice_ids_only(
                document_uris=request.document_uris,
                correlation_id=correlation_id
            )
            
            return {
                "invoice_ids": result.invoice_ids,
                "confidence_score": result.confidence_score
            }
            
    except Exception as e:
        logger.error(f"Invoice ID extraction failed: {e}", extra={"correlation_id": correlation_id})
        raise HTTPException(status_code=500, detail="Extraction failed")


@app.get("/api/v1/models/status")
async def get_model_status():
    """Get detailed status of all loaded models."""
    try:
        if not model_manager:
            raise HTTPException(status_code=503, detail="Model manager not initialized")
        
        status = await model_manager.get_detailed_status()
        return status
        
    except Exception as e:
        logger.error(f"Failed to get model status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve model status")


@app.post("/api/v1/models/reload")
async def reload_models():
    """Reload ML models (admin endpoint)."""
    try:
        if not ml_pipeline:
            raise HTTPException(status_code=503, detail="ML pipeline not initialized")
        
        await ml_pipeline.reload_models()
        return {"status": "success", "message": "Models reloaded successfully"}
        
    except Exception as e:
        logger.error(f"Failed to reload models: {e}")
        raise HTTPException(status_code=500, detail="Failed to reload models")


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
    workers = int(os.getenv("WORKERS", "1"))  # Single worker for GPU models
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level=log_level,
        workers=workers,
        reload=False,  # Disable reload for production
        access_log=True
    )

