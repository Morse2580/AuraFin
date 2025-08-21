# CashAppAgent Security Implementation

This document outlines the comprehensive security implementation for CashAppAgent, including authentication, authorization, rate limiting, input validation, and security monitoring.

## Security Architecture

### 1. Authentication & Authorization

#### API Key Authentication
- **Location**: `shared/security.py`
- **Features**:
  - 32-character secure API keys with `caa_` prefix
  - Redis-based key storage with expiration
  - Per-service and per-client key management
  - Usage tracking and audit logging

#### JWT Token Authentication
- **Location**: `shared/auth.py`
- **Features**:
  - Azure AD integration for service principals
  - JWT validation with audience and issuer verification
  - Token caching and refresh management

#### Permissions System
- **Granular Permissions**: `read`, `write`, `process_transactions`, `admin`
- **Role-Based Access**: Different permission sets for services vs clients
- **FastAPI Dependencies**: `get_current_user()`, `require_permission()`

### 2. Rate Limiting

#### Redis-Based Rate Limiting
- **Per-client limits**: 100 requests/minute
- **Burst protection**: 20 requests/second burst
- **Sliding window**: 60-second windows with cleanup
- **IP-based fallback**: When client ID unavailable

#### Nginx Rate Limiting
- **Location**: `infrastructure/nginx/nginx.conf`
- **Features**:
  - Multiple rate limit zones (api, burst, auth)
  - Connection limiting per IP
  - Geographic and pattern-based blocking

### 3. Input Validation & Security

#### Request Validation
- **SQL Injection Protection**: Pattern-based detection
- **XSS Prevention**: Script tag and JavaScript detection
- **Path Traversal**: Directory traversal pattern blocking
- **Null Byte Detection**: Binary content validation

#### Financial Data Validation
- **Amount Validation**: Negative amount prevention, maximum limits
- **Currency Validation**: ISO currency code enforcement
- **Decimal Precision**: Financial calculation accuracy

### 4. Security Middleware

#### Comprehensive Middleware (`SecurityMiddleware`)
- **IP Reputation**: Suspicious activity tracking and blocking
- **Request Logging**: Comprehensive audit trail
- **Security Headers**: HSTS, CSP, XSS protection
- **Error Handling**: Secure error responses

### 5. Network Security

#### Nginx Security Configuration
- **Security Headers**: Complete set of security headers
- **SSL/TLS**: HSTS enforcement, secure redirects
- **Attack Prevention**: Common attack pattern blocking
- **Access Control**: IP allowlisting for sensitive endpoints

#### Docker Network Security
- **Isolated Network**: `cashapp-network` with custom subnet
- **Service Communication**: Internal-only service-to-service
- **Port Exposure**: Minimal external port exposure

## Implementation Guide

### 1. Setting Up Security

```bash
# Initialize security configuration
python scripts/setup_security.py setup

# Reset security (if needed)
python scripts/setup_security.py reset
```

### 2. Service Integration

```python
# In FastAPI services
from shared.security import (
    setup_security_middleware, get_current_user, require_permission,
    validate_financial_amount, validate_currency_code
)

# Setup middleware
app = FastAPI()
security_middleware = setup_security_middleware(app, config_manager)

# Protect endpoints
@app.post("/api/v1/process_transaction")
@validate_financial_amount("amount")
@validate_currency_code("currency")
async def process_transaction(
    request: ProcessTransactionRequest,
    current_user: Dict = Depends(require_permission("process_transactions"))
):
    # Secure endpoint implementation
    pass
```

### 3. API Key Management

```python
# Create API key
from shared.security import create_service_api_key

key_info = await create_service_api_key(
    client_id="my-client",
    service_name="api-client",
    config=config_manager
)

# Use API key
headers = {"X-API-Key": key_info['api_key']}
response = await client.post("/api/v1/endpoint", headers=headers)
```

### 4. Monitoring Security Events

#### Audit Logging
- **Location**: `/app/logs/security_audit.log`
- **Events**: Authentication, authorization, security violations
- **Format**: Structured JSON for analysis

#### Metrics Collection
- **Blocked Requests**: Count of blocked requests by reason
- **Rate Limiting**: Rate limit violations by client
- **Threat Detection**: Security pattern matches
- **Authentication**: Success/failure rates

## Security Configuration

### Environment Variables

```bash
# Rate Limiting
RATE_LIMIT_REQUESTS_PER_MINUTE=100
RATE_LIMIT_BURST=20

# Security Settings
ENCRYPT_SENSITIVE_DATA=true
LOG_EMAIL_CONTENT=false
SECURITY_SCAN_ENABLED=true

# Redis (for rate limiting and API keys)
REDIS_URL=redis://localhost:6379/0
REDIS_PASSWORD=your-redis-password
```

### API Key Permissions

| Permission | Description | Services |
|------------|-------------|----------|
| `read` | Read-only access | All services |
| `write` | Write access to data | CLE, EIC, CM |
| `process_transactions` | Process payments | CLE only |
| `admin` | Administrative access | All services |

## Deployment Security

### 1. Container Security
- **Non-root users**: All services run as non-root
- **Read-only filesystems**: Where possible
- **Resource limits**: CPU and memory constraints
- **Secret management**: Azure Key Vault integration

### 2. Network Security
- **Internal networking**: Services communicate internally only
- **TLS termination**: Nginx handles SSL/TLS
- **Firewall rules**: Minimal port exposure
- **VPN access**: Production access through VPN only

### 3. Data Security
- **Encryption at rest**: Azure SQL Database encryption
- **Encryption in transit**: TLS 1.2+ for all communications
- **PII protection**: Minimal logging of sensitive data
- **Backup encryption**: Encrypted database backups

## Security Checklist

### Pre-Deployment
- [ ] Update all secrets in Azure Key Vault
- [ ] Configure API key rotation schedule
- [ ] Set up security monitoring alerts
- [ ] Review and test rate limits
- [ ] Validate SSL/TLS certificates

### Post-Deployment
- [ ] Verify all health checks pass
- [ ] Test authentication endpoints
- [ ] Validate rate limiting works
- [ ] Check security audit logs
- [ ] Run security scan

### Ongoing Maintenance
- [ ] Regular API key rotation (quarterly)
- [ ] Security log review (weekly)
- [ ] Update security patterns (monthly)
- [ ] Vulnerability scanning (continuous)
- [ ] Access review (monthly)

## Incident Response

### Security Events
1. **Blocked Requests**: Monitor for unusual blocking patterns
2. **Rate Limit Violations**: Investigate repeated violations
3. **Authentication Failures**: Track failed login attempts
4. **Suspicious Patterns**: Review threat detection logs

### Response Procedures
1. **Immediate**: Block suspicious IPs via Redis
2. **Investigation**: Review audit logs and metrics
3. **Mitigation**: Update security patterns if needed
4. **Recovery**: Reset affected API keys
5. **Documentation**: Update security procedures

## Compliance Considerations

### Data Protection
- **GDPR Compliance**: Minimal data collection, right to erasure
- **PCI DSS**: Secure handling of payment data
- **SOX Compliance**: Audit trails for financial transactions
- **Data Residency**: Azure region selection for compliance

### Audit Requirements
- **Authentication Logs**: All login attempts logged
- **Authorization Logs**: Permission checks logged
- **Data Access**: Transaction access logged
- **Administrative Actions**: API key management logged

## Security Contacts

- **Security Team**: security@company.com
- **Incident Response**: incident-response@company.com
- **Compliance**: compliance@company.com

---

For implementation details, see the individual security modules:
- `shared/security.py` - Core security middleware
- `shared/auth.py` - Authentication implementation
- `infrastructure/nginx/nginx.conf` - Network security
- `scripts/setup_security.py` - Security initialization