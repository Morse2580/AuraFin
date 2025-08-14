# services/cm/app/models/communication_models.py

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, EmailStr

from shared.models import MatchResult

class ClarificationEmailRequest(BaseModel):
    """Request for sending clarification email to customer"""
    match_result: MatchResult
    customer_info: Dict[str, Any] = Field(..., description="Customer contact information including email")
    template_override: Optional[str] = None
    custom_context: Optional[Dict[str, Any]] = {}

class InternalAlertRequest(BaseModel):
    """Request for sending internal alert"""
    match_result: MatchResult
    alert_type: str = Field(..., regex="^(email|slack|both)$")
    alert_config: Dict[str, Any] = Field(..., description="Alert configuration including recipients")
    priority: Optional[str] = Field("normal", regex="^(low|normal|high)$")

class BatchNotificationRequest(BaseModel):
    """Request for batch notification processing"""
    notifications: List[Dict[str, Any]] = Field(..., min_items=1, max_items=100)
    async_processing: bool = False

class CommunicationResponse(BaseModel):
    """Standard communication response"""
    success: bool
    message_id: Optional[str] = None
    provider: str
    processing_time_ms: int
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = {}

# services/cm/app/config.py

from typing import Optional, Dict, Any, List
from pydantic_settings import BaseSettings

class CMSettings(BaseSettings):
    """Communication Module configuration"""
    
    # Service Configuration
    SERVICE_NAME: str = "cm"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # API Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8004
    WORKERS: int = 4
    
    # Azure/Microsoft Graph Configuration
    AZURE_TENANT_ID: str
    AZURE_CLIENT_ID: str
    AZURE_CLIENT_SECRET: str
    
    # Email Configuration
    DEFAULT_SENDER_EMAIL: str
    DEFAULT_SENDER_NAME: str = "Accounts Receivable Team"
    COMPANY_NAME: str = "Your Company"
    CC_AR_TEAM: bool = True
    
    # Slack Configuration
    SLACK_BOT_TOKEN: Optional[str] = None
    SLACK_DEFAULT_CHANNEL: str = "#cashapp-alerts"
    SLACK_SIGNING_SECRET: Optional[str] = None
    
    # Template Configuration
    TEMPLATES_DIR: str = "templates"
    CUSTOM_TEMPLATES_ENABLED: bool = True
    
    # Communication Limits
    MAX_EMAIL_BATCH_SIZE: int = 50
    MAX_SLACK_BATCH_SIZE: int = 100
    EMAIL_TIMEOUT_SECONDS: int = 30
    SLACK_TIMEOUT_SECONDS: int = 30
    
    # Customer Portal Configuration
    CUSTOMER_PORTAL_URL: str = "https://portal.company.com"
    DASHBOARD_URL: str = "https://dashboard.company.com"
    
    # Retry Configuration
    MAX_RETRY_ATTEMPTS: int = 3
    RETRY_BACKOFF_SECONDS: float = 1.0
    
    # Security Configuration
    ENCRYPT_SENSITIVE_DATA: bool = True
    LOG_EMAIL_CONTENT: bool = False  # For privacy compliance
    
    # Monitoring Configuration
    METRICS_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL: int = 60
    
    class Config:
        env_file = ".env"
        case_sensitive = True
