# services/cm/app/services/template_manager.py

from typing import Dict, Any, Optional, List
from jinja2 import Environment, DictLoader, BaseLoader, meta
from datetime import datetime
import json
import os

from shared.logging_config import get_logger
from shared.exceptions import CommunicationError

logger = get_logger(__name__)

class EmailTemplateManager:
    """Manager for email templates used in communications"""
    
    def __init__(self):
        self.env = Environment(loader=DictLoader(self._get_default_templates()))
        self._load_custom_templates()
    
    def _get_default_templates(self) -> Dict[str, str]:
        """Get default email templates"""
        return {
            'payment_reminder': """
Dear {{ recipient_name or 'Valued Partner' }},

We hope this email finds you well. This is a friendly reminder regarding the following outstanding invoice(s):

{% for match in matches %}
Invoice ID: {{ match.invoice_id }}
Amount: ${{ match.amount or 'N/A' }}
Due Date: {{ match.due_date or 'N/A' }}
Days Overdue: {{ match.days_overdue or 0 }}
{% endfor %}

Please remit payment at your earliest convenience. If you have already processed payment, please disregard this notice.

For questions regarding this invoice, please contact our accounts receivable department.

Best regards,
{{ sender_name or 'Accounts Receivable Team' }}
{{ company_name or 'CashUp Agent' }}
            """,
            
            'invoice_matched': """
Dear {{ recipient_name or 'Team' }},

We have successfully matched the following invoices in our system:

{% for match in matches %}
Invoice ID: {{ match.invoice_id }}
Confidence Score: {{ (match.confidence_score * 100) | round(1) }}%
Status: {{ match.status | title }}
Processing Date: {{ match.created_at.strftime('%Y-%m-%d %H:%M:%S') if match.created_at else 'N/A' }}
{% endfor %}

Total Matches: {{ matches | length }}
Processing Summary:
- High Confidence (>90%): {{ matches | selectattr('confidence_score', '>', 0.9) | list | length }}
- Medium Confidence (70-90%): {{ matches | selectattr('confidence_score', '>', 0.7) | selectattr('confidence_score', '<=', 0.9) | list | length }}
- Low Confidence (<70%): {{ matches | selectattr('confidence_score', '<=', 0.7) | list | length }}

Best regards,
CashUp Agent System
            """,
            
            'error_notification': """
Dear {{ recipient_name or 'Administrator' }},

An error occurred in the CashUp Agent system:

Error Type: {{ error_type or 'Unknown Error' }}
Service: {{ service_name or 'Unknown Service' }}
Timestamp: {{ timestamp.strftime('%Y-%m-%d %H:%M:%S UTC') if timestamp else 'N/A' }}
Correlation ID: {{ correlation_id or 'N/A' }}

Error Details:
{{ error_message or 'No additional details available.' }}

{% if suggested_actions %}
Suggested Actions:
{% for action in suggested_actions %}
- {{ action }}
{% endfor %}
{% endif %}

Please investigate this issue promptly.

CashUp Agent Monitoring System
            """,
            
            'processing_complete': """
Dear {{ recipient_name or 'Team' }},

Document processing has been completed successfully:

Processing Summary:
- Documents Processed: {{ document_count or 0 }}
- Processing Duration: {{ processing_duration_ms or 0 }}ms
- Tier Used: {{ processing_tier or 'Unknown' }}
- Cost Estimate: ${{ cost_estimate or 0 }}

{% if invoice_ids %}
Extracted Invoice IDs:
{% for invoice_id in invoice_ids %}
- {{ invoice_id }}
{% endfor %}
{% endif %}

Confidence Score: {{ (confidence_score * 100) | round(1) if confidence_score else 'N/A' }}%

Best regards,
CashUp Agent Processing System
            """
        }
    
    def _load_custom_templates(self):
        """Load custom templates from configuration"""
        try:
            # Try to load custom templates from environment or config
            custom_templates_path = os.getenv('EMAIL_TEMPLATES_PATH')
            if custom_templates_path and os.path.exists(custom_templates_path):
                # Load custom templates from file
                with open(custom_templates_path, 'r') as f:
                    custom_templates = json.load(f)
                
                # Merge with default templates
                all_templates = {**self._get_default_templates(), **custom_templates}
                self.env = Environment(loader=DictLoader(all_templates))
                logger.info(f"Loaded custom email templates from {custom_templates_path}")
            
        except Exception as e:
            logger.warning(f"Failed to load custom templates: {e}, using defaults")
    
    def render_template(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render an email template with the given context"""
        try:
            template = self.env.get_template(template_name)
            rendered = template.render(**context)
            
            logger.debug(f"Successfully rendered template '{template_name}'")
            return rendered.strip()
            
        except Exception as e:
            logger.error(f"Failed to render template '{template_name}': {e}")
            raise CommunicationError(f"Template rendering failed: {e}")
    
    def get_available_templates(self) -> List[str]:
        """Get list of available template names"""
        return list(self.env.loader.mapping.keys())
    
    def validate_template_context(self, template_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that the context contains required variables for the template"""
        try:
            template_source = self.env.loader.get_source(self.env, template_name)
            template_ast = self.env.parse(template_source[0])
            required_vars = meta.find_undeclared_variables(template_ast)
            
            missing_vars = required_vars - set(context.keys())
            if missing_vars:
                logger.warning(f"Template '{template_name}' missing context variables: {missing_vars}")
            
            return {
                'required_variables': list(required_vars),
                'missing_variables': list(missing_vars),
                'provided_variables': list(context.keys()),
                'is_valid': len(missing_vars) == 0
            }
            
        except Exception as e:
            logger.error(f"Failed to validate template context for '{template_name}': {e}")
            return {
                'required_variables': [],
                'missing_variables': [],
                'provided_variables': list(context.keys()),
                'is_valid': False,
                'error': str(e)
            }
    
    def render_with_fallback(self, template_name: str, context: Dict[str, Any], 
                           fallback_template: Optional[str] = None) -> str:
        """Render template with fallback option"""
        try:
            return self.render_template(template_name, context)
        except Exception as e:
            logger.warning(f"Primary template '{template_name}' failed, trying fallback: {e}")
            
            if fallback_template:
                try:
                    return self.render_template(fallback_template, context)
                except Exception as fallback_error:
                    logger.error(f"Fallback template also failed: {fallback_error}")
            
            # Last resort: simple text template
            return self._create_simple_fallback(template_name, context)
    
    def _create_simple_fallback(self, template_name: str, context: Dict[str, Any]) -> str:
        """Create a simple fallback email when templates fail"""
        return f"""
Email Template: {template_name}

Context Data:
{json.dumps(context, indent=2, default=str)}

This is a fallback email generated when template rendering failed.
Please check the email template configuration.

CashUp Agent System
        """.strip()