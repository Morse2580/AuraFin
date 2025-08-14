# shared/logging.py
"""
Centralized logging configuration for CashAppAgent
Structured logging with correlation IDs for tracing
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict
from contextvars import ContextVar
import uuid

# Context variable for correlation ID across async operations
correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')


class StructuredFormatter(logging.Formatter):
    """
    JSON structured logging formatter
    Includes correlation IDs and standard fields
    """
    
    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'correlation_id': correlation_id.get() or str(uuid.uuid4()),
            'service': getattr(record, 'service', 'cashapp-agent'),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
            
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 
                          'pathname', 'filename', 'module', 'lineno', 
                          'funcName', 'created', 'msecs', 'relativeCreated',
                          'thread', 'threadName', 'processName', 'process',
                          'getMessage', 'exc_info', 'exc_text', 'stack_info']:
                log_entry[key] = value
                
        return json.dumps(log_entry)


def setup_logging(service_name: str, log_level: str = "INFO") -> logging.Logger:
    """
    Configure structured logging for a service
    
    Args:
        service_name: Name of the service (e.g., 'core-logic-engine')
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Configured logger instance
    """
    
    # Create logger
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create console handler with structured formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    
    # Set service name as default extra field
    logger = logging.LoggerAdapter(logger, {'service': service_name})
    
    return logger


def set_correlation_id(corr_id: str = None) -> str:
    """
    Set correlation ID for request tracing
    
    Args:
        corr_id: Correlation ID to set, generates UUID if None
    
    Returns:
        The correlation ID that was set
    """
    if corr_id is None:
        corr_id = str(uuid.uuid4())
    
    correlation_id.set(corr_id)
    return corr_id


def get_correlation_id() -> str:
    """Get current correlation ID"""
    return correlation_id.get() or str(uuid.uuid4())


class log_context:
    """Context manager for setting correlation ID and other logging context"""
    
    def __init__(self, correlation_id: str = None, **kwargs):
        self.correlation_id = correlation_id
        self.kwargs = kwargs
        self.previous_correlation_id = None
    
    def __enter__(self):
        self.previous_correlation_id = correlation_id.get() if correlation_id.get() else None
        set_correlation_id(self.correlation_id)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.previous_correlation_id:
            correlation_id.set(self.previous_correlation_id)
        else:
            correlation_id.set('')