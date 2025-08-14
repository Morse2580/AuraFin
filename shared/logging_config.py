# shared/logging_config.py
"""
Centralized logging configuration for CashAppAgent
Provides structured logging with correlation IDs and monitoring integration
"""

import os
import json
import time
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import logging
import logging.config
from contextlib import asynccontextmanager
from fastapi import Request

# Global correlation ID storage
_correlation_context = {}


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""

    def format(self, record):
        """Format log record as JSON"""
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        # Add correlation ID if available
        correlation_id = get_correlation_id()
        if correlation_id:
            log_entry['correlation_id'] = correlation_id

        # Add extra fields
        if hasattr(record, 'extra') and record.extra:
            log_entry.update(record.extra)

        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry)

def setup_logging_config():
    """Setup centralized logging configuration"""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_format = os.getenv('LOG_FORMAT', 'json')  # json or text
    
    if log_format == 'json':
        # Pass the callable directly to avoid import-time circular resolution
        formatter_config = {
            '()': JSONFormatter
        }
    else:
        formatter_config = {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        }
    
    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': formatter_config
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': log_level,
                'formatter': 'default',
                'stream': 'ext://sys.stdout'
            }
        },
        'root': {
            'level': log_level,
            'handlers': ['console']
        },
        'loggers': {
            'uvicorn': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False
            },
            'uvicorn.error': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False
            },
            'uvicorn.access': {
                'level': 'WARNING',
                'handlers': ['console'],
                'propagate': False
            }
        }
    }
    
    logging.config.dictConfig(config)

def get_logger(name: str) -> logging.Logger:
    """
    Get configured logger instance
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured logger
    """
    return logging.getLogger(name)

def set_correlation_id(correlation_id: str = None) -> str:
    """
    Set correlation ID for current request
    
    Args:
        correlation_id: Correlation ID to set (generates if None)
        
    Returns:
        The correlation ID that was set
    """
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    
    # Store in thread-local storage equivalent
    import threading
    current_thread = threading.current_thread()
    thread_id = current_thread.ident
    _correlation_context[thread_id] = correlation_id
    
    return correlation_id

def get_correlation_id() -> Optional[str]:
    """
    Get correlation ID for current request
    
    Returns:
        Current correlation ID or None
    """
    import threading
    current_thread = threading.current_thread()
    thread_id = current_thread.ident
    return _correlation_context.get(thread_id)

def clear_correlation_id():
    """Clear correlation ID for current thread"""
    import threading
    current_thread = threading.current_thread()
    thread_id = current_thread.ident
    _correlation_context.pop(thread_id, None)

async def correlation_id_middleware(request: Request, call_next):
    """
    FastAPI middleware to handle correlation IDs
    
    Args:
        request: FastAPI request
        call_next: Next middleware/endpoint
        
    Returns:
        Response with correlation ID header
    """
    # Get or generate correlation ID
    correlation_id = request.headers.get('X-Correlation-ID') or str(uuid.uuid4())
    
    # Set correlation ID
    set_correlation_id(correlation_id)
    
    try:
        # Process request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers['X-Correlation-ID'] = correlation_id
        
        return response
        
    finally:
        # Clean up correlation ID
        clear_correlation_id()

# Initialize logging on module import
setup_logging_config()
