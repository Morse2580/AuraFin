from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import asyncio
import logging
from typing import Dict, Any
from temporalio.client import Client
from workflows.cash_application import CashApplicationWorkflow, CollectionsWorkflow, CreditManagementWorkflow
from prometheus_client import make_asgi_app, Counter, Histogram, Gauge
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus metrics
workflow_counter = Counter(
    'temporal_workflows_total',
    'Total number of workflows started',
    ['workflow_type', 'client_id']
)

workflow_duration = Histogram(
    'temporal_workflow_duration_seconds',
    'Workflow execution duration',
    ['workflow_type']
)

active_workflows = Gauge(
    'temporal_active_workflows',
    'Number of active workflows',
    ['workflow_type']
)

app = FastAPI(
    title="CashApp Orchestrator Service",
    description="Temporal-based workflow orchestration for CashAppAgent",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Temporal client
temporal_client = None

@app.on_event("startup")
async def startup_event():
    """Initialize Temporal client on startup"""
    global temporal_client
    temporal_host = os.getenv('TEMPORAL_HOST', 'temporal:7233')
    
    try:
        temporal_client = await Client.connect(temporal_host)
        logger.info(f"Connected to Temporal server at {temporal_host}")
    except Exception as e:
        logger.error(f"Failed to connect to Temporal server: {str(e)}")
        raise


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "orchestrator",
        "temporal_connected": temporal_client is not None,
        "timestamp": time.time()
    }


@app.post("/api/v1/workflows/cash-application/start")
async def start_cash_application_workflow(
    transaction: Dict[str, Any],
    background_tasks: BackgroundTasks
):
    """
    Start a cash application workflow for transaction processing
    """
    try:
        if not temporal_client:
            raise HTTPException(status_code=503, detail="Temporal client not available")
        
        transaction_id = transaction.get('id')
        if not transaction_id:
            raise HTTPException(status_code=400, detail="Transaction ID is required")
        
        # Start workflow
        workflow_handle = await temporal_client.start_workflow(
            CashApplicationWorkflow.run,
            transaction,
            id=f"cash-application-{transaction_id}",
            task_queue="cashapp-task-queue",
        )
        
        # Record metrics
        workflow_counter.labels(
            workflow_type='cash_application',
            client_id=transaction.get('client_id', 'unknown')
        ).inc()
        active_workflows.labels(workflow_type='cash_application').inc()
        
        logger.info(f"Started cash application workflow: {workflow_handle.id}")
        
        return {
            "status": "started",
            "workflow_id": workflow_handle.id,
            "transaction_id": transaction_id,
            "run_id": workflow_handle.result_run_id
        }
        
    except Exception as e:
        logger.error(f"Failed to start cash application workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/workflows/collections/start")
async def start_collections_workflow(
    overdue_invoices: Dict[str, Any]
):
    """
    Start a collections workflow for overdue invoices
    """
    try:
        if not temporal_client:
            raise HTTPException(status_code=503, detail="Temporal client not available")
        
        invoice_list = overdue_invoices.get('invoices', [])
        if not invoice_list:
            raise HTTPException(status_code=400, detail="Invoice list is required")
        
        workflow_id = f"collections-{len(invoice_list)}-{int(time.time())}"
        
        # Start workflow
        workflow_handle = await temporal_client.start_workflow(
            CollectionsWorkflow.run,
            invoice_list,
            id=workflow_id,
            task_queue="cashapp-task-queue",
        )
        
        # Record metrics
        workflow_counter.labels(
            workflow_type='collections',
            client_id=overdue_invoices.get('client_id', 'unknown')
        ).inc()
        active_workflows.labels(workflow_type='collections').inc()
        
        logger.info(f"Started collections workflow: {workflow_handle.id} for {len(invoice_list)} invoices")
        
        return {
            "status": "started",
            "workflow_id": workflow_handle.id,
            "invoice_count": len(invoice_list),
            "run_id": workflow_handle.result_run_id
        }
        
    except Exception as e:
        logger.error(f"Failed to start collections workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/workflows/credit-management/start")
async def start_credit_management_workflow(
    customer_data: Dict[str, Any]
):
    """
    Start a credit management workflow for risk assessment
    """
    try:
        if not temporal_client:
            raise HTTPException(status_code=503, detail="Temporal client not available")
        
        customer_id = customer_data.get('customer_id')
        if not customer_id:
            raise HTTPException(status_code=400, detail="Customer ID is required")
        
        workflow_id = f"credit-management-{customer_id}-{int(time.time())}"
        
        # Start workflow
        workflow_handle = await temporal_client.start_workflow(
            CreditManagementWorkflow.run,
            customer_data,
            id=workflow_id,
            task_queue="cashapp-task-queue",
        )
        
        # Record metrics
        workflow_counter.labels(
            workflow_type='credit_management',
            client_id=customer_data.get('client_id', 'unknown')
        ).inc()
        active_workflows.labels(workflow_type='credit_management').inc()
        
        logger.info(f"Started credit management workflow: {workflow_handle.id}")
        
        return {
            "status": "started",
            "workflow_id": workflow_handle.id,
            "customer_id": customer_id,
            "run_id": workflow_handle.result_run_id
        }
        
    except Exception as e:
        logger.error(f"Failed to start credit management workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/workflows/{workflow_id}/status")
async def get_workflow_status(workflow_id: str):
    """
    Get the status of a running workflow
    """
    try:
        if not temporal_client:
            raise HTTPException(status_code=503, detail="Temporal client not available")
        
        # Get workflow handle
        workflow_handle = temporal_client.get_workflow_handle(workflow_id)
        
        # Check if workflow is complete
        try:
            result = await asyncio.wait_for(workflow_handle.result(), timeout=0.1)
            
            # Workflow completed
            active_workflows.labels(workflow_type=workflow_id.split('-')[0]).dec()
            
            return {
                "status": "completed",
                "workflow_id": workflow_id,
                "result": result,
                "run_id": workflow_handle.result_run_id
            }
            
        except asyncio.TimeoutError:
            # Workflow still running
            return {
                "status": "running",
                "workflow_id": workflow_id,
                "run_id": workflow_handle.result_run_id
            }
            
    except Exception as e:
        logger.error(f"Failed to get workflow status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/workflows/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str):
    """
    Cancel a running workflow
    """
    try:
        if not temporal_client:
            raise HTTPException(status_code=503, detail="Temporal client not available")
        
        # Get workflow handle and cancel
        workflow_handle = temporal_client.get_workflow_handle(workflow_id)
        await workflow_handle.cancel()
        
        # Update metrics
        active_workflows.labels(workflow_type=workflow_id.split('-')[0]).dec()
        
        logger.info(f"Cancelled workflow: {workflow_id}")
        
        return {
            "status": "cancelled",
            "workflow_id": workflow_id
        }
        
    except Exception as e:
        logger.error(f"Failed to cancel workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/workflows/stats")
async def get_workflow_stats():
    """
    Get workflow execution statistics
    """
    try:
        # This would typically query Temporal's visibility store
        # For now, return basic metrics from Prometheus
        return {
            "total_workflows_started": workflow_counter._value.sum(),
            "active_workflows": {
                "cash_application": active_workflows.labels(workflow_type='cash_application')._value.get(),
                "collections": active_workflows.labels(workflow_type='collections')._value.get(),
                "credit_management": active_workflows.labels(workflow_type='credit_management')._value.get()
            },
            "average_duration_seconds": {
                # These would be calculated from the histogram
                "cash_application": 0.0,
                "collections": 0.0,
                "credit_management": 0.0
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get workflow stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Mount Prometheus metrics endpoint
app.mount("/metrics", make_asgi_app())


if __name__ == "__main__":
    import uvicorn
    # Run using the in-memory app object to avoid a second import that
    # would duplicate Prometheus metric registration.
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8005,
        reload=True if os.getenv('ENVIRONMENT') == 'development' else False,
    )
