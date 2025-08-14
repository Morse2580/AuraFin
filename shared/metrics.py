
# shared/metrics.py
"""
Prometheus metrics utilities for CashAppAgent
Standardized metrics collection across all services
"""

from prometheus_client import Counter, Histogram, Gauge, Info
import time
from functools import wraps
from typing import Dict, Any
from .logging import get_correlation_id


# Common metrics for all services
REQUEST_COUNT = Counter(
    'cashapp_requests_total',
    'Total number of requests',
    ['service', 'endpoint', 'method', 'status']
)

REQUEST_DURATION = Histogram(
    'cashapp_request_duration_seconds',
    'Request duration in seconds',
    ['service', 'endpoint', 'method']
)

ACTIVE_CONNECTIONS = Gauge(
    'cashapp_active_connections',
    'Number of active connections',
    ['service', 'connection_type']
)

ERROR_COUNT = Counter(
    'cashapp_errors_total',
    'Total number of errors',
    ['service', 'error_type', 'error_code']
)

# Business metrics
TRANSACTIONS_PROCESSED = Counter(
    'cashapp_transactions_processed_total',
    'Total transactions processed',
    ['service', 'status', 'discrepancy_type']
)

PROCESSING_TIME = Histogram(
    'cashapp_processing_time_seconds',
    'Transaction processing time',
    ['service', 'transaction_type']
)

MATCH_SUCCESS_RATE = Gauge(
    'cashapp_match_success_rate',
    'Percentage of successful matches',
    ['service', 'time_window']
)

SERVICE_INFO = Info(
    'cashapp_service_info',
    'Service information'
)


def track_request_metrics(service_name: str):
    """
    Decorator to track request metrics
    
    Args:
        service_name: Name of the service
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            endpoint = func.__name__
            method = "POST"  # Assuming POST for most API calls
            status = "success"
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                ERROR_COUNT.labels(
                    service=service_name,
                    error_type=type(e).__name__,
                    error_code=getattr(e, 'error_code', 'UNKNOWN')
                ).inc()
                raise
            finally:
                duration = time.time() - start_time
                REQUEST_COUNT.labels(
                    service=service_name,
                    endpoint=endpoint,
                    method=method,
                    status=status
                ).inc()
                REQUEST_DURATION.labels(
                    service=service_name,
                    endpoint=endpoint,
                    method=method
                ).observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            endpoint = func.__name__
            method = "POST"
            status = "success"
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                ERROR_COUNT.labels(
                    service=service_name,
                    error_type=type(e).__name__,
                    error_code=getattr(e, 'error_code', 'UNKNOWN')
                ).inc()
                raise
            finally:
                duration = time.time() - start_time
                REQUEST_COUNT.labels(
                    service=service_name,
                    endpoint=endpoint,
                    method=method,
                    status=status
                ).inc()
                REQUEST_DURATION.labels(
                    service=service_name,
                    endpoint=endpoint,
                    method=method
                ).observe(duration)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def track_business_metrics(transaction_status: str, processing_time: float, 
                          service_name: str, discrepancy_type: str = None):
    """
    Track business-specific metrics
    
    Args:
        transaction_status: Status of transaction processing
        processing_time: Time taken to process transaction
        service_name: Name of the processing service
        discrepancy_type: Type of discrepancy if any
    """
    
    TRANSACTIONS_PROCESSED.labels(
        service=service_name,
        status=transaction_status,
        discrepancy_type=discrepancy_type or "none"
    ).inc()
    
    PROCESSING_TIME.labels(
        service=service_name,
        transaction_type="payment_matching"
    ).observe(processing_time)