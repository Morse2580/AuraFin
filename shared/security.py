# shared/security.py
"""
Security middleware and API key management for CashAppAgent
Provides comprehensive security controls for all FastAPI services
"""

import time
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Set
from functools import wraps
import asyncio
import json
import re

from fastapi import Request, Response, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import redis.asyncio as redis
import logging

from .config import ConfigurationManager
from .auth import JWTValidator
from .monitoring import MetricsCollector

logger = logging.getLogger(__name__)

# Security Constants
API_KEY_LENGTH = 32
MAX_REQUESTS_PER_MINUTE = 100
MAX_BURST_REQUESTS = 20
RATE_LIMIT_WINDOW = 60  # seconds
SUSPICIOUS_PATTERNS = [
    r'(?i)(union|select|insert|delete|drop|create|alter|exec|script)',
    r'(?i)(<script|javascript:|onload|onerror)',
    r'(?i)(\.\.\/|\.\.\\|%2e%2e)',
    r'(?i)(eval\(|function\(|setTimeout|setInterval)'
]

class APIKeyManager:
    """
    Manages API keys for service authentication
    Provides key generation, validation, and rotation
    """
    
    def __init__(self, config_manager: ConfigurationManager, redis_client: redis.Redis):
        self.config = config_manager
        self.redis = redis_client
        self.key_cache: Dict[str, Dict] = {}
        self.cache_ttl = 300  # 5 minutes
    
    async def generate_api_key(self, 
                              client_id: str, 
                              service_name: str,
                              permissions: List[str] = None,
                              expires_in_days: int = 365) -> Dict[str, str]:
        """
        Generate new API key for client/service
        
        Args:
            client_id: Client identifier
            service_name: Service name
            permissions: List of permissions
            expires_in_days: Key expiration in days
            
        Returns:
            Dict with key_id, api_key, and metadata
        """
        key_id = f"key_{client_id}_{service_name}_{int(time.time())}"
        api_key = f"caa_{secrets.token_urlsafe(API_KEY_LENGTH)}"
        
        # Hash key for storage
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        
        key_metadata = {
            'key_id': key_id,
            'key_hash': key_hash,
            'client_id': client_id,
            'service_name': service_name,
            'permissions': permissions or ['read'],
            'created_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': expires_at.isoformat(),
            'is_active': True,
            'last_used': None,
            'usage_count': 0
        }
        
        # Store in Redis with expiration
        await self.redis.hset(f"api_keys:{key_id}", mapping=key_metadata)
        await self.redis.expire(f"api_keys:{key_id}", int(timedelta(days=expires_in_days).total_seconds()))
        
        # Store hash -> key_id mapping for validation
        await self.redis.set(f"key_hash:{key_hash}", key_id, ex=int(timedelta(days=expires_in_days).total_seconds()))
        
        logger.info(f"Generated API key for {client_id}/{service_name}: {key_id}")
        
        return {
            'key_id': key_id,
            'api_key': api_key,
            'expires_at': expires_at.isoformat(),
            'permissions': permissions or ['read']
        }
    
    async def validate_api_key(self, api_key: str) -> Optional[Dict]:
        """
        Validate API key and return metadata
        
        Args:
            api_key: API key to validate
            
        Returns:
            Key metadata if valid, None if invalid
        """
        try:
            # Check cache first
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            
            if key_hash in self.key_cache:
                cached_data = self.key_cache[key_hash]
                if cached_data['cached_at'] + self.cache_ttl > time.time():
                    return cached_data['metadata']
            
            # Look up in Redis
            key_id = await self.redis.get(f"key_hash:{key_hash}")
            if not key_id:
                return None
            
            key_id = key_id.decode() if isinstance(key_id, bytes) else key_id
            key_metadata = await self.redis.hgetall(f"api_keys:{key_id}")
            
            if not key_metadata:
                return None
            
            # Convert bytes to strings
            metadata = {k.decode() if isinstance(k, bytes) else k: 
                       v.decode() if isinstance(v, bytes) else v 
                       for k, v in key_metadata.items()}
            
            # Check if key is active and not expired
            if not metadata.get('is_active', '').lower() == 'true':
                return None
            
            expires_at = datetime.fromisoformat(metadata['expires_at'])
            if expires_at < datetime.now(timezone.utc):
                return None
            
            # Update usage tracking
            await self._update_key_usage(key_id)
            
            # Cache the result
            self.key_cache[key_hash] = {
                'metadata': metadata,
                'cached_at': time.time()
            }
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error validating API key: {e}")
            return None
    
    async def _update_key_usage(self, key_id: str):
        """Update key usage statistics"""
        await self.redis.hincrby(f"api_keys:{key_id}", "usage_count", 1)
        await self.redis.hset(f"api_keys:{key_id}", "last_used", datetime.now(timezone.utc).isoformat())
    
    async def revoke_api_key(self, key_id: str) -> bool:
        """
        Revoke an API key
        
        Args:
            key_id: Key ID to revoke
            
        Returns:
            True if revoked successfully
        """
        try:
            await self.redis.hset(f"api_keys:{key_id}", "is_active", "false")
            await self.redis.hset(f"api_keys:{key_id}", "revoked_at", datetime.now(timezone.utc).isoformat())
            
            # Clear from cache
            self.key_cache.clear()
            
            logger.info(f"Revoked API key: {key_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error revoking API key {key_id}: {e}")
            return False
    
    async def list_keys(self, client_id: str = None) -> List[Dict]:
        """
        List API keys (metadata only)
        
        Args:
            client_id: Filter by client ID
            
        Returns:
            List of key metadata
        """
        try:
            pattern = "api_keys:*"
            keys = []
            
            async for key in self.redis.scan_iter(match=pattern):
                key_data = await self.redis.hgetall(key)
                if key_data:
                    metadata = {k.decode() if isinstance(k, bytes) else k: 
                               v.decode() if isinstance(v, bytes) else v 
                               for k, v in key_data.items()}
                    
                    if not client_id or metadata.get('client_id') == client_id:
                        # Remove sensitive data
                        safe_metadata = {k: v for k, v in metadata.items() if k != 'key_hash'}
                        keys.append(safe_metadata)
            
            return keys
            
        except Exception as e:
            logger.error(f"Error listing API keys: {e}")
            return []

class RateLimiter:
    """
    Redis-based rate limiter with sliding window
    Supports per-client and global rate limiting
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.window_size = RATE_LIMIT_WINDOW
    
    async def is_allowed(self, 
                        client_id: str, 
                        max_requests: int = MAX_REQUESTS_PER_MINUTE,
                        burst_limit: int = MAX_BURST_REQUESTS) -> Tuple[bool, Dict[str, int]]:
        """
        Check if request is allowed under rate limits
        
        Args:
            client_id: Client identifier
            max_requests: Max requests per window
            burst_limit: Burst request allowance
            
        Returns:
            (is_allowed, rate_limit_info)
        """
        now = time.time()
        window_start = now - self.window_size
        
        # Sliding window key
        window_key = f"rate_limit:{client_id}:{int(now // self.window_size)}"
        burst_key = f"burst_limit:{client_id}"
        
        try:
            # Use pipeline for atomic operations
            pipe = self.redis.pipeline()
            
            # Remove old entries from sliding window
            pipe.zremrangebyscore(window_key, 0, window_start)
            
            # Count current requests in window
            pipe.zcard(window_key)
            
            # Get burst count
            pipe.get(burst_key)
            
            results = await pipe.execute()
            current_count = results[1]
            burst_count = int(results[2] or 0)
            
            # Check limits
            if current_count >= max_requests:
                return False, {
                    'requests_remaining': 0,
                    'reset_time': int(now + self.window_size),
                    'limit_type': 'rate_limit'
                }
            
            if burst_count >= burst_limit:
                return False, {
                    'requests_remaining': 0,
                    'reset_time': int(now + 60),  # Burst resets every minute
                    'limit_type': 'burst_limit'
                }
            
            # Record this request
            request_id = f"{now}:{secrets.token_hex(8)}"
            pipe = self.redis.pipeline()
            pipe.zadd(window_key, {request_id: now})
            pipe.expire(window_key, self.window_size)
            pipe.incr(burst_key)
            pipe.expire(burst_key, 60)
            await pipe.execute()
            
            return True, {
                'requests_remaining': max_requests - current_count - 1,
                'reset_time': int(now + self.window_size),
                'limit_type': 'allowed'
            }
            
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Fail open for availability
            return True, {
                'requests_remaining': max_requests,
                'reset_time': int(now + self.window_size),
                'limit_type': 'error'
            }

class SecurityValidator:
    """
    Validates requests for security threats
    Detects SQL injection, XSS, path traversal, etc.
    """
    
    def __init__(self):
        self.suspicious_patterns = [re.compile(pattern) for pattern in SUSPICIOUS_PATTERNS]
        self.blocked_ips: Set[str] = set()
        self.suspicious_activity: Dict[str, List[float]] = {}
    
    def validate_request_data(self, data: str) -> Tuple[bool, List[str]]:
        """
        Validate request data for security threats
        
        Args:
            data: Request data to validate
            
        Returns:
            (is_safe, list of threats detected)
        """
        threats = []
        
        if not data:
            return True, threats
        
        # Check for suspicious patterns
        for pattern in self.suspicious_patterns:
            if pattern.search(data):
                threats.append(f"Suspicious pattern detected: {pattern.pattern}")
        
        # Check for excessive length (potential DoS)
        if len(data) > 1000000:  # 1MB limit
            threats.append("Request data too large")
        
        # Check for null bytes
        if '\x00' in data:
            threats.append("Null bytes detected")
        
        return len(threats) == 0, threats
    
    def check_ip_reputation(self, client_ip: str) -> bool:
        """
        Check if IP has suspicious activity
        
        Args:
            client_ip: Client IP address
            
        Returns:
            True if IP is allowed
        """
        if client_ip in self.blocked_ips:
            return False
        
        # Check request frequency
        now = time.time()
        if client_ip in self.suspicious_activity:
            # Remove old entries
            self.suspicious_activity[client_ip] = [
                timestamp for timestamp in self.suspicious_activity[client_ip]
                if now - timestamp < 300  # 5 minute window
            ]
            
            # Check if too many requests
            if len(self.suspicious_activity[client_ip]) > 1000:  # 1000 requests in 5 minutes
                self.blocked_ips.add(client_ip)
                logger.warning(f"Blocked suspicious IP: {client_ip}")
                return False
        else:
            self.suspicious_activity[client_ip] = []
        
        # Record this request
        self.suspicious_activity[client_ip].append(now)
        return True

class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive security middleware for FastAPI applications
    Handles authentication, rate limiting, input validation, and logging
    """
    
    def __init__(self, app: ASGIApp, config: ConfigurationManager):
        super().__init__(app)
        self.config = config
        self.api_key_manager = None
        self.rate_limiter = None
        self.security_validator = SecurityValidator()
        self.jwt_validator = None
        self.metrics = MetricsCollector("security")
        
        # Excluded paths (health checks, metrics)
        self.excluded_paths = {'/health', '/metrics', '/docs', '/openapi.json', '/favicon.ico'}
    
    async def setup(self):
        """Initialize async components"""
        if not self.api_key_manager:
            redis_client = redis.from_url(self.config.get('REDIS_URL', 'redis://localhost:6379'))
            self.api_key_manager = APIKeyManager(self.config, redis_client)
            self.rate_limiter = RateLimiter(redis_client)
            self.jwt_validator = JWTValidator()
    
    async def dispatch(self, request: Request, call_next):
        """Process request through security middleware"""
        start_time = time.time()
        
        try:
            # Initialize if needed
            await self.setup()
            
            # Skip security for excluded paths
            if request.url.path in self.excluded_paths:
                return await call_next(request)
            
            # 1. IP reputation check
            client_ip = self._get_client_ip(request)
            if not self.security_validator.check_ip_reputation(client_ip):
                self.metrics.increment_counter("security.blocked_requests", {"reason": "ip_blocked"})
                raise HTTPException(status_code=403, detail="Access denied")
            
            # 2. Rate limiting
            auth_result = await self._authenticate_request(request)
            client_id = auth_result.get('client_id', client_ip) if auth_result else client_ip
            
            is_allowed, rate_info = await self.rate_limiter.is_allowed(client_id)
            if not is_allowed:
                self.metrics.increment_counter("security.rate_limited", {"client_id": client_id})
                response = Response(
                    content="Rate limit exceeded",
                    status_code=429,
                    headers={
                        "X-RateLimit-Remaining": str(rate_info.get('requests_remaining', 0)),
                        "X-RateLimit-Reset": str(rate_info.get('reset_time', 0))
                    }
                )
                return response
            
            # 3. Input validation
            if request.method in ['POST', 'PUT', 'PATCH']:
                body = await request.body()
                if body:
                    body_str = body.decode('utf-8', errors='ignore')
                    is_safe, threats = self.security_validator.validate_request_data(body_str)
                    if not is_safe:
                        self.metrics.increment_counter("security.threats_detected", 
                                                     {"client_id": client_id, "threat_count": str(len(threats))})
                        logger.warning(f"Security threats detected from {client_ip}: {threats}")
                        raise HTTPException(status_code=400, detail="Invalid request data")
                    
                    # Restore body for downstream processing
                    request._body = body
            
            # 4. Authentication validation (already done above)
            if not auth_result:
                self.metrics.increment_counter("security.auth_failed", {"client_id": client_id})
                raise HTTPException(status_code=401, detail="Authentication required")
            
            # 5. Add security headers and process request
            request.state.auth_info = auth_result
            request.state.client_ip = client_ip
            
            response = await call_next(request)
            
            # Add security headers
            response.headers.update({
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-XSS-Protection": "1; mode=block",
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                "Content-Security-Policy": "default-src 'self'",
                "X-RateLimit-Remaining": str(rate_info.get('requests_remaining', 0)),
                "X-RateLimit-Reset": str(rate_info.get('reset_time', 0))
            })
            
            # Log successful request
            processing_time = (time.time() - start_time) * 1000
            self.metrics.record_histogram("security.request_duration", processing_time)
            
            logger.info(f"Secure request processed: {request.method} {request.url.path} "
                       f"from {client_ip} ({processing_time:.2f}ms)")
            
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Security middleware error: {e}")
            self.metrics.increment_counter("security.middleware_errors")
            raise HTTPException(status_code=500, detail="Security processing error")
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request"""
        # Check X-Forwarded-For header first (for load balancers)
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        # Check X-Real-IP header
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip
        
        # Fall back to direct connection
        if hasattr(request, 'client') and request.client:
            return request.client.host
        
        return "unknown"
    
    async def _authenticate_request(self, request: Request) -> Optional[Dict]:
        """
        Authenticate request using various methods
        
        Args:
            request: FastAPI request object
            
        Returns:
            Authentication metadata if successful
        """
        # 1. Try API Key authentication
        api_key = request.headers.get('X-API-Key')
        if api_key:
            api_auth = await self.api_key_manager.validate_api_key(api_key)
            if api_auth:
                return {
                    'auth_method': 'api_key',
                    'client_id': api_auth['client_id'],
                    'service_name': api_auth['service_name'],
                    'permissions': json.loads(api_auth.get('permissions', '[]')) if isinstance(api_auth.get('permissions'), str) else api_auth.get('permissions', [])
                }
        
        # 2. Try Bearer token (JWT)
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                jwt_payload = await self.jwt_validator.validate_token(token)
                if jwt_payload:
                    return {
                        'auth_method': 'jwt',
                        'client_id': jwt_payload.get('sub'),
                        'service_name': jwt_payload.get('aud'),
                        'permissions': jwt_payload.get('permissions', ['read'])
                    }
            except Exception as e:
                logger.debug(f"JWT validation failed: {e}")
        
        return None

# FastAPI Security Dependencies
security_bearer = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_current_user(
    request: Request,
    bearer_token: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    api_key: Optional[str] = Security(api_key_header)
) -> Dict:
    """
    FastAPI dependency for authentication
    
    Returns:
        Current user/client information
    """
    if hasattr(request.state, 'auth_info') and request.state.auth_info:
        return request.state.auth_info
    
    raise HTTPException(status_code=401, detail="Authentication required")

def require_permission(permission: str):
    """
    FastAPI dependency factory for permission checking
    
    Args:
        permission: Required permission
        
    Returns:
        Dependency function
    """
    async def check_permission(current_user: Dict = Depends(get_current_user)) -> Dict:
        user_permissions = current_user.get('permissions', [])
        
        if permission not in user_permissions and 'admin' not in user_permissions:
            raise HTTPException(
                status_code=403, 
                detail=f"Permission required: {permission}"
            )
        
        return current_user
    
    return check_permission

class SecurityAuditLogger:
    """
    Logs security events for audit and compliance
    """
    
    def __init__(self, config: ConfigurationManager):
        self.config = config
        self.audit_logger = logging.getLogger('security_audit')
        
        # Configure audit log handler
        handler = logging.FileHandler('/app/logs/security_audit.log')
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.audit_logger.addHandler(handler)
        self.audit_logger.setLevel(logging.INFO)
    
    def log_authentication_event(self, 
                                client_id: str, 
                                client_ip: str, 
                                success: bool, 
                                auth_method: str,
                                additional_info: Dict = None):
        """Log authentication events"""
        event = {
            'event_type': 'authentication',
            'client_id': client_id,
            'client_ip': client_ip,
            'success': success,
            'auth_method': auth_method,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'additional_info': additional_info or {}
        }
        
        self.audit_logger.info(json.dumps(event))
    
    def log_authorization_event(self, 
                               client_id: str, 
                               resource: str, 
                               action: str, 
                               success: bool,
                               reason: str = None):
        """Log authorization events"""
        event = {
            'event_type': 'authorization',
            'client_id': client_id,
            'resource': resource,
            'action': action,
            'success': success,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        self.audit_logger.info(json.dumps(event))
    
    def log_security_event(self, 
                          event_type: str, 
                          client_ip: str, 
                          details: Dict,
                          severity: str = 'medium'):
        """Log general security events"""
        event = {
            'event_type': event_type,
            'client_ip': client_ip,
            'severity': severity,
            'details': details,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        self.audit_logger.warning(json.dumps(event))

# Utility functions for service setup
def setup_security_middleware(app, config: ConfigurationManager):
    """
    Add security middleware to FastAPI app
    
    Args:
        app: FastAPI application
        config: Configuration manager
    """
    middleware = SecurityMiddleware(app, config)
    app.add_middleware(BaseHTTPMiddleware, dispatch=middleware.dispatch)
    return middleware

async def create_service_api_key(client_id: str, service_name: str, config: ConfigurationManager) -> Dict:
    """
    Utility to create API key for service
    
    Args:
        client_id: Client identifier
        service_name: Service name
        config: Configuration manager
        
    Returns:
        API key information
    """
    redis_client = redis.from_url(config.get('REDIS_URL', 'redis://localhost:6379'))
    api_key_manager = APIKeyManager(config, redis_client)
    
    return await api_key_manager.generate_api_key(
        client_id=client_id,
        service_name=service_name,
        permissions=['read', 'write'],
        expires_in_days=365
    )

# Request validation decorators
def validate_financial_amount(amount_field: str = "amount"):
    """
    Decorator to validate financial amounts
    
    Args:
        amount_field: Field name containing amount
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object in args/kwargs
            request_data = None
            for arg in args:
                if hasattr(arg, amount_field):
                    request_data = arg
                    break
            
            if request_data:
                amount = getattr(request_data, amount_field, None)
                if amount is not None:
                    # Validate amount range
                    if amount < 0:
                        raise HTTPException(status_code=400, detail="Amount cannot be negative")
                    if amount > 1000000:  # 1M limit
                        raise HTTPException(status_code=400, detail="Amount exceeds maximum limit")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def validate_currency_code(currency_field: str = "currency"):
    """
    Decorator to validate currency codes
    
    Args:
        currency_field: Field name containing currency
    """
    valid_currencies = {'EUR', 'USD', 'GBP', 'CAD', 'AUD', 'JPY', 'CHF', 'SEK', 'NOK', 'DKK'}
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object in args/kwargs
            request_data = None
            for arg in args:
                if hasattr(arg, currency_field):
                    request_data = arg
                    break
            
            if request_data:
                currency = getattr(request_data, currency_field, None)
                if currency and currency not in valid_currencies:
                    raise HTTPException(status_code=400, detail=f"Invalid currency code: {currency}")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Example usage in FastAPI routes
"""
from shared.security import (
    SecurityMiddleware, get_current_user, require_permission,
    validate_financial_amount, validate_currency_code, setup_security_middleware
)

# In main.py
app = FastAPI()
security_middleware = setup_security_middleware(app, config)

# In routes
@app.post("/api/v1/process_transaction")
@validate_financial_amount("amount")
@validate_currency_code("currency")
async def process_transaction(
    request: ProcessTransactionRequest,
    current_user: Dict = Depends(require_permission("process_transactions"))
):
    # Process transaction with security validation
    pass
"""
