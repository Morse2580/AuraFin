# services/cm/app/services/email_service.py

import smtplib
import json
from typing import Dict, Any, List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from jinja2 import Environment, BaseLoader
import aiohttp
from dataclasses import dataclass

from shared.models import MatchResult
from shared.logging_config import get_logger
from shared.exceptions import CommunicationError
from .template_manager import EmailTemplateManager
from .microsoft_graph_client import MicrosoftGraphClient

logger = get_logger(__name__)

@dataclass
class EmailRecipient:
    """Email recipient information"""
    email: str
    name: str
    type: str  # 'customer', 'internal', 'cc', 'bcc'

@dataclass 
class EmailMessage:
    """Email message structure"""
    subject: str
    body_text: str
    body_html: str
    recipients: List[EmailRecipient]
    sender_email: str
    sender_name: str
    attachments: Optional[List[Dict[str, Any]]] = None
    priority: str = "normal"  # 'low', 'normal', 'high'
    
class EmailService:
    """Main email service orchestrating different providers"""
    
    def __init__(self, 
                 microsoft_graph_client: MicrosoftGraphClient,
                 template_manager: EmailTemplateManager,
                 settings: Dict[str, Any]):
        self.graph_client = microsoft_graph_client
        self.template_manager = template_manager
        self.settings = settings
        self.default_sender = settings.get('default_sender', {})
        
        logger.info("Email service initialized")
    
    async def send_clarification_email(self, 
                                     match_result: MatchResult,
                                     customer_info: Dict[str, Any]) -> Dict[str, Any]:
        """Send clarification email to customer for payment discrepancies"""
        
        logger.info(f"Preparing clarification email for transaction {match_result.transaction_id}")
        
        try:
            # Determine email template based on discrepancy type
            template_name = self._get_template_name(match_result.discrepancy_code)
            
            # Generate email content
            email_message = await self._generate_clarification_email(
                match_result, customer_info, template_name
            )
            
            # Send email via Microsoft Graph
            result = await self.graph_client.send_email(email_message)
            
            logger.info(f"Clarification email sent successfully: {result.get('message_id')}")
            
            return {
                'success': True,
                'message_id': result.get('message_id'),
                'recipient': customer_info.get('email'),
                'template_used': template_name,
                'sent_at': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to send clarification email: {str(e)}")
            raise CommunicationError(f"Clarification email failed: {str(e)}")
    
    async def send_internal_alert(self, 
                                match_result: MatchResult,
                                alert_config: Dict[str, Any]) -> Dict[str, Any]:
        """Send internal alert for transactions requiring review"""
        
        logger.info(f"Preparing internal alert for transaction {match_result.transaction_id}")
        
        try:
            # Generate alert email
            email_message = await self._generate_internal_alert_email(
                match_result, alert_config
            )
            
            # Send to internal team
            result = await self.graph_client.send_email(email_message)
            
            logger.info(f"Internal alert sent successfully: {result.get('message_id')}")
            
            return {
                'success': True,
                'message_id': result.get('message_id'),
                'alert_type': 'email',
                'sent_at': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to send internal alert: {str(e)}")
            raise CommunicationError(f"Internal alert email failed: {str(e)}")
    
    async def send_batch_notifications(self, 
                                     notifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send multiple notifications in batch"""
        
        logger.info(f"Processing batch of {len(notifications)} notifications")
        
        results = {
            'successful': [],
            'failed': [],
            'total_processed': len(notifications)
        }
        
        for notification in notifications:
            try:
                if notification['type'] == 'clarification':
                    result = await self.send_clarification_email(
                        notification['match_result'],
                        notification['customer_info']
                    )
                    results['successful'].append({
                        'transaction_id': notification['match_result'].transaction_id,
                        'result': result
                    })
                    
                elif notification['type'] == 'internal_alert':
                    result = await self.send_internal_alert(
                        notification['match_result'],
                        notification['alert_config']
                    )
                    results['successful'].append({
                        'transaction_id': notification['match_result'].transaction_id,
                        'result': result
                    })
                    
            except Exception as e:
                logger.error(f"Batch notification failed for transaction {notification.get('transaction_id', 'unknown')}: {str(e)}")
                results['failed'].append({
                    'transaction_id': notification.get('transaction_id', 'unknown'),
                    'error': str(e)
                })
        
        logger.info(f"Batch processing completed: {len(results['successful'])} successful, {len(results['failed'])} failed")
        
        return results
    
    async def _generate_clarification_email(self,
                                          match_result: MatchResult,
                                          customer_info: Dict[str, Any],
                                          template_name: str) -> EmailMessage:
        """Generate clarification email content"""
        
        # Prepare template context
        context = {
            'customer_name': customer_info.get('name', 'Valued Customer'),
            'payment_amount': sum(match_result.matched_pairs.values()) if match_result.matched_pairs else 0,
            'currency': 'USD',  # Should be dynamic
            'transaction_id': match_result.transaction_id,
            'matched_invoices': list(match_result.matched_pairs.keys()),
            'discrepancy_code': match_result.discrepancy_code,
            'unapplied_amount': float(match_result.unapplied_amount),
            'company_name': self.settings.get('company_name', 'Your Company'),
            'sender_name': self.default_sender.get('name', 'Accounts Receivable Team'),
            'contact_email': self.default_sender.get('email', 'ar@company.com'),
            'portal_url': self.settings.get('customer_portal_url', '#'),
            'date': datetime.now().strftime('%B %d, %Y')
        }
        
        # Handle specific discrepancy types
        if match_result.discrepancy_code == 'SHORT_PAYMENT':
            context['shortage_amount'] = self._calculate_shortage_amount(match_result)
            context['payment_instruction'] = "Please remit the remaining balance or contact us to discuss payment arrangements."
        
        elif match_result.discrepancy_code == 'OVER_PAYMENT':
            context['overpayment_amount'] = float(match_result.unapplied_amount)
            context['payment_instruction'] = "We have applied your payment and credited the overpayment to your account. Please let us know if you'd like a refund or to apply it to future invoices."
        
        # Generate email content from template
        email_content = await self.template_manager.render_template(template_name, context)
        
        # Create email message
        recipients = [EmailRecipient(
            email=customer_info['email'],
            name=customer_info.get('name', ''),
            type='customer'
        )]
        
        # Add CC recipients if configured
        if self.settings.get('cc_ar_team'):
            recipients.append(EmailRecipient(
                email=self.default_sender['email'],
                name=self.default_sender['name'],
                type='cc'
            ))
        
        return EmailMessage(
            subject=email_content['subject'],
            body_text=email_content['body_text'],
            body_html=email_content['body_html'],
            recipients=recipients,
            sender_email=self.default_sender['email'],
            sender_name=self.default_sender['name'],
            priority='normal'
        )
    
    async def _generate_internal_alert_email(self,
                                           match_result: MatchResult,
                                           alert_config: Dict[str, Any]) -> EmailMessage:
        """Generate internal alert email content"""
        
        # Prepare alert context
        context = {
            'transaction_id': match_result.transaction_id,
            'status': match_result.status,
            'discrepancy_code': match_result.discrepancy_code or 'UNKNOWN',
            'log_entry': match_result.log_entry,
            'matched_pairs': match_result.matched_pairs,
            'unapplied_amount': float(match_result.unapplied_amount),
            'dashboard_url': f"{self.settings.get('dashboard_url', '#')}/transaction/{match_result.transaction_id}",
            'priority': self._determine_alert_priority(match_result),
            'date': datetime.now().strftime('%B %d, %Y at %I:%M %p'),
            'system_name': 'CashAppAgent'
        }
        
        # Generate alert content
        email_content = await self.template_manager.render_template('internal_alert', context)
        
        # Create recipient list
        recipients = []
        for email in alert_config.get('recipients', []):
            recipients.append(EmailRecipient(
                email=email['email'],
                name=email.get('name', ''),
                type='internal'
            ))
        
        return EmailMessage(
            subject=email_content['subject'],
            body_text=email_content['body_text'],
            body_html=email_content['body_html'],
            recipients=recipients,
            sender_email=self.default_sender['email'],
            sender_name='CashAppAgent System',
            priority=context['priority']
        )
    
    def _get_template_name(self, discrepancy_code: str) -> str:
        """Get template name based on discrepancy code"""
        template_mapping = {
            'SHORT_PAYMENT': 'short_payment_clarification',
            'OVER_PAYMENT': 'overpayment_clarification',
            'INVALID_INVOICE': 'invalid_invoice_clarification',
            'PARTIAL_MATCH': 'partial_match_clarification'
        }
        return template_mapping.get(discrepancy_code, 'general_clarification')
    
    def _calculate_shortage_amount(self, match_result: MatchResult) -> float:
        """Calculate shortage amount for short payments"""
        # This would integrate with ERP to get actual invoice amounts
        # For now, simplified calculation
        return 0.0  # Placeholder
    
    def _determine_alert_priority(self, match_result: MatchResult) -> str:
        """Determine email priority based on match result"""
        if match_result.status == 'RequiresReview':
            if match_result.discrepancy_code in ['INVALID_INVOICE', 'SUSPICIOUS_PAYMENT']:
                return 'high'
            else:
                return 'normal'
        return 'low'

# services/cm/app/services/template_manager.py

from typing import Dict, Any
from jinja2 import Environment, DictLoader
import json
import os
from pathlib import Path

from shared.logging_config import get_logger

logger = get_logger(__name__)

class EmailTemplateManager:
    """Manages email templates with Jinja2 rendering"""
    
    def __init__(self, templates_dir: str = None):
        self.templates_dir = templates_dir or "templates"
        self.templates = {}
        self.jinja_env = None
        
        # Load templates
        self._load_templates()
        self._initialize_jinja()
        
        logger.info(f"Email template manager initialized with {len(self.templates)} templates")
    
    def _load_templates(self):
        """Load email templates from files and defaults"""
        
        # Default templates (embedded for reliability)
        default_templates = {
            'short_payment_clarification': {
                'subject': "Regarding your recent payment - {{ customer_name }}",
                'body_text': """Dear {{ customer_name }},

Thank you for your recent payment of ${{ "%.2f"|format(payment_amount) }}.

We have applied your payment to the following invoice(s):
{% for invoice_id in matched_invoices %}
- {{ invoice_id }}
{% endfor %}

However, there appears to be a shortage of ${{ "%.2f"|format(shortage_amount) }}. {{ payment_instruction }}

If you have any questions or believe this is an error, please contact our Accounts Receivable team at {{ contact_email }}.

Thank you for your business.

Best regards,
{{ sender_name }}
{{ company_name }}""",
                'body_html': """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Payment Clarification Required</title>
    <style>
        .container { max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif; }
        .header { background-color: #f8f9fa; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .invoice-list { background-color: #f1f3f4; padding: 10px; margin: 10px 0; }
        .footer { background-color: #f8f9fa; padding: 15px; text-align: center; font-size: 12px; }
        .amount { font-weight: bold; color: #d93025; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Payment Clarification Required</h2>
        </div>
        <div class="content">
            <p>Dear {{ customer_name }},</p>
            
            <p>Thank you for your recent payment of <span class="amount">${{ "%.2f"|format(payment_amount) }}</span>.</p>
            
            <p>We have applied your payment to the following invoice(s):</p>
            <div class="invoice-list">
                <ul>
                {% for invoice_id in matched_invoices %}
                    <li>{{ invoice_id }}</li>
                {% endfor %}
                </ul>
            </div>
            
            <p>However, there appears to be a shortage of <span class="amount">${{ "%.2f"|format(shortage_amount) }}</span>.</p>
            
            <p>{{ payment_instruction }}</p>
            
            <p>If you have any questions or believe this is an error, please contact our Accounts Receivable team at <a href="mailto:{{ contact_email }}">{{ contact_email }}</a>.</p>
            
            <p>You can also view your account status in our <a href="{{ portal_url }}">customer portal</a>.</p>
        </div>
        <div class="footer">
            <p>Best regards,<br>
            {{ sender_name }}<br>
            {{ company_name }}</p>
            <p><em>This is an automated message from our cash application system.</em></p>
        </div>
    </div>
</body>
</html>"""
            },
            
            'overpayment_clarification': {
                'subject': "Overpayment Credit Applied - {{ customer_name }}",
                'body_text': """Dear {{ customer_name }},

Thank you for your recent payment of ${{ "%.2f"|format(payment_amount) }}.

We have applied your payment to the following invoice(s):
{% for invoice_id in matched_invoices %}
- {{ invoice_id }}
{% endfor %}

Your payment included an overpayment of ${{ "%.2f"|format(overpayment_amount) }}, which has been credited to your account.

{{ payment_instruction }}

If you have any questions, please contact our Accounts Receivable team at {{ contact_email }}.

Thank you for your business.

Best regards,
{{ sender_name }}
{{ company_name }}""",
                'body_html': """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Overpayment Credit Applied</title>
    <style>
        .container { max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif; }
        .header { background-color: #e8f5e8; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .invoice-list { background-color: #f1f3f4; padding: 10px; margin: 10px 0; }
        .footer { background-color: #f8f9fa; padding: 15px; text-align: center; font-size: 12px; }
        .amount { font-weight: bold; color: #137333; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Overpayment Credit Applied</h2>
        </div>
        <div class="content">
            <p>Dear {{ customer_name }},</p>
            
            <p>Thank you for your recent payment of <span class="amount">${{ "%.2f"|format(payment_amount) }}</span>.</p>
            
            <p>We have applied your payment to the following invoice(s):</p>
            <div class="invoice-list">
                <ul>
                {% for invoice_id in matched_invoices %}
                    <li>{{ invoice_id }}</li>
                {% endfor %}
                </ul>
            </div>
            
            <p>Your payment included an overpayment of <span class="amount">${{ "%.2f"|format(overpayment_amount) }}</span>, which has been credited to your account.</p>
            
            <p>{{ payment_instruction }}</p>
            
            <p>If you have any questions, please contact our Accounts Receivable team at <a href="mailto:{{ contact_email }}">{{ contact_email }}</a>.</p>
        </div>
        <div class="footer">
            <p>Best regards,<br>
            {{ sender_name }}<br>
            {{ company_name }}</p>
        </div>
    </div>
</body>
</html>"""
            },
            
            'internal_alert': {
                'subject': "🚨 CashAppAgent: Human Review Required - {{ transaction_id }}",
                'body_text': """CashAppAgent Alert - Human Review Required

Transaction ID: {{ transaction_id }}
Status: {{ status }}
Discrepancy Code: {{ discrepancy_code }}
Priority: {{ priority|upper }}

Details:
{{ log_entry }}

Matched Pairs:
{% for invoice_id, amount in matched_pairs.items() %}
- {{ invoice_id }}: ${{ "%.2f"|format(amount) }}
{% endfor %}

Unapplied Amount: ${{ "%.2f"|format(unapplied_amount) }}

Action Required:
Please review this transaction in the dashboard: {{ dashboard_url }}

Generated on: {{ date }}
System: {{ system_name }}""",
                'body_html': """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>CashAppAgent Alert</title>
    <style>
        .container { max-width: 600px; margin: 0 auto; font-family: 'Courier New', monospace; }
        .header { background-color: #fce8e6; padding: 20px; text-align: center; border-left: 4px solid #d93025; }
        .content { padding: 20px; background-color: #f8f9fa; }
        .detail-row { margin: 5px 0; }
        .label { font-weight: bold; display: inline-block; width: 150px; }
        .value { color: #1a73e8; }
        .high-priority { color: #d93025; font-weight: bold; }
        .button { display: inline-block; background-color: #1a73e8; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; margin: 10px 0; }
        .footer { text-align: center; font-size: 11px; color: #5f6368; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🚨 CashAppAgent Alert</h2>
            <p><strong>Human Review Required</strong></p>
        </div>
        <div class="content">
            <div class="detail-row">
                <span class="label">Transaction ID:</span>
                <span class="value">{{ transaction_id }}</span>
            </div>
            <div class="detail-row">
                <span class="label">Status:</span>
                <span class="value">{{ status }}</span>
            </div>
            <div class="detail-row">
                <span class="label">Discrepancy:</span>
                <span class="value">{{ discrepancy_code }}</span>
            </div>
            <div class="detail-row">
                <span class="label">Priority:</span>
                <span class="{% if priority == 'high' %}high-priority{% else %}value{% endif %}">{{ priority|upper }}</span>
            </div>
            
            <h3>Details:</h3>
            <p style="background: white; padding: 10px; border-left: 3px solid #1a73e8;">{{ log_entry }}</p>
            
            <h3>Matched Pairs:</h3>
            <ul>
            {% for invoice_id, amount in matched_pairs.items() %}
                <li>{{ invoice_id }}: <strong>${{ "%.2f"|format(amount) }}</strong></li>
            {% endfor %}
            </ul>
            
            <div class="detail-row">
                <span class="label">Unapplied Amount:</span>
                <span class="value"><strong>${{ "%.2f"|format(unapplied_amount) }}</strong></span>
            </div>
            
            <p><a href="{{ dashboard_url }}" class="button">Review in Dashboard</a></p>
            
            <div class="footer">
                <p>Generated on {{ date }} by {{ system_name }}</p>
                <p><em>This is an automated alert from the autonomous cash application system.</em></p>
            </div>
        </div>
    </div>
</body>
</html>"""
            }
        }
        
        # Load default templates
        self.templates.update(default_templates)
        
        # Try to load custom templates from files if directory exists
        if os.path.exists(self.templates_dir):
            self._load_templates_from_files()
    
    def _load_templates_from_files(self):
        """Load templates from JSON files"""
        try:
            templates_path = Path(self.templates_dir)
            
            for template_file in templates_path.glob("*.json"):
                try:
                    with open(template_file, 'r', encoding='utf-8') as f:
                        template_data = json.load(f)
                        template_name = template_file.stem
                        self.templates[template_name] = template_data
                        logger.debug(f"Loaded template: {template_name}")
                        
                except Exception as e:
                    logger.warning(f"Failed to load template {template_file}: {str(e)}")
                    
        except Exception as e:
            logger.warning(f"Failed to load templates from directory {self.templates_dir}: {str(e)}")
    
    def _initialize_jinja(self):
        """Initialize Jinja2 environment with loaded templates"""
        try:
            # Flatten templates for Jinja2 DictLoader
            template_dict = {}
            
            for template_name, template_data in self.templates.items():
                # Add all template parts with prefixed names
                template_dict[f"{template_name}_subject"] = template_data['subject']
                template_dict[f"{template_name}_text"] = template_data['body_text'] 
                template_dict[f"{template_name}_html"] = template_data['body_html']
            
            # Create Jinja2 environment
            self.jinja_env = Environment(
                loader=DictLoader(template_dict),
                autoescape=True,
                trim_blocks=True,
                lstrip_blocks=True
            )
            
            logger.info("Jinja2 template environment initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Jinja2 environment: {str(e)}")
            raise
    
    async def render_template(self, template_name: str, context: Dict[str, Any]) -> Dict[str, str]:
        """Render email template with given context"""
        
        if template_name not in self.templates:
            logger.warning(f"Template '{template_name}' not found, using default")
            template_name = 'general_clarification'
            
            # Fallback template if general_clarification doesn't exist
            if template_name not in self.templates:
                return self._create_fallback_email(context)
        
        try:
            # Render all template parts
            subject_template = self.jinja_env.get_template(f"{template_name}_subject")
            text_template = self.jinja_env.get_template(f"{template_name}_text")
            html_template = self.jinja_env.get_template(f"{template_name}_html")
            
            rendered_content = {
                'subject': subject_template.render(**context),
                'body_text': text_template.render(**context),
                'body_html': html_template.render(**context)
            }
            
            logger.debug(f"Successfully rendered template: {template_name}")
            return rendered_content
            
        except Exception as e:
            logger.error(f"Failed to render template {template_name}: {str(e)}")
            return self._create_fallback_email(context)
    
    def _create_fallback_email(self, context: Dict[str, Any]) -> Dict[str, str]:
        """Create a basic fallback email when template rendering fails"""
        
        return {
            'subject': f"Payment Processing Notification - Transaction {context.get('transaction_id', 'N/A')}",
            'body_text': f"""
Dear Customer,

We have processed your recent payment for transaction {context.get('transaction_id', 'N/A')}.

Please contact our Accounts Receivable team if you have any questions.

Best regards,
{context.get('company_name', 'Accounts Receivable Team')}
            """.strip(),
            'body_html': f"""
<html>
<body>
    <p>Dear Customer,</p>
    <p>We have processed your recent payment for transaction <strong>{context.get('transaction_id', 'N/A')}</strong>.</p>
    <p>Please contact our Accounts Receivable team if you have any questions.</p>
    <p>Best regards,<br>{context.get('company_name', 'Accounts Receivable Team')}</p>
</body>
</html>
            """.strip()
        }
    
    def list_templates(self) -> List[str]:
        """List all available templates"""
        return list(self.templates.keys())
    
    def add_template(self, template_name: str, template_data: Dict[str, str]) -> bool:
        """Add or update a template"""
        try:
            required_fields = ['subject', 'body_text', 'body_html']
            
            if not all(field in template_data for field in required_fields):
                logger.error(f"Template {template_name} missing required fields: {required_fields}")
                return False
            
            self.templates[template_name] = template_data
            
            # Reinitialize Jinja2 environment with new template
            self._initialize_jinja()
            
            logger.info(f"Template {template_name} added successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add template {template_name}: {str(e)}")
            return False
