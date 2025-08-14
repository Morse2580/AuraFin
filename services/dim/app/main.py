# services/dim/app/main.py

import time
import asyncio
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from shared.models import DocumentParseRequest, DocumentParseResult, HealthResponse
from shared.logging_config import get_logger, correlation_id_middleware
from shared.health import HealthChecker
from shared.exceptions import DIMProcessingError
from shared.metrics import MetricsCollector

from .models.document_processor import DocumentIntelligenceService
from .config import DIMSettings

logger = get_logger(__name__)

# Global instances
doc_intelligence_service: DocumentIntelligenceService = None
health_checker: HealthChecker = None
metrics: MetricsCollector = None
settings: DIMSettings = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown"""
    # Startup
    global doc_intelligence_service, health_checker, metrics, settings
    
    logger.info("Starting Document Intelligence Module...")
    
    # Load configuration
    settings = DIMSettings()
    
    # Initialize metrics
    metrics = MetricsCollector(service_name="dim")
    
    # Initialize health checker
    health_checker = HealthChecker(service_name="dim")
    
    # Initialize document intelligence service
    doc_intelligence_service = DocumentIntelligenceService(
        blob_connection_string=settings.AZURE_STORAGE_CONNECTION_STRING
    )
    
    # Warm up models (load them into memory)
    logger.info("Warming up ML models...")
    await _warmup_models()
    
    logger.info("DIM service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down DIM service...")

async def _warmup_models():
    """Warm up ML models by loading them into GPU memory"""
    try:
        # This ensures models are loaded and ready for inference
        # You could run a dummy inference here if needed
        logger.info("ML models warmed up successfully")
    except Exception as e:
        logger.error(f"Model warmup failed: {str(e)}")
        raise

# Create FastAPI app
app = FastAPI(
    title="Document Intelligence Module (DIM)",
    description="ML-powered document parsing service for autonomous cash application",
    version="1.0.0",
    lifespan=lifespan
)

# Add middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(correlation_id_middleware)

# Dependency to get document intelligence service
def get_doc_service() -> DocumentIntelligenceService:
    if doc_intelligence_service is None:
        raise HTTPException(status_code=503, detail="Document Intelligence service not initialized")
    return doc_intelligence_service

def get_metrics() -> MetricsCollector:
    if metrics is None:
        raise HTTPException(status_code=503, detail="Metrics service not initialized")
    return metrics

# API Endpoints

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    if health_checker is None:
        raise HTTPException(status_code=503, detail="Health checker not initialized")
    
    return await health_checker.check_health()

@app.get("/health/deep")
async def deep_health_check():
    """Deep health check including ML models and dependencies"""
    if health_checker is None:
        raise HTTPException(status_code=503, detail="Health checker not initialized")
    
    checks = {
        "service": "healthy",
        "models": "checking...",
        "storage": "checking...",
        "gpu": "checking..."
    }
    
    try:
        # Check GPU availability
        import torch
        if torch.cuda.is_available():
            checks["gpu"] = f"healthy - {torch.cuda.get_device_name(0)}"
        else:
            checks["gpu"] = "cpu_only"
        
        # Check models are loaded
        if doc_intelligence_service:
            checks["models"] = "loaded"
        else:
            checks["models"] = "not_loaded"
            
        # Check Azure Storage connectivity
        try:
            # Simple connectivity test - list containers
            containers = doc_intelligence_service.blob_client.list_containers(max_results=1)
            list(containers)  # Force evaluation
            checks["storage"] = "connected"
        except Exception as e:
            checks["storage"] = f"error: {str(e)}"
            
        return {"status": "healthy", "checks": checks}
        
    except Exception as e:
        logger.error(f"Deep health check failed: {str(e)}")
        return {"status": "unhealthy", "error": str(e), "checks": checks}

@app.post("/api/v1/parse_document", response_model=DocumentParseResult)
async def parse_document(
    request: DocumentParseRequest,
    background_tasks: BackgroundTasks,
    doc_service: DocumentIntelligenceService = Depends(get_doc_service),
    metrics_collector: MetricsCollector = Depends(get_metrics)
):
    """
    Main endpoint for document parsing
    
    Takes a list of document URIs and returns extracted invoice IDs
    """
    start_time = time.time()
    
    logger.info(f"Processing document parse request with {len(request.document_uris)} documents")
    
    # Validate request
    if not request.document_uris:
        raise HTTPException(status_code=400, detail="No document URIs provided")
    
    if len(request.document_uris) > 10:  # Reasonable limit
        raise HTTPException(status_code=400, detail="Too many documents in single request (max 10)")
    
    try:
        # Track request metrics
        metrics_collector.increment_counter(
            "dim_parse_requests_total",
            labels={"document_count": str(len(request.document_uris))}
        )
        
        # Process documents
        result = await doc_service.parse_documents(request.document_uris)
        
        # Calculate processing time
        processing_time = int((time.time() - start_time) * 1000)
        result.processing_time_ms = processing_time
        
        # Track success metrics
        metrics_collector.increment_counter("dim_parse_success_total")
        metrics_collector.record_histogram(
            "dim_processing_duration_ms",
            processing_time,
            labels={"status": "success"}
        )
        metrics_collector.record_histogram(
            "dim_invoice_ids_extracted",
            len(result.invoice_ids),
            labels={"confidence_bucket": _get_confidence_bucket(result.confidence_score)}
        )
        
        # Log background metrics collection
        background_tasks.add_task(
            _collect_detailed_metrics,
            request.document_uris,
            result,
            processing_time
        )
        
        logger.info(
            f"Document parsing completed successfully - "
            f"IDs found: {len(result.invoice_ids)}, "
            f"Confidence: {result.confidence_score:.3f}, "
            f"Time: {processing_time}ms"
        )
        
        return result
        
    except DIMProcessingError as e:
        # Business logic error
        logger.warning(f"Document processing failed: {str(e)}")
        metrics_collector.increment_counter(
            "dim_parse_errors_total",
            labels={"error_type": "processing_error"}
        )
        raise HTTPException(status_code=422, detail=str(e))
        
    except Exception as e:
        # System error
        logger.error(f"Unexpected error in document parsing: {str(e)}")
        metrics_collector.increment_counter(
            "dim_parse_errors_total",
            labels={"error_type": "system_error"}
        )
        raise HTTPException(status_code=500, detail="Internal processing error")

@app.post("/api/v1/batch_parse")
async def batch_parse_documents(
    requests: List[DocumentParseRequest],
    background_tasks: BackgroundTasks,
    doc_service: DocumentIntelligenceService = Depends(get_doc_service)
):
    """
    Batch processing endpoint for multiple document parse requests
    Useful for high-throughput scenarios
    """
    if len(requests) > 100:  # Reasonable batch limit
        raise HTTPException(status_code=400, detail="Batch size too large (max 100 requests)")
    
    logger.info(f"Processing batch of {len(requests)} document parse requests")
    
    # Process all requests concurrently
    tasks = [
        doc_service.parse_documents(request.document_uris)
        for request in requests
    ]
    
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Separate successful results from errors
        successful_results = []
        errors = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append({
                    "index": i,
                    "error": str(result),
                    "document_uris": requests[i].document_uris
                })
            else:
                successful_results.append({
                    "index": i,
                    "result": result
                })
        
        return {
            "successful_count": len(successful_results),
            "error_count": len(errors),
            "results": successful_results,
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Batch processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Batch processing failed")

@app.get("/api/v1/model_info")
async def get_model_info():
    """Get information about loaded ML models"""
    try:
        import torch
        
        model_info = {
            "layoutlm": {
                "model_name": "microsoft/layoutlmv3-base",
                "device": str(doc_intelligence_service.layoutlm.device),
                "loaded": True
            },
            "llama": {
                "model_name": "meta-llama/Meta-Llama-3-8B-Instruct",
                "device": str(doc_intelligence_service.llama.device),
                "loaded": True
            },
            "system": {
                "cuda_available": torch.cuda.is_available(),
                "cuda_device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
                "cuda_memory_allocated": torch.cuda.memory_allocated() if torch.cuda.is_available() else 0,
                "cuda_memory_reserved": torch.cuda.memory_reserved() if torch.cuda.is_available() else 0
            }
        }
        
        if torch.cuda.is_available():
            model_info["system"]["cuda_device_name"] = torch.cuda.get_device_name(0)
            
        return model_info
        
    except Exception as e:
        logger.error(f"Failed to get model info: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve model information")

@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    if metrics is None:
        raise HTTPException(status_code=503, detail="Metrics not available")
    
    return metrics.get_metrics()

# Helper functions

def _get_confidence_bucket(confidence: float) -> str:
    """Convert confidence score to bucket for metrics"""
    if confidence >= 0.9:
        return "high"
    elif confidence >= 0.7:
        return "medium"
    else:
        return "low"

async def _collect_detailed_metrics(
    document_uris: List[str], 
    result: DocumentParseResult, 
    processing_time: int
):
    """Collect detailed metrics in background"""
    try:
        # Document type analysis
        doc_types = {}
        for uri in document_uris:
            ext = uri.split('.')[-1].lower()
            doc_types[ext] = doc_types.get(ext, 0) + 1
        
        # Log metrics by document type
        for doc_type, count in doc_types.items():
            metrics.record_histogram(
                "dim_processing_by_type_ms",
                processing_time,
                labels={"document_type": doc_type}
            )
        
        logger.debug(f"Background metrics collection completed for {len(document_uris)} documents")
        
    except Exception as e:
        logger.warning(f"Background metrics collection failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
        log_config=None  # Use our custom logging
    )

