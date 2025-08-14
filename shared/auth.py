# shared/auth.py
"""
Azure AD Authentication and Authorization for CashAppAgent
Provides service-to-service authentication using managed identities
"""

import os
import time
import httpx
from typing import Dict, List, Optional, Callable
from functools import wraps
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from azure.identity import DefaultAzureCredential, ClientSecretCredential
from azure.core.exceptions import AzureError
import jwt
from jwt import PyJWTError

from .logging import setup_logging
from .exception import CashAppException

logger = setup_logging("auth")

class AzureAuthConfig:
    """Azure AD configuration"""
    TENANT_ID = os.getenv('AZURE_TENANT_ID')
    CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
    CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET')
    SCOPE = os.getenv('AZURE_SCOPE', 'https://graph.microsoft.com/.default')
    
    # Service-to-service authentication
    CASHAPP_APP_ID = os.getenv('CASHAPP_APP_ID')
    REQUIRED_ROLES = {
        'cle': ['CashApp.Transaction.Process', 'CashApp.Data.Read'],
        'dim': ['CashApp.Document.Process', 'CashApp.Storage.Access'],
        'eic': ['CashApp.ERP.Access', 'CashApp.Invoice.Manage'],
        'cm': ['CashApp.Communication.Send', 'CashApp.Template.Access']
    }

config = AzureAuthConfig()

class TokenManager:
    """Manages Azure AD access tokens with caching and refresh"""
    
    def __init__(self):
        self._tokens: Dict[str, Dict] = {}
        self._credential = None
        self._initialize_credential()
    
    def _initialize_credential(self):
        """Initialize Azure credential based on environment"""
        try:
            if config.CLIENT_SECRET and config.CLIENT_ID and config.TENANT_ID:
                # Service principal authentication
                self._credential = ClientSecretCredential(
                    tenant_id=config.TENANT_ID,
                    client_id=config.CLIENT_ID,
                    client_secret=config.CLIENT_SECRET
                )
                logger.info("Initialized service principal authentication")
            else:
                # Managed identity authentication
                self._credential = DefaultAzureCredential()
                logger.info("Initialized managed identity authentication")
                
        except Exception as e:
            logger.error(f"Failed to initialize Azure credentials: {e}")
            raise CashAppException(f"Authentication initialization failed: {e}", "AUTH_INIT_ERROR")
    
    async def get_token(self, scope: str = None) -> str:
        """
        Get access token for specified scope with caching
        
        Args:
            scope: OAuth scope (defaults to Graph API)
            
        Returns:
            Valid access token
        """
        if not scope:
            scope = config.SCOPE
            
        # Check cache first
        if scope in self._tokens:
            token_info = self._tokens[scope]
            if time.time() < token_info['expires_at'] - 300:  # 5 min buffer
                return token_info['access_token']
        
        try:
            # Get new token
            token_response = self._credential.get_token(scope)
            
            # Cache token
            self._tokens[scope] = {
                'access_token': token_response.token,
                'expires_at': token_response.expires_on
            }
            
            logger.debug(f"Retrieved new access token for scope: {scope}")
            return token_response.token
            
        except AzureError as e:
            logger.error(f"Failed to get access token: {e}")
            raise CashAppException(f"Token acquisition failed: {e}", "TOKEN_ERROR")
    
    def clear_cache(self, scope: str = None):
        """Clear token cache for scope or all scopes"""
        if scope:
            self._tokens.pop(scope, None)
        else:
            self._tokens.clear()
        logger.info(f"Token cache cleared for: {scope or 'all scopes'}")

# Global token manager
token_manager = TokenManager()

class JWTValidator:
    """Validates JWT tokens from Azure AD"""
    
    def __init__(self):
        self._jwks_cache = {}
        self._jwks_expiry = 0
    
    async def validate_token(self, token: str) -> Dict:
        """
        Validate JWT token and extract claims
        
        Args:
            token: JWT token to validate
            
        Returns:
            Token claims if valid
            
        Raises:
            HTTPException: If token is invalid
        """
        try:
            # Decode without verification first to get header
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get('kid')
            
            if not kid:
                raise HTTPException(status_code=401, detail="Token missing key ID")
            
            # Get signing key
            signing_key = await self._get_signing_key(kid)
            
            # Validate token
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=['RS256'],
                audience=config.CASHAPP_APP_ID,
                issuer=f"https://sts.windows.net/{config.TENANT_ID}/"
            )
            
            logger.debug("Token validated successfully", extra={'sub': payload.get('sub')})
            return payload
            
        except PyJWTError as e:
            logger.warning(f"JWT validation failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            raise HTTPException(status_code=500, detail="Authentication error")
    
    async def _get_signing_key(self, kid: str) -> str:
        """Get JWT signing key from Azure AD JWKS endpoint"""
        current_time = time.time()
        
        # Check cache
        if current_time < self._jwks_expiry and kid in self._jwks_cache:
            return self._jwks_cache[kid]
        
        try:
            # Fetch JWKS
            jwks_url = f"https://login.microsoftonline.com/{config.TENANT_ID}/discovery/v2.0/keys"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(jwks_url)
                response.raise_for_status()
                jwks = response.json()
            
            # Find key by kid
            for key in jwks.get('keys', []):
                if key.get('kid') == kid:
                    # Convert to PEM format
                    from cryptography.hazmat.primitives import serialization
                    from cryptography.hazmat.primitives.asymmetric import rsa
                    import base64
                    
                    # Decode the modulus and exponent
                    n = base64.urlsafe_b64decode(key['n'] + '==')
                    e = base64.urlsafe_b64decode(key['e'] + '==')
                    
                    # Create RSA public key
                    public_numbers = rsa.RSAPublicNumbers(
                        int.from_bytes(e, 'big'),
                        int.from_bytes(n, 'big')
                    )
                    public_key = public_numbers.public_key()
                    
                    # Convert to PEM
                    pem = public_key.public_key().public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo
                    )
                    
                    # Cache key
                    self._jwks_cache[kid] = pem
                    self._jwks_expiry = current_time + 3600  # Cache for 1 hour
                    
                    return pem
            
            raise ValueError(f"Key {kid} not found in JWKS")
            
        except Exception as e:
            logger.error(f"Failed to get signing key: {e}")
            raise HTTPException(status_code=500, detail="Failed to validate token")

# Global JWT validator
jwt_validator = JWTValidator()

# Security schemes
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """
    Extract and validate current user from JWT token
    
    Returns:
        User claims from validated token
    """
    token = credentials.credentials
    return await jwt_validator.validate_token(token)

def require_roles(required_roles: List[str]) -> Callable:
    """
    Decorator to require specific roles for endpoint access
    
    Args:
        required_roles: List of required Azure AD app roles
        
    Returns:
        Decorated function with role checking
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get user from kwargs (injected by FastAPI)
            user = None
            for key, value in kwargs.items():
                if isinstance(value, dict) and 'sub' in value:
                    user = value
                    break
            
            if not user:
                raise HTTPException(status_code=401, detail="Authentication required")
            
            # Check roles
            user_roles = user.get('roles', [])
            if not any(role in user_roles for role in required_roles):
                logger.warning(f"Access denied - required roles: {required_roles}, user roles: {user_roles}")
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

class ServiceAuthenticator:
    """Handles service-to-service authentication"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.required_roles = config.REQUIRED_ROLES.get(service_name, [])
    
    async def get_service_token(self, target_service: str) -> str:
        """
        Get token for calling another service
        
        Args:
            target_service: Name of target service
            
        Returns:
            Access token for service-to-service calls
        """
        scope = f"api://{config.CASHAPP_APP_ID}/.default"
        return await token_manager.get_token(scope)
    
    async def authenticate_request(self, request: Request) -> Dict:
        """
        Authenticate incoming service request
        
        Args:
            request: FastAPI request object
            
        Returns:
            Validated token claims
        """
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Bearer token required")
        
        token = auth_header[7:]  # Remove 'Bearer ' prefix
        claims = await jwt_validator.validate_token(token)
        
        # Verify service has required roles
        user_roles = claims.get('roles', [])
        if not any(role in user_roles for role in self.required_roles):
            raise HTTPException(status_code=403, detail="Insufficient service permissions")
        
        return claims

# HTTP client with automatic authentication
class AuthenticatedHttpClient:
    """HTTP client that automatically adds authentication headers"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.authenticator = ServiceAuthenticator(service_name)
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        Make authenticated HTTP request
        
        Args:
            method: HTTP method
            url: Request URL
            **kwargs: Additional request parameters
            
        Returns:
            HTTP response
        """
        try:
            # Get service token
            token = await self.authenticator.get_service_token("target")
            
            # Add auth header
            headers = kwargs.get('headers', {})
            headers['Authorization'] = f'Bearer {token}'
            kwargs['headers'] = headers
            
            # Make request
            response = await self.client.request(method, url, **kwargs)
            return response
            
        except Exception as e:
            logger.error(f"Authenticated request failed: {e}")
            raise
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

# Middleware for request authentication
async def auth_middleware(request: Request, call_next):
    """
    Authentication middleware for FastAPI
    Validates JWT tokens on protected endpoints
    """
    # Skip auth for health checks and metrics
    if request.url.path in ['/health', '/metrics', '/docs', '/openapi.json']:
        return await call_next(request)
    
    # Skip auth for local development
    if os.getenv('ENVIRONMENT') == 'development':
        return await call_next(request)
    
    try:
        # Validate authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Authentication required")
        
        token = auth_header[7:]
        claims = await jwt_validator.validate_token(token)
        
        # Add user to request state
        request.state.user = claims
        
        return await call_next(request)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication middleware error: {e}")
        raise HTTPException(status_code=500, detail="Authentication error")

# Dependency for extracting authenticated user
async def get_authenticated_user(request: Request) -> Dict:
    """
    Get authenticated user from request state
    
    Returns:
        User claims from validated token
    """
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

# Role-based access control decorators
def require_transaction_access(func: Callable) -> Callable:
    """Require transaction processing permissions"""
    return require_roles(['CashApp.Transaction.Process', 'CashApp.Data.Read'])(func)

def require_document_access(func: Callable) -> Callable:
    """Require document processing permissions"""
    return require_roles(['CashApp.Document.Process', 'CashApp.Storage.Access'])(func)

def require_erp_access(func: Callable) -> Callable:
    """Require ERP integration permissions"""
    return require_roles(['CashApp.ERP.Access', 'CashApp.Invoice.Manage'])(func)

def require_communication_access(func: Callable) -> Callable:
    """Require communication permissions"""
    return require_roles(['CashApp.Communication.Send', 'CashApp.Template.Access'])(func)

def require_admin_access(func: Callable) -> Callable:
    """Require admin permissions"""
    return require_roles(['CashApp.Admin.Manage', 'CashApp.System.Configure'])(func)

# API Key authentication for simpler scenarios
class APIKeyManager:
    """Manages API keys for client access"""
    
    def __init__(self):
        self._api_keys = {}
        self._load_api_keys()
    
    def _load_api_keys(self):
        """Load API keys from environment or key vault"""
        # For now, load from environment variables
        api_keys_str = os.getenv('CASHAPP_API_KEYS', '')
        for key_pair in api_keys_str.split(','):
            if ':' in key_pair:
                client_id, api_key = key_pair.split(':', 1)
                self._api_keys[api_key] = {
                    'client_id': client_id,
                    'permissions': ['basic_access'],
                    'created_at': time.time()
                }
    
    def validate_api_key(self, api_key: str) -> Optional[Dict]:
        """
        Validate API key and return client info
        
        Args:
            api_key: API key to validate
            
        Returns:
            Client info if valid, None otherwise
        """
        return self._api_keys.get(api_key)
    
    def create_api_key(self, client_id: str, permissions: List[str]) -> str:
        """
        Create new API key for client
        
        Args:
            client_id: Client identifier
            permissions: List of permissions to grant
            
        Returns:
            Generated API key
        """
        import secrets
        api_key = secrets.token_urlsafe(32)
        
        self._api_keys[api_key] = {
            'client_id': client_id,
            'permissions': permissions,
            'created_at': time.time()
        }
        
        logger.info(f"Created API key for client: {client_id}")
        return api_key

# Global API key manager
api_key_manager = APIKeyManager()

async def get_api_key_auth(request: Request) -> Dict:
    """
    Authenticate using API key from X-API-Key header
    
    Returns:
        Client info from valid API key
    """
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    client_info = api_key_manager.validate_api_key(api_key)
    if not client_info:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return client_info

# Combined authentication dependency
async def get_current_principal(request: Request) -> Dict:
    """
    Get current authenticated principal (user or service)
    Supports both JWT and API key authentication
    
    Returns:
        Principal info with roles/permissions
    """
    # Try JWT first
    try:
        return await get_authenticated_user(request)
    except HTTPException:
        pass
    
    # Try API key
    try:
        return await get_api_key_auth(request)
    except HTTPException:
        pass
    
    # No valid authentication found
    raise HTTPException(status_code=401, detail="Authentication required")

# Health check for authentication system
async def auth_health_check() -> Dict:
    """
    Check authentication system health
    
    Returns:
        Health status of auth components
    """
    try:
        # Test token acquisition
        test_token = await token_manager.get_token()
        token_status = "healthy" if test_token else "failed"
        
        # Test Azure AD connectivity
        jwks_url = f"https://login.microsoftonline.com/{config.TENANT_ID}/discovery/v2.0/keys"
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url, timeout=10)
            azure_ad_status = "healthy" if response.status_code == 200 else "failed"
        
        return {
            "status": "healthy" if all([token_status == "healthy", azure_ad_status == "healthy"]) else "degraded",
            "components": {
                "token_acquisition": token_status,
                "azure_ad_connectivity": azure_ad_status,
                "api_keys_loaded": len(api_key_manager._api_keys)
            }
        }
        
    except Exception as e:
        logger.error(f"Auth health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }