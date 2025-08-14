# shared/health_checks.py
"""
Health check utilities for all CashAppAgent services
Standardized health check endpoints and database connectivity
"""

from typing import Dict, Any
import asyncio
import aiohttp
from datetime import datetime
import psycopg2
from psycopg2 import OperationalError


class HealthCheckManager:
    """
    Centralized health check management
    Provides standardized health checks for all services
    """
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.checks = {}
        self.startup_time = datetime.utcnow()
    
    def add_check(self, name: str, check_func):
        """Add a health check function"""
        self.checks[name] = check_func
    
    async def run_checks(self) -> Dict[str, Any]:
        """
        Run all registered health checks
        
        Returns:
            Health check results with overall status
        """
        results = {
            'service': self.service_name,
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'uptime_seconds': (datetime.utcnow() - self.startup_time).total_seconds(),
            'checks': {}
        }
        
        overall_healthy = True
        
        for name, check_func in self.checks.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()
                
                results['checks'][name] = {
                    'status': 'healthy' if result else 'unhealthy',
                    'details': result if isinstance(result, dict) else {}
                }
                
                if not result:
                    overall_healthy = False
                    
            except Exception as e:
                results['checks'][name] = {
                    'status': 'error',
                    'error': str(e)
                }
                overall_healthy = False
        
        results['status'] = 'healthy' if overall_healthy else 'unhealthy'
        return results


async def check_database_connection(connection_string: str) -> bool:
    """
    Check PostgreSQL database connectivity
    
    Args:
        connection_string: Database connection string
    
    Returns:
        True if connection successful, False otherwise
    """
    try:
        conn = psycopg2.connect(connection_string)
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        cursor.close()
        conn.close()
        return True
    except OperationalError:
        return False


async def check_http_service(url: str, timeout: int = 5) -> bool:
    """
    Check HTTP service availability
    
    Args:
        url: Service URL to check
        timeout: Request timeout in seconds
    
    Returns:
        True if service responds with 2xx status, False otherwise
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(timeout)) as response:
                return 200 <= response.status < 300
    except Exception:
        return False


def check_disk_space(path: str = "/", min_free_gb: float = 1.0) -> Dict[str, Any]:
    """
    Check available disk space
    
    Args:
        path: Path to check
        min_free_gb: Minimum free space in GB
    
    Returns:
        Dictionary with disk space info and healthy status
    """
    import shutil
    
    total, used, free = shutil.disk_usage(path)
    free_gb = free / (1024**3)
    
    return {
        'healthy': free_gb >= min_free_gb,
        'free_gb': round(free_gb, 2),
        'total_gb': round(total / (1024**3), 2),
        'used_percent': round((used / total) * 100, 1)
    }