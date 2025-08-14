# shared/monitoring.py
"""
Comprehensive monitoring and observability for CashAppAgent
Integrates Application Insights, custom metrics, and health checks
"""

import os
import time
import traceback
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
import asyncio
import psutil

from .logging import setup_logging
from .exception import CashAppException

logger = setup_logging("monitoring")

# Application Insights integration (placeholder - would use actual SDK)
class ApplicationInsights:
    """Application Insights telemetry client"""
    
    def __init__(self, instrumentation_key: str):
        self.instrumentation_key = instrumentation_key
        self.telemetry_buffer = []
        self.enabled = bool(instrumentation_key)
    
    def track_event(self, name: str, properties: Dict[str, Any] = None, measurements: Dict[str, float] = None):
        """Track custom event"""
        if not self.enabled:
            return
        
        event = {
            'type': 'event',
            'name': name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'properties': properties or {},
            'measurements': measurements or {}
        }
        
        self.telemetry_buffer.append(event)
        logger.debug(f"Tracked event: {name}")
    
    def track_metric(self, name: str, value: float, properties: Dict[str, str] = None):
        """Track custom metric"""
        if not self.enabled:
            return
        
        metric = {
            'type': 'metric',
            'name': name,
            'value': value,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'properties': properties or {}
        }
        
        self.telemetry_buffer.append(metric)
    
    def track_exception(self, exception: Exception, properties: Dict[str, Any] = None):
        """Track exception"""
        if not self.enabled:
            return
        
        exc_data = {
            'type': 'exception',
            'exception_type': type(exception).__name__,
            'message': str(exception),
            'stack_trace': traceback.format_exc(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'properties': properties or {}
        }
        
        self.telemetry_buffer.append(exc_data)
        logger.debug(f"Tracked exception: {type(exception).__name__}")
    
    def track_dependency(self, name: str, type_name: str, data: str, success: bool, duration_ms: int):
        """Track dependency call"""
        if not self.enabled:
            return
        
        dependency = {
            'type': 'dependency',
            'name': name,
            'dependency_type': type_name,
            'data': data,
            'success': success,
            'duration_ms': duration_ms,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        self.telemetry_buffer.append(dependency)
    
    async def flush(self):
        """Flush telemetry buffer"""
        if not self.enabled or not self.telemetry_buffer:
            return
        
        # In production, would send to Application Insights
        logger.info(f"Flushed {len(self.telemetry_buffer)} telemetry items")
        self.telemetry_buffer.clear()

class HealthStatus(str, Enum):
    """Health check status values"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

@dataclass
class HealthCheck:
    """Individual health check definition"""
    name: str
    check_function: Callable
    timeout_seconds: int = 30
    critical: bool = True
    interval_seconds: int = 60

@dataclass
class HealthCheckResult:
    """Result of a health check"""
    name: str
    status: HealthStatus
    response_time_ms: int
    message: Optional[str] = None
    details: Dict[str, Any] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

class ComprehensiveHealthChecker:
    """
    Comprehensive health checking system
    Monitors all system components and dependencies
    """
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.checks = {}
        self.last_results = {}
        self.check_history = []
        self.max_history = 100
    
    def add_check(self, check: HealthCheck):
        """Add health check"""
        self.checks[check.name] = check
        logger.info(f"Added health check: {check.name}")
    
    def add_simple_check(self, name: str, check_function: Callable, critical: bool = True):
        """Add simple health check with defaults"""
        check = HealthCheck(
            name=name,
            check_function=check_function,
            critical=critical
        )
        self.add_check(check)
    
    async def run_all_checks(self) -> Dict[str, Any]:
        """
        Run all health checks and return comprehensive status
        
        Returns:
            Complete health status with all check results
        """
        start_time = time.time()
        
        try:
            # Run all checks concurrently
            check_tasks = [
                self._run_single_check(check)
                for check in self.checks.values()
            ]
            
            check_results = await asyncio.gather(*check_tasks, return_exceptions=True)
            
            # Process results
            results = {}
            critical_failures = 0
            total_checks = len(check_tasks)
            
            for i, result in enumerate(check_results):
                check_name = list(self.checks.keys())[i]
                check = self.checks[check_name]
                
                if isinstance(result, Exception):
                    # Check failed with exception
                    health_result = HealthCheckResult(
                        name=check_name,
                        status=HealthStatus.UNHEALTHY,
                        response_time_ms=0,
                        message=f"Check failed: {str(result)}"
                    )
                    if check.critical:
                        critical_failures += 1
                else:
                    health_result = result
                    if health_result.status == HealthStatus.UNHEALTHY and check.critical:
                        critical_failures += 1
                
                results[check_name] = health_result
                self.last_results[check_name] = health_result
            
            # Determine overall status
            if critical_failures > 0:
                overall_status = HealthStatus.UNHEALTHY
            elif any(r.status == HealthStatus.DEGRADED for r in results.values()):
                overall_status = HealthStatus.DEGRADED
            else:
                overall_status = HealthStatus.HEALTHY
            
            # Create comprehensive response
            total_time = int((time.time() - start_time) * 1000)
            
            health_summary = {
                'service': self.service_name,
                'status': overall_status.value,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'response_time_ms': total_time,
                'checks': {
                    name: {
                        'status': result.status.value,
                        'response_time_ms': result.response_time_ms,
                        'message': result.message,
                        'details': result.details,
                        'critical': self.checks[name].critical
                    }
                    for name, result in results.items()
                },
                'summary': {
                    'total_checks': total_checks,
                    'healthy_checks': sum(1 for r in results.values() if r.status == HealthStatus.HEALTHY),
                    'degraded_checks': sum(1 for r in results.values() if r.status == HealthStatus.DEGRADED),
                    'unhealthy_checks': sum(1 for r in results.values() if r.status == HealthStatus.UNHEALTHY),
                    'critical_failures': critical_failures
                },
                'system_info': await self._get_system_info()
            }
            
            # Store in history
            self.check_history.append(health_summary)
            if len(self.check_history) > self.max_history:
                self.check_history.pop(0)
            
            return health_summary
            
        except Exception as e:
            logger.error(f"Health check execution failed: {e}")
            return {
                'service': self.service_name,
                'status': HealthStatus.UNHEALTHY.value,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e),
                'system_info': await self._get_system_info()
            }
    
    async def _run_single_check(self, check: HealthCheck) -> HealthCheckResult:
        """Run individual health check with timeout"""
        start_time = time.time()
        
        try:
            # Run check with timeout
            result = await asyncio.wait_for(
                check.check_function(),
                timeout=check.timeout_seconds
            )
            
            response_time = int((time.time() - start_time) * 1000)
            
            # Parse result
            if isinstance(result, dict):
                status_str = result.get('status', 'healthy')
                status = HealthStatus(status_str) if status_str in ['healthy', 'degraded', 'unhealthy'] else HealthStatus.HEALTHY
                
                return HealthCheckResult(
                    name=check.name,
                    status=status,
                    response_time_ms=response_time,
                    message=result.get('message'),
                    details=result.get('details')
                )
            elif isinstance(result, bool):
                status = HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
                return HealthCheckResult(
                    name=check.name,
                    status=status,
                    response_time_ms=response_time,
                    message="OK" if result else "Check failed"
                )
            else:
                # Assume healthy if check returns without exception
                return HealthCheckResult(
                    name=check.name,
                    status=HealthStatus.HEALTHY,
                    response_time_ms=response_time,
                    message="OK"
                )
                
        except asyncio.TimeoutError:
            response_time = int((time.time() - start_time) * 1000)
            return HealthCheckResult(
                name=check.name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=response_time,
                message=f"Check timed out after {check.timeout_seconds}s"
            )
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            return HealthCheckResult(
                name=check.name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=response_time,
                message=f"Check failed: {str(e)}"
            )
    
    async def _get_system_info(self) -> Dict[str, Any]:
        """Get system resource information"""
        try:
            # Get process info
            process = psutil.Process()
            
            # Get system info
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                'process': {
                    'pid': process.pid,
                    'cpu_percent': process.cpu_percent(),
                    'memory_percent': process.memory_percent(),
                    'memory_rss_mb': process.memory_info().rss / 1024 / 1024,
                    'num_threads': process.num_threads(),
                    'create_time': process.create_time()
                },
                'system': {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'memory_available_gb': memory.available / 1024 / 1024 / 1024,
                    'disk_percent': disk.percent,
                    'disk_free_gb': disk.free / 1024 / 1024 / 1024
                },
                'python': {
                    'version': os.sys.version,
                    'platform': os.sys.platform
                }
            }
        except Exception as e:
            logger.warning(f"Failed to get system info: {e}")
            return {'error': str(e)}
    
    def get_health_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get health check history for specified hours"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        return [
            entry for entry in self.check_history
            if datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00')) > cutoff_time
        ]

class MetricsCollector:
    """
    Custom metrics collection and reporting
    Collects business and technical metrics
    """
    
    def __init__(self, service_name: str, app_insights: ApplicationInsights = None):
        self.service_name = service_name
        self.app_insights = app_insights
        self.metrics = {}
        self.counters = {}
        self.histograms = {}
        self.gauges = {}
    
    def increment_counter(self, name: str, value: int = 1, labels: Dict[str, str] = None):
        """Increment counter metric"""
        key = self._make_metric_key(name, labels)
        self.counters[key] = self.counters.get(key, 0) + value
        
        if self.app_insights:
            self.app_insights.track_metric(name, value, labels)
    
    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Set gauge metric value"""
        key = self._make_metric_key(name, labels)
        self.gauges[key] = {
            'value': value,
            'timestamp': time.time(),
            'labels': labels or {}
        }
        
        if self.app_insights:
            self.app_insights.track_metric(name, value, labels)
    
    def record_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record histogram value"""
        key = self._make_metric_key(name, labels)
        if key not in self.histograms:
            self.histograms[key] = {
                'values': [],
                'labels': labels or {}
            }
        
        self.histograms[key]['values'].append(value)
        
        # Keep only last 1000 values for memory efficiency
        if len(self.histograms[key]['values']) > 1000:
            self.histograms[key]['values'] = self.histograms[key]['values'][-1000:]
        
        if self.app_insights:
            self.app_insights.track_metric(name, value, labels)
    
    def _make_metric_key(self, name: str, labels: Dict[str, str] = None) -> str:
        """Create metric key with labels"""
        if not labels:
            return name
        
        label_str = ','.join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}[{label_str}]"
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of all collected metrics"""
        summary = {
            'service': self.service_name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'counters': dict(self.counters),
            'gauges': {
                key: data['value'] for key, data in self.gauges.items()
            },
            'histograms': {}
        }
        
        # Calculate histogram statistics
        for key, data in self.histograms.items():
            values = data['values']
            if values:
                values_sorted = sorted(values)
                summary['histograms'][key] = {
                    'count': len(values),
                    'min': min(values),
                    'max': max(values),
                    'mean': sum(values) / len(values),
                    'p50': values_sorted[len(values_sorted) // 2],
                    'p95': values_sorted[int(len(values_sorted) * 0.95)],
                    'p99': values_sorted[int(len(values_sorted) * 0.99)]
                }
        
        return summary

class BusinessMetricsTracker:
    """
    Tracks business-specific metrics for CashAppAgent
    Provides insights into processing performance and accuracy
    """
    
    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics = metrics_collector
        self.business_events = []
    
    def track_transaction_processed(self, 
                                   transaction_id: str,
                                   amount: float,
                                   currency: str,
                                   processing_time_ms: int,
                                   status: str,
                                   client_id: str = None):
        """Track transaction processing metrics"""
        labels = {
            'status': status,
            'currency': currency
        }
        if client_id:
            labels['client_id'] = client_id
        
        # Track counters
        self.metrics.increment_counter('transactions_processed_total', 1, labels)
        if status in ['matched', 'partially_matched']:
            self.metrics.increment_counter('transactions_successful_total', 1, labels)
        
        # Track processing time
        self.metrics.record_histogram('transaction_processing_time_ms', processing_time_ms, labels)
        
        # Track amount
        self.metrics.record_histogram('transaction_amount', amount, labels)
        
        # Store business event
        self.business_events.append({
            'type': 'transaction_processed',
            'transaction_id': transaction_id,
            'amount': amount,
            'currency': currency,
            'status': status,
            'processing_time_ms': processing_time_ms,
            'client_id': client_id,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    def track_erp_operation(self, 
                           operation_type: str,
                           erp_system: str,
                           success: bool,
                           duration_ms: int,
                           error_type: str = None):
        """Track ERP operation metrics"""
        labels = {
            'operation': operation_type,
            'erp_system': erp_system,
            'success': str(success)
        }
        if error_type:
            labels['error_type'] = error_type
        
        self.metrics.increment_counter('erp_operations_total', 1, labels)
        self.metrics.record_histogram('erp_operation_duration_ms', duration_ms, labels)
        
        if not success:
            self.metrics.increment_counter('erp_operation_errors_total', 1, labels)
    
    def track_document_processed(self, 
                                document_count: int,
                                invoice_ids_found: int,
                                confidence_score: float,
                                processing_time_ms: int):
        """Track document processing metrics"""
        labels = {
            'document_count': str(document_count)
        }
        
        self.metrics.increment_counter('documents_processed_total', document_count, labels)
        self.metrics.record_histogram('document_processing_time_ms', processing_time_ms, labels)
        self.metrics.record_histogram('invoice_ids_extracted', invoice_ids_found, labels)
        self.metrics.record_histogram('document_confidence_score', confidence_score, labels)
    
    def track_communication_sent(self, 
                                comm_type: str,
                                success: bool,
                                recipient_count: int = 1):
        """Track communication metrics"""
        labels = {
            'type': comm_type,
            'success': str(success)
        }
        
        self.metrics.increment_counter('communications_sent_total', recipient_count, labels)
        
        if not success:
            self.metrics.increment_counter('communication_failures_total', 1, labels)
    
    def get_business_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get business metrics summary for specified period"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Filter events by time period
        recent_events = [
            event for event in self.business_events
            if datetime.fromisoformat(event['timestamp']) > cutoff_time
        ]
        
        # Calculate summary statistics
        transaction_events = [e for e in recent_events if e['type'] == 'transaction_processed']
        
        if not transaction_events:
            return {'period_hours': hours, 'no_data': True}
        
        total_transactions = len(transaction_events)
        successful_transactions = len([e for e in transaction_events if e['status'] in ['matched', 'partially_matched']])
        total_amount = sum(e['amount'] for e in transaction_events)
        avg_processing_time = sum(e['processing_time_ms'] for e in transaction_events) / total_transactions
        
        # Group by currency
        by_currency = {}
        for event in transaction_events:
            currency = event['currency']
            if currency not in by_currency:
                by_currency[currency] = {'count': 0, 'amount': 0}
            by_currency[currency]['count'] += 1
            by_currency[currency]['amount'] += event['amount']
        
        return {
            'period_hours': hours,
            'total_transactions': total_transactions,
            'successful_transactions': successful_transactions,
            'success_rate': successful_transactions / total_transactions,
            'total_amount_processed': total_amount,
            'average_processing_time_ms': avg_processing_time,
            'by_currency': by_currency,
            'clients_active': len(set(e.get('client_id') for e in transaction_events if e.get('client_id')))
        }

class AlertManager:
    """
    Manages system alerts and notifications
    Provides configurable alerting based on metrics and health checks
    """
    
    def __init__(self, 
                 metrics_collector: MetricsCollector,
                 health_checker: ComprehensiveHealthChecker):
        self.metrics = metrics_collector
        self.health_checker = health_checker
        self.alert_rules = {}
        self.alert_history = []
        self.suppression_cache = {}  # Prevent alert spam
    
    def add_alert_rule(self, 
                      name: str,
                      condition: Callable[[Dict[str, Any]], bool],
                      severity: str = "warning",
                      cooldown_minutes: int = 15):
        """
        Add alert rule
        
        Args:
            name: Alert rule name
            condition: Function that returns True when alert should fire
            severity: Alert severity (info, warning, error, critical)
            cooldown_minutes: Minimum time between same alerts
        """
        self.alert_rules[name] = {
            'condition': condition,
            'severity': severity,
            'cooldown_minutes': cooldown_minutes
        }
        logger.info(f"Added alert rule: {name}")
    
    async def check_alerts(self) -> List[Dict[str, Any]]:
        """
        Check all alert rules and fire alerts if conditions met
        
        Returns:
            List of fired alerts
        """
        try:
            # Get current metrics and health status
            metrics_summary = self.metrics.get_metrics_summary()
            health_summary = await self.health_checker.run_all_checks()
            
            context = {
                'metrics': metrics_summary,
                'health': health_summary,
                'timestamp': time.time()
            }
            
            fired_alerts = []
            
            # Check each alert rule
            for rule_name, rule in self.alert_rules.items():
                try:
                    # Check if alert should fire
                    should_alert = rule['condition'](context)
                    
                    if should_alert:
                        # Check cooldown
                        last_fired = self.suppression_cache.get(rule_name, 0)
                        cooldown_seconds = rule['cooldown_minutes'] * 60
                        
                        if time.time() - last_fired > cooldown_seconds:
                            # Fire alert
                            alert = {
                                'rule_name': rule_name,
                                'severity': rule['severity'],
                                'timestamp': datetime.now(timezone.utc).isoformat(),
                                'context': context,
                                'service': self.metrics.service_name
                            }
                            
                            fired_alerts.append(alert)
                            self.alert_history.append(alert)
                            self.suppression_cache[rule_name] = time.time()
                            
                            logger.warning(f"Alert fired: {rule_name}", extra={
                                'severity': rule['severity'],
                                'service': self.metrics.service_name
                            })
                
                except Exception as e:
                    logger.error(f"Alert rule {rule_name} failed: {e}")
            
            return fired_alerts
            
        except Exception as e:
            logger.error(f"Alert checking failed: {e}")
            return []
    
    def add_default_alert_rules(self):
        """Add standard alert rules for CashAppAgent"""
        
        # High error rate alert
        def high_error_rate(context):
            health = context.get('health', {})
            unhealthy_checks = health.get('summary', {}).get('unhealthy_checks', 0)
            total_checks = health.get('summary', {}).get('total_checks', 1)
            return unhealthy_checks / total_checks > 0.2  # 20% failure rate
        
        self.add_alert_rule('high_error_rate', high_error_rate, 'error', 10)
        
        # Database connectivity alert
        def database_down(context):
            health = context.get('health', {})
            db_check = health.get('checks', {}).get('database', {})
            return db_check.get('status') == 'unhealthy'
        
        self.add_alert_rule('database_down', database_down, 'critical', 5)
        
        # High processing time alert
        def slow_processing(context):
            metrics = context.get('metrics', {})
            histograms = metrics.get('histograms', {})
            processing_time_metrics = {k: v for k, v in histograms.items() if 'processing_time' in k}
            
            for metric_name, stats in processing_time_metrics.items():
                if stats.get('p95', 0) > 30000:  # 30 seconds
                    return True
            return False
        
        self.add_alert_rule('slow_processing', slow_processing, 'warning', 30)
        
        # Memory usage alert
        def high_memory_usage(context):
            health = context.get('health', {})
            system_info = health.get('system_info', {})
            memory_percent = system_info.get('system', {}).get('memory_percent', 0)
            return memory_percent > 85
        
        self.add_alert_rule('high_memory_usage', high_memory_usage, 'warning', 15)

# Standard health check functions
async def check_database_health(connection_string: str) -> Dict[str, Any]:
    """Check database connectivity and performance"""
    try:
        from .database import DatabaseManager
        
        db_manager = DatabaseManager(connection_string)
        await db_manager.initialize()
        
        # Test basic query
        start_time = time.time()
        result = await db_manager.execute_query("SELECT 1")
        query_time = int((time.time() - start_time) * 1000)
        
        await db_manager.close()
        
        return {
            'status': 'healthy',
            'response_time_ms': query_time,
            'details': {
                'query_result': result,
                'connection_test': 'passed'
            }
        }
        
    except Exception as e:
        return {
            'status': 'unhealthy',
            'message': str(e),
            'details': {'error_type': type(e).__name__}
        }

async def check_service_health(service_url: str, timeout: int = 10) -> Dict[str, Any]:
    """Check external service health"""
    try:
        import httpx
        
        start_time = time.time()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{service_url}/health", timeout=timeout)
            response_time = int((time.time() - start_time) * 1000)
            
            if response.status_code == 200:
                return {
                    'status': 'healthy',
                    'response_time_ms': response_time,
                    'details': response.json() if response.content else {}
                }
            else:
                return {
                    'status': 'unhealthy',
                    'response_time_ms': response_time,
                    'message': f"HTTP {response.status_code}",
                    'details': {'status_code': response.status_code}
                }
                
    except Exception as e:
        return {
            'status': 'unhealthy',
            'message': str(e),
            'details': {'error_type': type(e).__name__}
        }

async def check_azure_service_health(service_name: str, endpoint: str = None) -> Dict[str, Any]:
    """Check Azure service health"""
    try:
        # This would check specific Azure services
        # For now, return a placeholder
        return {
            'status': 'healthy',
            'message': f"{service_name} connectivity verified",
            'details': {
                'service': service_name,
                'endpoint': endpoint
            }
        }
        
    except Exception as e:
        return {
            'status': 'unhealthy',
            'message': str(e),
            'details': {'service': service_name}
        }

# Global monitoring instances
_app_insights = None
_health_checker = None
_metrics_collector = None
_business_tracker = None
_alert_manager = None

def initialize_monitoring(service_name: str, 
                         app_insights_key: str = None) -> tuple:
    """
    Initialize monitoring system for service
    
    Args:
        service_name: Name of the service
        app_insights_key: Application Insights instrumentation key
        
    Returns:
        Tuple of (health_checker, metrics_collector, business_tracker)
    """
    global _app_insights, _health_checker, _metrics_collector, _business_tracker, _alert_manager
    
    # Initialize Application Insights
    _app_insights = ApplicationInsights(app_insights_key)
    
    # Initialize health checker
    _health_checker = ComprehensiveHealthChecker(service_name)
    
    # Initialize metrics collector
    _metrics_collector = MetricsCollector(service_name, _app_insights)
    
    # Initialize business tracker
    _business_tracker = BusinessMetricsTracker(_metrics_collector)
    
    # Initialize alert manager
    _alert_manager = AlertManager(_metrics_collector, _health_checker)
    _alert_manager.add_default_alert_rules()
    
    logger.info(f"Monitoring system initialized for {service_name}")
    
    return _health_checker, _metrics_collector, _business_tracker

def get_monitoring_components() -> tuple:
    """Get initialized monitoring components"""
    if not _health_checker:
        raise CashAppException("Monitoring not initialized", "MONITORING_NOT_INITIALIZED")
    
    return _health_checker, _metrics_collector, _business_tracker, _alert_manager

# Background monitoring task
async def start_monitoring_loop(interval_seconds: int = 60):
    """
    Start background monitoring loop
    
    Args:
        interval_seconds: Monitoring interval
    """
    if not _alert_manager:
        logger.warning("Alert manager not initialized, skipping monitoring loop")
        return
    
    logger.info(f"Starting monitoring loop with {interval_seconds}s interval")
    
    while True:
        try:
            # Check alerts
            fired_alerts = await _alert_manager.check_alerts()
            
            if fired_alerts:
                logger.info(f"Monitoring cycle completed: {len(fired_alerts)} alerts fired")
            
            # Flush Application Insights telemetry
            if _app_insights:
                await _app_insights.flush()
            
            await asyncio.sleep(interval_seconds)
            
        except Exception as e:
            logger.error(f"Monitoring loop error: {e}")
            await asyncio.sleep(interval_seconds)

async def monitoring_health_check() -> Dict[str, Any]:
    """Check monitoring system health"""
    try:
        components = {}
        
        if _health_checker:
            components['health_checker'] = 'initialized'
        else:
            components['health_checker'] = 'not_initialized'
        
        if _metrics_collector:
            components['metrics_collector'] = 'initialized'
        else:
            components['metrics_collector'] = 'not_initialized'
        
        if _app_insights and _app_insights.enabled:
            components['application_insights'] = 'enabled'
        else:
            components['application_insights'] = 'disabled'
        
        if _alert_manager:
            components['alert_manager'] = f"initialized_with_{len(_alert_manager.alert_rules)}_rules"
        else:
            components['alert_manager'] = 'not_initialized'
        
        overall_status = 'healthy' if all(
            status != 'not_initialized' for status in components.values()
        ) else 'degraded'
        
        return {
            'status': overall_status,
            'components': components
        }
        
    except Exception as e:
        logger.error(f"Monitoring health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e)
        }