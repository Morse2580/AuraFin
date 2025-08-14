"""
Enhanced Prometheus metrics for CashAppAgent
Provides comprehensive monitoring across all services with custom dashboards
"""

from prometheus_client import Counter, Histogram, Gauge, Info, Enum, CollectorRegistry, make_asgi_app
import time
import psutil
import threading
import logging
from typing import Dict, Any, Optional
from contextlib import contextmanager
from functools import wraps
import os

logger = logging.getLogger(__name__)

# Create custom registry for the application
REGISTRY = CollectorRegistry()

# =============================================================================
# CORE BUSINESS METRICS
# =============================================================================

# Transaction Processing Metrics
transaction_counter = Counter(
    'cashapp_transactions_total',
    'Total number of transactions processed',
    ['service', 'status', 'client_id', 'transaction_type'],
    registry=REGISTRY
)

transaction_duration = Histogram(
    'cashapp_transaction_duration_seconds',
    'Time spent processing transactions',
    ['service', 'transaction_type', 'complexity'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
    registry=REGISTRY
)

transaction_amount = Histogram(
    'cashapp_transaction_amount_usd',
    'Transaction amounts in USD',
    ['client_id', 'status'],
    buckets=[10, 50, 100, 500, 1000, 5000, 10000, 50000, 100000],
    registry=REGISTRY
)

# Document Processing Metrics
document_processing_counter = Counter(
    'cashapp_documents_processed_total',
    'Total number of documents processed',
    ['service', 'engine', 'document_type', 'status'],
    registry=REGISTRY
)

document_processing_duration = Histogram(
    'cashapp_document_processing_seconds',
    'Document processing time',
    ['engine', 'complexity_level', 'preprocessing'],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 60.0],
    registry=REGISTRY
)

ocr_confidence_score = Histogram(
    'cashapp_ocr_confidence_score',
    'OCR confidence scores',
    ['engine', 'document_type'],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    registry=REGISTRY
)

ocr_cost_per_document = Histogram(
    'cashapp_ocr_cost_usd',
    'OCR processing cost per document',
    ['engine'],
    buckets=[0.0, 0.001, 0.005, 0.01, 0.05, 0.1],
    registry=REGISTRY
)

# Invoice Matching Metrics
invoice_matching_counter = Counter(
    'cashapp_invoice_matches_total',
    'Total invoice matching attempts',
    ['status', 'match_type', 'confidence_level'],
    registry=REGISTRY
)

invoice_matching_accuracy = Gauge(
    'cashapp_invoice_matching_accuracy_ratio',
    'Invoice matching accuracy over time',
    ['client_id', 'time_window'],
    registry=REGISTRY
)

matching_confidence_score = Histogram(
    'cashapp_matching_confidence_score',
    'Invoice matching confidence scores',
    ['algorithm', 'client_id'],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    registry=REGISTRY
)

# ERP Integration Metrics
erp_operations_counter = Counter(
    'cashapp_erp_operations_total',
    'Total ERP operations performed',
    ['erp_system', 'operation_type', 'status'],
    registry=REGISTRY
)

erp_response_duration = Histogram(
    'cashapp_erp_response_seconds',
    'ERP system response times',
    ['erp_system', 'operation_type'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    registry=REGISTRY
)

erp_data_sync_lag = Gauge(
    'cashapp_erp_sync_lag_seconds',
    'Data synchronization lag with ERP systems',
    ['erp_system'],
    registry=REGISTRY
)

# Communication Metrics
communication_counter = Counter(
    'cashapp_communications_sent_total',
    'Total communications sent',
    ['channel', 'type', 'status'],
    registry=REGISTRY
)

notification_delivery_time = Histogram(
    'cashapp_notification_delivery_seconds',
    'Time to deliver notifications',
    ['channel', 'priority'],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0],
    registry=REGISTRY
)

# =============================================================================
# TEMPORAL WORKFLOW METRICS
# =============================================================================

workflow_counter = Counter(
    'cashapp_workflows_total',
    'Total Temporal workflows started',
    ['workflow_type', 'status'],
    registry=REGISTRY
)

workflow_duration = Histogram(
    'cashapp_workflow_duration_seconds',
    'Workflow execution duration',
    ['workflow_type', 'status'],
    buckets=[1, 5, 10, 30, 60, 300, 600, 1800, 3600],
    registry=REGISTRY
)

active_workflows = Gauge(
    'cashapp_active_workflows',
    'Number of currently active workflows',
    ['workflow_type'],
    registry=REGISTRY
)

workflow_retry_counter = Counter(
    'cashapp_workflow_retries_total',
    'Total workflow activity retries',
    ['workflow_type', 'activity_type', 'failure_reason'],
    registry=REGISTRY
)

# =============================================================================
# QUEUE METRICS
# =============================================================================

queue_messages_produced = Counter(
    'cashapp_queue_messages_produced_total',
    'Total messages produced to queues',
    ['queue_name', 'message_type'],
    registry=REGISTRY
)

queue_messages_consumed = Counter(
    'cashapp_queue_messages_consumed_total',
    'Total messages consumed from queues',
    ['queue_name', 'status'],
    registry=REGISTRY
)

queue_depth = Gauge(
    'cashapp_queue_depth',
    'Number of messages in queue',
    ['queue_name'],
    registry=REGISTRY
)

queue_processing_duration = Histogram(
    'cashapp_queue_message_processing_seconds',
    'Time to process queue messages',
    ['queue_name', 'message_type'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
    registry=REGISTRY
)

dead_letter_queue_messages = Gauge(
    'cashapp_dlq_messages',
    'Number of messages in dead letter queues',
    ['original_queue'],
    registry=REGISTRY
)

# =============================================================================
# SYSTEM AND INFRASTRUCTURE METRICS
# =============================================================================

# HTTP Request Metrics
http_requests_total = Counter(
    'cashapp_http_requests_total',
    'Total HTTP requests',
    ['service', 'method', 'endpoint', 'status_code'],
    registry=REGISTRY
)

http_request_duration = Histogram(
    'cashapp_http_request_duration_seconds',
    'HTTP request duration',
    ['service', 'method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
    registry=REGISTRY
)

# Database Metrics
database_connections = Gauge(
    'cashapp_database_connections',
    'Number of database connections',
    ['database', 'status'],
    registry=REGISTRY
)

database_query_duration = Histogram(
    'cashapp_database_query_duration_seconds',
    'Database query execution time',
    ['database', 'query_type'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    registry=REGISTRY
)

# Cache Metrics
cache_operations = Counter(
    'cashapp_cache_operations_total',
    'Total cache operations',
    ['cache_type', 'operation', 'status'],
    registry=REGISTRY
)

cache_hit_ratio = Gauge(
    'cashapp_cache_hit_ratio',
    'Cache hit ratio',
    ['cache_type'],
    registry=REGISTRY
)

# System Resource Metrics
system_cpu_usage = Gauge(
    'cashapp_system_cpu_usage_percent',
    'System CPU usage percentage',
    ['service'],
    registry=REGISTRY
)

system_memory_usage = Gauge(
    'cashapp_system_memory_usage_bytes',
    'System memory usage in bytes',
    ['service', 'type'],
    registry=REGISTRY
)

system_disk_usage = Gauge(
    'cashapp_system_disk_usage_bytes',
    'System disk usage in bytes',
    ['service', 'mount_point'],
    registry=REGISTRY
)

# =============================================================================
# BUSINESS KPI METRICS
# =============================================================================

# Financial Metrics
daily_transaction_volume = Gauge(
    'cashapp_daily_transaction_volume_usd',
    'Daily transaction volume in USD',
    ['date'],
    registry=REGISTRY
)

processing_cost_savings = Counter(
    'cashapp_cost_savings_total_usd',
    'Total cost savings from hybrid processing',
    ['optimization_type'],
    registry=REGISTRY
)

# Performance KPIs
straight_through_processing_rate = Gauge(
    'cashapp_stp_rate_percent',
    'Straight-through processing rate percentage',
    ['client_id', 'time_period'],
    registry=REGISTRY
)

manual_review_rate = Gauge(
    'cashapp_manual_review_rate_percent',
    'Manual review rate percentage',
    ['reason', 'time_period'],
    registry=REGISTRY
)

customer_satisfaction_score = Gauge(
    'cashapp_customer_satisfaction_score',
    'Customer satisfaction score (1-10)',
    ['client_id'],
    registry=REGISTRY
)

# =============================================================================
# APPLICATION INFO METRICS
# =============================================================================

application_info = Info(
    'cashapp_application_info',
    'Application build and deployment information',
    registry=REGISTRY
)

service_health_status = Enum(
    'cashapp_service_health_status',
    'Service health status',
    ['service'],
    states=['healthy', 'degraded', 'unhealthy'],
    registry=REGISTRY
)

# =============================================================================
# METRIC COLLECTION UTILITIES
# =============================================================================

class MetricsCollector:
    """Centralized metrics collection and management"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.start_time = time.time()
        self._system_metrics_thread = None
        self._stop_system_metrics = False
        
        # Set application info
        application_info.info({
            'service': service_name,
            'version': os.getenv('APP_VERSION', 'dev'),
            'build_date': os.getenv('BUILD_DATE', 'unknown'),
            'git_commit': os.getenv('GIT_COMMIT', 'unknown')
        })
        
        # Start system metrics collection
        self.start_system_metrics_collection()
    
    def start_system_metrics_collection(self):
        """Start background thread for system metrics collection"""
        def collect_system_metrics():
            while not self._stop_system_metrics:
                try:
                    # CPU usage
                    cpu_percent = psutil.cpu_percent(interval=1)
                    system_cpu_usage.labels(service=self.service_name).set(cpu_percent)
                    
                    # Memory usage
                    memory = psutil.virtual_memory()
                    system_memory_usage.labels(
                        service=self.service_name, 
                        type='used'
                    ).set(memory.used)
                    system_memory_usage.labels(
                        service=self.service_name, 
                        type='available'
                    ).set(memory.available)
                    
                    # Disk usage
                    for disk_partition in psutil.disk_partitions():
                        try:
                            disk_usage = psutil.disk_usage(disk_partition.mountpoint)
                            system_disk_usage.labels(
                                service=self.service_name,
                                mount_point=disk_partition.mountpoint
                            ).set(disk_usage.used)
                        except PermissionError:
                            continue
                    
                    time.sleep(30)  # Collect every 30 seconds
                    
                except Exception as e:
                    logger.error(f"Error collecting system metrics: {e}")
                    time.sleep(30)
        
        self._system_metrics_thread = threading.Thread(
            target=collect_system_metrics, 
            daemon=True
        )
        self._system_metrics_thread.start()
        logger.info("System metrics collection started")
    
    def stop_system_metrics_collection(self):
        """Stop system metrics collection"""
        self._stop_system_metrics = True
        if self._system_metrics_thread:
            self._system_metrics_thread.join(timeout=5)
        logger.info("System metrics collection stopped")
    
    @contextmanager
    def time_operation(self, metric: Histogram, **labels):
        """Context manager for timing operations"""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            metric.labels(**labels).observe(duration)
    
    def record_transaction(self, 
                         transaction_type: str,
                         status: str,
                         client_id: str,
                         amount: float,
                         duration: float):
        """Record transaction metrics"""
        transaction_counter.labels(
            service=self.service_name,
            status=status,
            client_id=client_id,
            transaction_type=transaction_type
        ).inc()
        
        transaction_duration.labels(
            service=self.service_name,
            transaction_type=transaction_type,
            complexity='medium'  # Could be determined dynamically
        ).observe(duration)
        
        transaction_amount.labels(
            client_id=client_id,
            status=status
        ).observe(amount)
    
    def record_document_processing(self,
                                 engine: str,
                                 document_type: str,
                                 status: str,
                                 duration: float,
                                 confidence: float = None,
                                 cost: float = None):
        """Record document processing metrics"""
        document_processing_counter.labels(
            service=self.service_name,
            engine=engine,
            document_type=document_type,
            status=status
        ).inc()
        
        document_processing_duration.labels(
            engine=engine,
            complexity_level='medium',
            preprocessing='true'
        ).observe(duration)
        
        if confidence is not None:
            ocr_confidence_score.labels(
                engine=engine,
                document_type=document_type
            ).observe(confidence)
        
        if cost is not None:
            ocr_cost_per_document.labels(engine=engine).observe(cost)
    
    def record_workflow_execution(self,
                                workflow_type: str,
                                status: str,
                                duration: float):
        """Record workflow execution metrics"""
        workflow_counter.labels(
            workflow_type=workflow_type,
            status=status
        ).inc()
        
        workflow_duration.labels(
            workflow_type=workflow_type,
            status=status
        ).observe(duration)
    
    def record_http_request(self,
                          method: str,
                          endpoint: str,
                          status_code: int,
                          duration: float):
        """Record HTTP request metrics"""
        http_requests_total.labels(
            service=self.service_name,
            method=method,
            endpoint=endpoint,
            status_code=status_code
        ).inc()
        
        http_request_duration.labels(
            service=self.service_name,
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    def record_queue_operation(self,
                             queue_name: str,
                             operation: str,
                             message_type: str = None,
                             duration: float = None):
        """Record queue operation metrics"""
        if operation == 'produce':
            queue_messages_produced.labels(
                queue_name=queue_name,
                message_type=message_type or 'unknown'
            ).inc()
        elif operation == 'consume':
            queue_messages_consumed.labels(
                queue_name=queue_name,
                status='success'
            ).inc()
        
        if duration is not None:
            queue_processing_duration.labels(
                queue_name=queue_name,
                message_type=message_type or 'unknown'
            ).observe(duration)
    
    def set_service_health(self, status: str):
        """Set service health status"""
        service_health_status.labels(service=self.service_name).state(status)
    
    def get_metrics_app(self):
        """Get ASGI app for metrics endpoint"""
        return make_asgi_app(registry=REGISTRY)

# Global metrics collector
_metrics_collector: Optional[MetricsCollector] = None

def initialize_metrics(service_name: str) -> MetricsCollector:
    """Initialize metrics collector for service"""
    global _metrics_collector
    if not _metrics_collector:
        _metrics_collector = MetricsCollector(service_name)
        logger.info(f"Metrics initialized for service: {service_name}")
    return _metrics_collector

def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector"""
    if not _metrics_collector:
        raise RuntimeError("Metrics collector not initialized")
    return _metrics_collector

def metrics_middleware(service_name: str):
    """FastAPI middleware for automatic request metrics"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status_code = 200
            
            try:
                response = await func(*args, **kwargs)
                if hasattr(response, 'status_code'):
                    status_code = response.status_code
                return response
            except Exception as e:
                status_code = 500
                raise
            finally:
                duration = time.time() - start_time
                collector = get_metrics_collector()
                
                # Extract request info (this would be more sophisticated in practice)
                method = kwargs.get('method', 'GET')
                endpoint = kwargs.get('endpoint', 'unknown')
                
                collector.record_http_request(method, endpoint, status_code, duration)
        
        return wrapper
    return decorator

# =============================================================================
# METRIC DECORATORS
# =============================================================================

def track_transaction_processing(transaction_type: str = 'general'):
    """Decorator to track transaction processing"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = 'success'
            client_id = kwargs.get('client_id', 'unknown')
            amount = kwargs.get('amount', 0.0)
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                duration = time.time() - start_time
                collector = get_metrics_collector()
                collector.record_transaction(transaction_type, status, client_id, amount, duration)
        
        return wrapper
    return decorator

def track_document_processing(engine: str, document_type: str = 'invoice'):
    """Decorator to track document processing"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = 'success'
            
            try:
                result = await func(*args, **kwargs)
                
                # Extract confidence and cost from result if available
                confidence = getattr(result, 'confidence', None)
                cost = getattr(result, 'cost_estimate', None)
                
                collector = get_metrics_collector()
                duration = time.time() - start_time
                collector.record_document_processing(
                    engine, document_type, status, duration, confidence, cost
                )
                
                return result
            except Exception as e:
                status = 'error'
                collector = get_metrics_collector()
                duration = time.time() - start_time
                collector.record_document_processing(engine, document_type, status, duration)
                raise
        
        return wrapper
    return decorator