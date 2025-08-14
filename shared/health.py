# shared/health.py
"""
Health check utilities for CashAppAgent services
Standardized health checking across all microservices
"""

import time
import asyncio
from typing import Dict, Any, List, Callable
from datetime import datetime, timezone
from dataclasses import dataclass

from .logging_config import get_logger

logger = get_logger(__name__)

@dataclass
class HealthResponse:
    """Standard health response format"""
    status: str
    timestamp: str
    response_time_ms: int
    service: str
    version: str
    checks: Dict[str, Any] = None

class HealthChecker:
    """
    Basic health checker for individual services
    Provides standard health check functionality
    """
    
    def __init__(self, service_name: str, version: str = "1.0.0"):
        self.service_name = service_name
        self.version = version
        self.startup_time = time.time()
        self.health_checks = {}
    
    def add_check(self, name: str, check_function: Callable):
        """Add health check function"""
        self.health_checks[name] = check_function
        logger.info(f"Added health check: {name}")
    
    async def check_health(self) -> HealthResponse:
        """
        Run basic health check
        
        Returns:
            Basic health response
        """
        start_time = time.time()
        
        try:
            # Basic service health
            uptime_seconds = time.time() - self.startup_time
            
            checks = {
                'uptime_seconds': uptime_seconds,
                'status': 'healthy'
            }
            
            # Run additional checks if any
            if self.health_checks:
                for name, check_func in self.health_checks.items():
                    try:
                        result = await asyncio.wait_for(check_func(), timeout=10)
                        checks[name] = result
                    except Exception as e:
                        checks[name] = {'status': 'failed', 'error': str(e)}
                        checks['status'] = 'degraded'
            
            response_time = int((time.time() - start_time) * 1000)
            
            return HealthResponse(
                status=checks['status'],
                timestamp=datetime.now(timezone.utc).isoformat(),
                response_time_ms=response_time,
                service=self.service_name,
                version=self.version,
                checks=checks
            )
            
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            logger.error(f"Health check failed: {e}")
            
            return HealthResponse(
                status='unhealthy',
                timestamp=datetime.now(timezone.utc).isoformat(),
                response_time_ms=response_time,
                service=self.service_name,
                version=self.version,
                checks={'error': str(e)}
            )

# Standard health check functions
async def check_database_connection(connection_string: str) -> Dict[str, Any]:
    """Check database connectivity"""
    try:
        import asyncpg
        
        start_time = time.time()
        conn = await asyncpg.connect(connection_string)
        await conn.execute('SELECT 1')
        await conn.close()
        
        response_time = int((time.time() - start_time) * 1000)
        
        return {
            'status': 'healthy',
            'response_time_ms': response_time
        }
        
    except Exception as e:
        return {
            'status': 'unhealthy',
            'error': str(e)
        }

async def check_http_service(url: str, timeout: int = 5) -> Dict[str, Any]:
    """Check HTTP service health"""
    try:
        import httpx
        
        start_time = time.time()
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout)
            response_time = int((time.time() - start_time) * 1000)
            
            return {
                'status': 'healthy' if response.status_code == 200 else 'degraded',
                'status_code': response.status_code,
                'response_time_ms': response_time
            }
            
    except Exception as e:
        return {
            'status': 'unhealthy',
            'error': str(e)
        }

async def check_azure_service(service_name: str, test_function: Callable = None) -> Dict[str, Any]:
    """Check Azure service connectivity"""
    try:
        if test_function:
            start_time = time.time()
            result = await test_function()
            response_time = int((time.time() - start_time) * 1000)
            
            return {
                'status': 'healthy' if result else 'unhealthy',
                'response_time_ms': response_time,
                'service': service_name
            }
        else:
            return {
                'status': 'not_configured',
                'service': service_name
            }
            
    except Exception as e:
        return {
            'status': 'unhealthy',
            'error': str(e),
            'service': service_name
        }