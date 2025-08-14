# services/cm/app/main.py

import time
import asyncio
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from shared.models import MatchResult, HealthResponse
from shared.logging_config import get_logger, correlation_id_middleware
from shared.health import HealthChecker
from shared.exceptions import CommunicationError
from shared.metrics import MetricsCollector

from .services.email_service import EmailService
from .services.slack_client import SlackClient
from .services.microsoft_graph_client import MicrosoftGraphClient
from .services.template_manager import EmailTemplateManager
from .models.communication_models import (
    ClarificationEmailRequest,
    InternalAlertRequest, 
    BatchNotificationRequest,
    CommunicationResponse
)
from .config import CMSettings

logger = get_logger(__name__)

# Global instances
email_service: EmailService = None
slack_client: SlackClient = None
health_checker: HealthChecker = None
metrics: MetricsCollector = None
settings: CMSettings = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown"""
    # Startup
    global email_service, slack_client, health_checker, metrics, settings
    
    logger.info("Starting Communication Module...")
    
    # Load configuration
    settings = CMSettings()
    
    # Initialize metrics
    metrics = MetricsCollector(service_name="cm")
    
    # Initialize health checker
    health_checker = HealthChecker(service_name="cm")
    
    # Initialize template manager
    template_manager = EmailTemplateManager(settings.TEMPLATES_DIR)
    
    # Initialize Microsoft Graph client
    graph_client = MicrosoftGraphClient(
        tenant_id=settings.AZURE_TENANT_ID,
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET
    )
    
    # Initialize email service
    email_service = EmailService(
        microsoft_graph_client=graph_client,
        template_manager=template_manager,
        settings=settings.dict()
    )
    
    # Initialize Slack client if configured
    if settings.SLACK_BOT_TOKEN:
        slack_client = SlackClient(
            bot_token=settings.SLACK_BOT_TOKEN,
            default_channel=settings.SLACK_DEFAULT_CHANNEL
        )
    else:
        logger.warning("Slack bot token not configured - Slack notifications disabled")
    
    # Test connections
    await _test_connections()
    
    logger.info("CM service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down CM service...")

async def _test_connections():
    """Test connections to external services"""
    try:
        # Test Microsoft Graph
        graph_result = await email_service.graph_client.test_connection()
        logger.info(f"Microsoft Graph test: {graph_result['status']}")
        
        # Test Slack if configured
        if slack_client:
            slack_result = await slack_client.test_connection()
            logger.info(f"Slack test: {slack_result['status']}")
            
    except Exception as e:
        logger.warning(f"Connection tests failed: {str(e)}")

# Create FastAPI app
app = FastAPI(
    title="Communication Module (CM)",
    description="Automated communication service for customer and internal notifications",
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
def get_email_service() -> EmailService:
    if email_service is None:
        raise HTTPException(status_code=503, detail="Email service not initialized")
    return email_service

def get_slack_client() -> SlackClient:
    if slack_client is None:
        raise HTTPException(status_code=503, detail="Slack client not configured")
    return slack_client

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
    """Deep health check including external service connectivity"""
    checks = {
        "service": "healthy",
        "email_service": "checking...",
        "microsoft_graph": "checking...",
        "slack": "checking...",
        "templates": "checking..."
    }
    
    try:
        # Test email service
        if email_service:
            checks["email_service"] = "initialized"
        else:
            checks["email_service"] = "not_initialized"
        
        # Test Microsoft Graph
        if email_service:
            graph_test = await email_service.graph_client.test_connection()
            checks["microsoft_graph"] = graph_test["status"]
        
        # Test Slack
        if slack_client:
            slack_test = await slack_client.test_connection()
            checks["slack"] = slack_test["status"]
        else:
            checks["slack"] = "not_configured"
        
        # Test templates
        if email_service:
            template_count = len(email_service.template_manager.list_templates())
            checks["templates"] = f"loaded_{template_count}_templates"
        
        overall_status = "healthy" if all(
            status not in ["error", "not_initialized"]
            for status in checks.values()
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

@app.post("/api/v1/send_clarification_email", response_model=CommunicationResponse)
async def send_clarification_email(
    request: ClarificationEmailRequest,
    background_tasks: BackgroundTasks,
    email_svc: EmailService = Depends(get_email_service),
    metrics_collector: MetricsCollector = Depends(get_metrics)
):
    """
    Send clarification email to customer for payment discrepancies
    """
    start_time = time.time()
    
    logger.info(f"Clarification email request for transaction {request.match_result.transaction_id}")
    
    try:
        # Validate request
        if not request.customer_info.get('email'):
            raise HTTPException(status_code=400, detail="Customer email is required")
        
        # Track request metrics
        metrics_collector.increment_counter(
            "cm_clarification_emails_total",
            labels={"discrepancy_code": request.match_result.discrepancy_code or "unknown"}
        )
        
        # Send clarification email
        result = await email_svc.send_clarification_email(
            request.match_result,
            request.customer_info
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Track success metrics
        metrics_collector.increment_counter("cm_clarification_success_total")
        metrics_collector.record_histogram(
            "cm_email_processing_duration_ms",
            processing_time,
            labels={"email_type": "clarification", "status": "success"}
        )
        
        # Background logging
        background_tasks.add_task(
            _log_communication_event,
            "clarification_email",
            request.match_result.transaction_id,
            result,
            processing_time
        )
        
        response = CommunicationResponse(
            success=result['success'],
            message_id=result['message_id'],
            provider="microsoft_graph",
            processing_time_ms=processing_time,
            details=result
        )
        
        logger.info(
            f"Clarification email sent successfully - "
            f"Transaction: {request.match_result.transaction_id}, "
            f"Recipient: {request.customer_info['email']}, "
            f"Time: {processing_time}ms"
        )
        
        return response
        
    except CommunicationError as e:
        logger.warning(f"Communication error: {str(e)}")
        metrics_collector.increment_counter(
            "cm_clarification_errors_total",
            labels={"error_type": "communication_error"}
        )
        raise HTTPException(status_code=422, detail=str(e))
        
    except Exception as e:
        logger.error(f"Unexpected error in clarification email: {str(e)}")
        metrics_collector.increment_counter(
            "cm_clarification_errors_total",
            labels={"error_type": "system_error"}
        )
        raise HTTPException(status_code=500, detail="Internal communication error")

@app.post("/api/v1/send_internal_alert", response_model=CommunicationResponse)
async def send_internal_alert(
    request: InternalAlertRequest,
    background_tasks: BackgroundTasks,
    email_svc: EmailService = Depends(get_email_service),
    metrics_collector: MetricsCollector = Depends(get_metrics)
):
    """
    Send internal alert for transactions requiring review
    """
    start_time = time.time()
    
    logger.info(f"Internal alert request for transaction {request.match_result.transaction_id}")
    
    try:
        # Track request metrics
        metrics_collector.increment_counter(
            "cm_internal_alerts_total",
            labels={
                "alert_type": request.alert_type,
                "discrepancy_code": request.match_result.discrepancy_code or "unknown"
            }
        )
        
        results = []
        
        # Send email alert
        if request.alert_type in ['email', 'both']:
            email_result = await email_svc.send_internal_alert(
                request.match_result,
                request.alert_config
            )
            results.append({
                'provider': 'email',
                'result': email_result
            })
        
        # Send Slack alert
        if request.alert_type in ['slack', 'both'] and slack_client:
            slack_result = await slack_client.send_internal_alert(
                request.match_result,
                request.alert_config.get('slack_channel'),
                request.alert_config.get('custom_message')
            )
            results.append({
                'provider': 'slack',
                'result': slack_result
            })
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Track success metrics
        metrics_collector.increment_counter("cm_internal_alert_success_total")
        metrics_collector.record_histogram(
            "cm_alert_processing_duration_ms",
            processing_time,
            labels={"alert_type": request.alert_type, "status": "success"}
        )
        
        # Background logging
        background_tasks.add_task(
            _log_communication_event,
            "internal_alert",
            request.match_result.transaction_id,
            results,
            processing_time
        )
        
        # Return combined result
        primary_result = results[0]['result'] if results else {'success': False}
        
        response = CommunicationResponse(
            success=primary_result['success'],
            message_id=primary_result.get('message_id'),
            provider=request.alert_type,
            processing_time_ms=processing_time,
            details={'results': results}
        )
        
        logger.info(
            f"Internal alert sent successfully - "
            f"Transaction: {request.match_result.transaction_id}, "
            f"Type: {request.alert_type}, "
            f"Time: {processing_time}ms"
        )
        
        return response
        
    except CommunicationError as e:
        logger.warning(f"Communication error: {str(e)}")
        metrics_collector.increment_counter(
            "cm_internal_alert_errors_total",
            labels={"error_type": "communication_error"}
        )
        raise HTTPException(status_code=422, detail=str(e))
        
    except Exception as e:
        logger.error(f"Unexpected error in internal alert: {str(e)}")
        metrics_collector.increment_counter(
            "cm_internal_alert_errors_total",
            labels={"error_type": "system_error"}
        )
        raise HTTPException(status_code=500, detail="Internal communication error")

@app.post("/api/v1/batch_notifications")
async def batch_notifications(
    request: BatchNotificationRequest,
    background_tasks: BackgroundTasks,
    email_svc: EmailService = Depends(get_email_service),
    metrics_collector: MetricsCollector = Depends(get_metrics)
):
    """
    Process multiple notifications in batch
    """
    start_time = time.time()
    
    logger.info(f"Processing batch of {len(request.notifications)} notifications")
    
    if len(request.notifications) > 100:  # Reasonable limit
        raise HTTPException(status_code=400, detail="Batch size too large (max 100 notifications)")
    
    try:
        # Track batch request
        metrics_collector.increment_counter(
            "cm_batch_requests_total",
            labels={"batch_size": str(len(request.notifications))}
        )
        
        # Process email notifications
        email_notifications = [
            n for n in request.notifications 
            if n['type'] in ['clarification_email', 'internal_alert_email']
        ]
        
        if email_notifications:
            email_results = await email_svc.send_batch_notifications(email_notifications)
        else:
            email_results = {'successful': [], 'failed': []}
        
        # Process Slack notifications
        slack_notifications = [
            n for n in request.notifications
            if n['type'] == 'internal_alert_slack'
        ]
        
        if slack_notifications and slack_client:
            slack_results = await slack_client.send_batch_alerts(slack_notifications)
        else:
            slack_results = {'successful': [], 'failed': []}
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Combine results
        total_successful = len(email_results['successful']) + len(slack_results['successful'])
        total_failed = len(email_results['failed']) + len(slack_results['failed'])
        
        # Track metrics
        metrics_collector.record_histogram(
            "cm_batch_processing_duration_ms",
            processing_time,
            labels={"status": "success"}
        )
        metrics_collector.record_histogram(
            "cm_batch_success_rate",
            total_successful / len(request.notifications) if request.notifications else 0,
            labels={"batch_size": str(len(request.notifications))}
        )
        
        response = {
            "total_processed": len(request.notifications),
            "successful_count": total_successful,
            "failed_count": total_failed,
            "processing_time_ms": processing_time,
            "email_results": email_results,
            "slack_results": slack_results,
            "timestamp": time.time()
        }
        
        logger.info(
            f"Batch processing completed - "
            f"Processed: {len(request.notifications)}, "
            f"Successful: {total_successful}, "
            f"Failed: {total_failed}, "
            f"Time: {processing_time}ms"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Batch processing failed: {str(e)}")
        metrics_collector.increment_counter(
            "cm_batch_errors_total",
            labels={"error_type": "system_error"}
        )
        raise HTTPException(status_code=500, detail="Batch processing failed")

@app.get("/api/v1/templates")
async def list_templates(email_svc: EmailService = Depends(get_email_service)):
    """List all available email templates"""
    try:
        templates = email_svc.template_manager.list_templates()
        return {
            "templates": templates,
            "total_count": len(templates)
        }
    except Exception as e:
        logger.error(f"Failed to list templates: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve templates")

@app.post("/api/v1/test_connections")
async def test_connections():
    """Test connectivity to all external services"""
    results = {}
    
    try:
        # Test Microsoft Graph
        if email_service:
            results['microsoft_graph'] = await email_service.graph_client.test_connection()
        
        # Test Slack
        if slack_client:
            results['slack'] = await slack_client.test_connection()
        else:
            results['slack'] = {
                'status': 'not_configured',
                'message': 'Slack client not configured'
            }
        
        return {
            "tests": results,
            "overall_status": "healthy" if all(
                r.get('status') == 'success' for r in results.values()
            ) else "degraded",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Connection tests failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Connection tests failed")

@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    if metrics is None:
        raise HTTPException(status_code=503, detail="Metrics not available")
    
    return metrics.get_metrics()

# Helper functions

async def _log_communication_event(
    event_type: str,
    transaction_id: str,
    result: Any,
    processing_time: int
):
    """Background task for detailed communication logging"""
    try:
        logger.info(
            f"Communication event completed - "
            f"Type: {event_type}, "
            f"Transaction: {transaction_id}, "
            f"Success: {result.get('success', False) if isinstance(result, dict) else 'unknown'}, "
            f"Processing time: {processing_time}ms"
        )
        
        # Could add detailed audit logging to database here
        
    except Exception as e:
        logger.warning(f"Background communication logging failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8004,
        reload=True,
        log_config=None
    )