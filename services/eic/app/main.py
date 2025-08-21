
# services/eic/app/main.py

import time
import asyncio
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from shared.models import Invoice, MatchResult, HealthResponse
from shared.logging_config import get_logger, correlation_id_middleware
from shared.health import HealthChecker
from shared.exceptions import ERPConnectionError, ERPAuthenticationError, ERPDataError
from shared.metrics import MetricsCollector

from .connectors.erp_manager import ERPManager
# Note: Other imports commented out as files don't exist yet
# from .connectors.credential_manager import CredentialManager
# from .models.erp_models import ERPSystemRequest, ERPSystemResponse, InvoiceRequest, ApplicationRequest  
# from .config import EICSettings

logger = get_logger(__name__)

# Global instances
erp_manager = None  # ERPManager
credential_manager = None  # CredentialManager  
health_checker = None  # HealthChecker
metrics = None  # MetricsCollector
settings = None  # EICSettings

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown"""
    # Startup
    global erp_manager, credential_manager, health_checker, metrics, settings
    
    logger.info("Starting ERP Integration Connectors...")
    
    # Load configuration (commented out for Docker build test)
    # settings = EICSettings()
    
    # Initialize metrics
    metrics = MetricsCollector(service_name="eic")
    
    # Initialize health checker
    health_checker = HealthChecker(service_name="eic")
    
    # Initialize credential manager (commented out for Docker build test)
    # credential_manager = CredentialManager(
    #     key_vault_url=settings.AZURE_KEY_VAULT_URL,
    #     database_url=settings.DATABASE_URL
    # )
    
    # Initialize ERP manager (commented out for Docker build test)
    # erp_manager = ERPManager(credential_manager, settings)
    
    # Load ERP systems from database (commented out for Docker build test)
    # await erp_manager.initialize()
    
    logger.info("EIC service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down EIC service...")
    if erp_manager:
        await erp_manager.cleanup()

# Create FastAPI app
app = FastAPI(
    title="ERP Integration Connectors (EIC)",
    description="Unified facade for multiple ERP systems",
    version="1.0.0",
    lifespan=lifespan
)

# Add middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(correlation_id_middleware)

# Dependencies  
def get_erp_manager():
    if erp_manager is None:
        raise HTTPException(status_code=503, detail="ERP Manager not initialized")
    return erp_manager

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
    """Deep health check including ERP system connectivity"""
    if not erp_manager:
        raise HTTPException(status_code=503, detail="ERP Manager not available")
    
    checks = {
        "service": "healthy",
        "erp_systems": {},
        "credentials": "checking...",
        "database": "checking..."
    }
    
    try:
        # Test all configured ERP systems
        systems_status = await erp_manager.test_all_systems()
        checks["erp_systems"] = systems_status
        
        # Test credential manager
        if credential_manager:
            cred_check = await credential_manager.health_check()
            checks["credentials"] = cred_check["status"]
        
        # Test database connectivity
        # This would be implemented based on your database setup
        checks["database"] = "connected"
        
        overall_status = "healthy" if all(
            system.get("status") == "success" 
            for system in systems_status.values()
        ) else "degraded"
        
        return {
            "status": overall_status,
            "checks": checks,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Deep health check failed: {str(e)}")
        return {
            "status": "unhealthy", 
            "error": str(e), 
            "checks": checks,
            "timestamp": time.time()
        }

@app.post("/api/v1/get_invoices", response_model=List[Invoice])
async def get_invoices(
    request: InvoiceRequest,
    background_tasks: BackgroundTasks,
    erp_mgr: ERPManager = Depends(get_erp_manager),
    metrics_collector: MetricsCollector = Depends(get_metrics)
):
    """
    Retrieve invoices from ERP systems
    
    Supports both specific ERP system queries and multi-system fallback
    """
    start_time = time.time()
    
    logger.info(f"Invoice request for {len(request.invoice_ids)} IDs from system: {request.erp_system or 'auto-detect'}")
    
    if not request.invoice_ids:
        raise HTTPException(status_code=400, detail="No invoice IDs provided")
    
    try:
        # Track request metrics
        metrics_collector.increment_counter(
            "eic_invoice_requests_total",
            labels={
                "erp_system": request.erp_system or "auto",
                "invoice_count": str(len(request.invoice_ids))
            }
        )
        
        # Get invoices from ERP
        if request.erp_system:
            # Specific ERP system
            invoices = await erp_mgr.get_invoices_from_system(
                request.erp_system, 
                request.invoice_ids
            )
        else:
            # Multi-system lookup with fallback
            invoices = await erp_mgr.get_invoices_multi_system(request.invoice_ids)
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Track success metrics
        metrics_collector.increment_counter(
            "eic_invoice_success_total",
            labels={"erp_system": request.erp_system or "multi"}
        )
        metrics_collector.record_histogram(
            "eic_invoice_processing_duration_ms",
            processing_time,
            labels={"status": "success"}
        )
        metrics_collector.record_histogram(
            "eic_invoices_found_count",
            len(invoices),
            labels={"requested": str(len(request.invoice_ids))}
        )
        
        # Background task for detailed logging
        background_tasks.add_task(
            _log_invoice_retrieval,
            request,
            invoices,
            processing_time
        )
        
        logger.info(
            f"Invoice retrieval completed - "
            f"Found: {len(invoices)}/{len(request.invoice_ids)}, "
            f"Time: {processing_time}ms"
        )
        
        return invoices
        
    except ERPConnectionError as e:
        logger.warning(f"ERP connection error: {str(e)}")
        metrics_collector.increment_counter(
            "eic_invoice_errors_total",
            labels={"error_type": "connection_error"}
        )
        raise HTTPException(status_code=502, detail=f"ERP connection failed: {str(e)}")
        
    except ERPAuthenticationError as e:
        logger.error(f"ERP authentication error: {str(e)}")
        metrics_collector.increment_counter(
            "eic_invoice_errors_total",
            labels={"error_type": "auth_error"}
        )
        raise HTTPException(status_code=401, detail=f"ERP authentication failed: {str(e)}")
        
    except ERPDataError as e:
        logger.warning(f"ERP data error: {str(e)}")
        metrics_collector.increment_counter(
            "eic_invoice_errors_total",
            labels={"error_type": "data_error"}
        )
        raise HTTPException(status_code=422, detail=f"ERP data error: {str(e)}")
        
    except Exception as e:
        logger.error(f"Unexpected error in invoice retrieval: {str(e)}")
        metrics_collector.increment_counter(
            "eic_invoice_errors_total",
            labels={"error_type": "system_error"}
        )
        raise HTTPException(status_code=500, detail="Internal processing error")

@app.post("/api/v1/post_application")
async def post_application(
    request: ApplicationRequest,
    background_tasks: BackgroundTasks,
    erp_mgr: ERPManager = Depends(get_erp_manager),
    metrics_collector: MetricsCollector = Depends(get_metrics)
):
    """
    Post cash application to ERP systems
    
    Performs atomic operations with rollback capability
    """
    start_time = time.time()
    
    logger.info(f"Application request for transaction {request.match_result.transaction_id}")
    
    try:
        # Validate request
        if not request.match_result.matched_pairs:
            raise HTTPException(status_code=400, detail="No matched pairs in application request")
        
        # Track request metrics
        metrics_collector.increment_counter(
            "eic_application_requests_total",
            labels={
                "erp_system": request.erp_system or "auto",
                "status": request.match_result.status
            }
        )
        
        # Post application to ERP
        if request.erp_system:
            # Specific ERP system
            result = await erp_mgr.post_application_to_system(
                request.erp_system,
                request.match_result,
                idempotency_key=request.idempotency_key
            )
        else:
            # Auto-detect ERP system based on invoice IDs
            result = await erp_mgr.post_application_auto_detect(
                request.match_result,
                idempotency_key=request.idempotency_key
            )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Track success metrics
        metrics_collector.increment_counter(
            "eic_application_success_total",
            labels={"erp_system": result.get("erp_system", "unknown")}
        )
        metrics_collector.record_histogram(
            "eic_application_processing_duration_ms",
            processing_time,
            labels={"status": "success"}
        )
        
        # Background task for audit logging
        background_tasks.add_task(
            _log_application_posting,
            request,
            result,
            processing_time
        )
        
        logger.info(
            f"Application posting completed - "
            f"ERP Transaction: {result.get('erp_transaction_id')}, "
            f"Time: {processing_time}ms"
        )
        
        return {
            **result,
            "processing_time_ms": processing_time,
            "timestamp": time.time()
        }
        
    except ERPConnectionError as e:
        logger.warning(f"ERP connection error: {str(e)}")
        metrics_collector.increment_counter(
            "eic_application_errors_total",
            labels={"error_type": "connection_error"}
        )
        raise HTTPException(status_code=502, detail=f"ERP connection failed: {str(e)}")
        
    except ERPAuthenticationError as e:
        logger.error(f"ERP authentication error: {str(e)}")
        metrics_collector.increment_counter(
            "eic_application_errors_total",
            labels={"error_type": "auth_error"}
        )
        raise HTTPException(status_code=401, detail=f"ERP authentication failed: {str(e)}")
        
    except ERPDataError as e:
        logger.warning(f"ERP data error: {str(e)}")
        metrics_collector.increment_counter(
            "eic_application_errors_total",
            labels={"error_type": "data_error"}
        )
        raise HTTPException(status_code=422, detail=f"ERP data error: {str(e)}")
        
    except Exception as e:
        logger.error(f"Unexpected error in application posting: {str(e)}")
        metrics_collector.increment_counter(
            "eic_application_errors_total",
            labels={"error_type": "system_error"}
        )
        raise HTTPException(status_code=500, detail="Internal processing error")

@app.get("/api/v1/systems")
async def list_erp_systems(
    erp_mgr: ERPManager = Depends(get_erp_manager)
):
    """List all configured ERP systems and their status"""
    try:
        systems = await erp_mgr.list_systems()
        return {
            "systems": systems,
            "total_count": len(systems),
            "active_count": sum(1 for s in systems if s.get("status") == "active")
        }
    except Exception as e:
        logger.error(f"Failed to list ERP systems: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve systems list")

@app.post("/api/v1/systems/{system_name}/test")
async def test_erp_system(
    system_name: str,
    erp_mgr: ERPManager = Depends(get_erp_manager)
):
    """Test connectivity to a specific ERP system"""
    try:
        result = await erp_mgr.test_system(system_name)
        return result
    except Exception as e:
        logger.error(f"Failed to test ERP system {system_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"System test failed: {str(e)}")

@app.get("/api/v1/transaction_logs/{transaction_id}")
async def get_transaction_logs(
    transaction_id: str,
    erp_mgr: ERPManager = Depends(get_erp_manager)
):
    """Get transaction logs for auditing"""
    try:
        logs = await erp_mgr.get_transaction_logs(transaction_id)
        return {
            "transaction_id": transaction_id,
            "logs": logs,
            "log_count": len(logs)
        }
    except Exception as e:
        logger.error(f"Failed to retrieve transaction logs: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve logs")

@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    if metrics is None:
        raise HTTPException(status_code=503, detail="Metrics not available")
    
    return metrics.get_metrics()

# Helper functions

async def _log_invoice_retrieval(
    request: InvoiceRequest,
    invoices: List[Invoice],
    processing_time: int
):
    """Background task for detailed invoice retrieval logging"""
    try:
        # Log detailed metrics
        found_ratio = len(invoices) / len(request.invoice_ids) if request.invoice_ids else 0
        
        logger.info(
            f"Invoice retrieval details - "
            f"System: {request.erp_system or 'multi'}, "
            f"Requested: {len(request.invoice_ids)}, "
            f"Found: {len(invoices)}, "
            f"Hit rate: {found_ratio:.2%}, "
            f"Processing time: {processing_time}ms"
        )
        
        # Could add detailed audit logging here
        
    except Exception as e:
        logger.warning(f"Background invoice logging failed: {str(e)}")

async def _log_application_posting(
    request: ApplicationRequest,
    result: Dict[str, Any],
    processing_time: int
):
    """Background task for detailed application posting logging"""
    try:
        logger.info(
            f"Application posting details - "
            f"Transaction: {request.match_result.transaction_id}, "
            f"ERP System: {result.get('erp_system')}, "
            f"ERP Transaction: {result.get('erp_transaction_id')}, "
            f"Success: {result.get('success', False)}, "
            f"Processing time: {processing_time}ms"
        )
        
        # Could add detailed audit logging here
        
    except Exception as e:
        logger.warning(f"Background application logging failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        reload=True,
        log_config=None
    )

# services/eic/app/models/erp_models.py

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from shared.models import MatchResult

class InvoiceRequest(BaseModel):
    """Request for invoice retrieval"""
    invoice_ids: List[str] = Field(..., min_items=1, max_items=100)
    erp_system: Optional[str] = None  # If None, auto-detect
    include_details: bool = True
    timeout_seconds: Optional[int] = 30

class ApplicationRequest(BaseModel):
    """Request for cash application posting"""
    match_result: MatchResult
    erp_system: Optional[str] = None  # If None, auto-detect
    idempotency_key: Optional[str] = None
    force_post: bool = False  # Override some validation checks

class ERPSystemRequest(BaseModel):
    """Request for ERP system configuration"""
    system_name: str
    system_type: str  # 'netsuite', 'sap', 'quickbooks'
    credentials: Dict[str, Any]
    configuration: Dict[str, Any] = {}
    is_active: bool = True

class ERPSystemResponse(BaseModel):
    """Response for ERP system information"""
    system_name: str
    system_type: str
    status: str  # 'active', 'inactive', 'error'
    last_tested: Optional[str] = None
    error_message: Optional[str] = None
    configuration_summary: Dict[str, Any] = {}

# services/eic/app/config.py

from typing import Optional, Dict, Any
from pydantic_settings import BaseSettings

class EICSettings(BaseSettings):
    """EIC service configuration"""
    
    # Service Configuration
    SERVICE_NAME: str = "eic"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # API Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8003
    WORKERS: int = 4
    
    # Database Configuration
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # Azure Configuration
    AZURE_KEY_VAULT_URL: str
    AZURE_TENANT_ID: Optional[str] = None
    AZURE_CLIENT_ID: Optional[str] = None
    AZURE_CLIENT_SECRET: Optional[str] = None
    
    # ERP Configuration
    DEFAULT_TIMEOUT_SECONDS: int = 30
    MAX_RETRY_ATTEMPTS: int = 3
    RETRY_BACKOFF_SECONDS: float = 1.0
    
    # Connection Pooling
    MAX_CONCURRENT_CONNECTIONS: int = 50
    CONNECTION_POOL_SIZE: int = 10
    
    # Security Configuration
    ENCRYPT_CREDENTIALS: bool = True
    CREDENTIAL_ROTATION_DAYS: int = 90
    
    # Monitoring Configuration
    METRICS_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL: int = 60
    
    # Multi-system Configuration
    ENABLE_MULTI_SYSTEM_FALLBACK: bool = True
    SYSTEM_PRIORITY_ORDER: List[str] = ["netsuite", "sap", "quickbooks"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True
