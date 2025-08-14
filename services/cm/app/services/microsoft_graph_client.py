# services/cm/app/services/microsoft_graph_client.py

import aiohttp
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import base64

from shared.logging_config import get_logger
from shared.exceptions import CommunicationError
from .email_service import EmailMessage, EmailRecipient

logger = get_logger(__name__)

class MicrosoftGraphClient:
    """Microsoft Graph API client for sending emails"""
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        
        self._access_token = None
        self._token_expires_at = None
        
        logger.info("Microsoft Graph client initialized")
    
    async def authenticate(self) -> bool:
        """Authenticate with Microsoft Graph using client credentials flow"""
        try:
            auth_data = {
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'scope': 'https://graph.microsoft.com/.default'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.token_url, data=auth_data) as response:
                    if response.status == 200:
                        token_data = await response.json()
                        self._access_token = token_data['access_token']
                        expires_in = token_data.get('expires_in', 3600)
                        self._token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)  # 5 min buffer
                        
                        logger.info("Microsoft Graph authentication successful")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Graph authentication failed: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Graph authentication error: {str(e)}")
            raise CommunicationError(f"Microsoft Graph authentication failed: {str(e)}")
    
    async def ensure_authenticated(self) -> bool:
        """Ensure valid authentication token"""
        if self._access_token is None or self._is_token_expired():
            return await self.authenticate()
        return True
    
    def _is_token_expired(self) -> bool:
        """Check if current token is expired"""
        if self._token_expires_at is None:
            return True
        return datetime.utcnow() >= self._token_expires_at
    
    async def send_email(self, email_message: EmailMessage) -> Dict[str, Any]:
        """Send email via Microsoft Graph"""
        await self.ensure_authenticated()
        
        try:
            # Build Graph API email payload
            graph_message = self._build_graph_message(email_message)
            
            # Send email
            headers = {
                'Authorization': f'Bearer {self._access_token}',
                'Content-Type': 'application/json'
            }
            
            send_url = f"{self.base_url}/users/{email_message.sender_email}/sendMail"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    send_url,
                    json=graph_message,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 202:  # Accepted
                        logger.info(f"Email sent successfully via Graph API")
                        return {
                            'success': True,
                            'message_id': f"graph_{int(datetime.utcnow().timestamp())}",
                            'provider': 'microsoft_graph',
                            'sent_at': datetime.utcnow().isoformat()
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Graph API send failed: {response.status} - {error_text}")
                        raise CommunicationError(f"Email send failed: {response.status} - {error_text}")
                        
        except Exception as e:
            logger.error(f"Failed to send email via Graph API: {str(e)}")
            raise CommunicationError(f"Graph API email send failed: {str(e)}")
    
    def _build_graph_message(self, email_message: EmailMessage) -> Dict[str, Any]:
        """Convert EmailMessage to Microsoft Graph message format"""
        
        # Build recipient lists
        to_recipients = []
        cc_recipients = []
        bcc_recipients = []
        
        for recipient in email_message.recipients:
            recipient_data = {
                'emailAddress': {
                    'address': recipient.email,
                    'name': recipient.name
                }
            }
            
            if recipient.type in ['customer', 'internal']:
                to_recipients.append(recipient_data)
            elif recipient.type == 'cc':
                cc_recipients.append(recipient_data)
            elif recipient.type == 'bcc':
                bcc_recipients.append(recipient_data)
        
        # Build message
        graph_message = {
            'message': {
                'subject': email_message.subject,
                'body': {
                    'contentType': 'HTML',
                    'content': email_message.body_html
                },
                'toRecipients': to_recipients,
                'importance': self._map_priority(email_message.priority),
                'from': {
                    'emailAddress': {
                        'address': email_message.sender_email,
                        'name': email_message.sender_name
                    }
                }
            }
        }
        
        # Add CC/BCC if present
        if cc_recipients:
            graph_message['message']['ccRecipients'] = cc_recipients
        
        if bcc_recipients:
            graph_message['message']['bccRecipients'] = bcc_recipients
        
        # Add attachments if present
        if email_message.attachments:
            attachments = []
            for attachment in email_message.attachments:
                attachments.append({
                    '@odata.type': '#microsoft.graph.fileAttachment',
                    'name': attachment['name'],
                    'contentType': attachment.get('content_type', 'application/octet-stream'),
                    'contentBytes': base64.b64encode(attachment['content']).decode()
                })
            graph_message['message']['attachments'] = attachments
        
        return graph_message
    
    def _map_priority(self, priority: str) -> str:
        """Map internal priority to Graph API importance"""
        priority_mapping = {
            'low': 'low',
            'normal': 'normal', 
            'high': 'high'
        }
        return priority_mapping.get(priority, 'normal')
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test Microsoft Graph connectivity"""
        try:
            await self.ensure_authenticated()
            
            # Simple API call to test connectivity
            headers = {'Authorization': f'Bearer {self._access_token}'}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/me", headers=headers) as response:
                    if response.status == 200:
                        return {
                            'status': 'success',
                            'message': 'Microsoft Graph connection successful',
                            'provider': 'microsoft_graph'
                        }
                    else:
                        return {
                            'status': 'error',
                            'message': f'Connection test failed: {response.status}',
                            'provider': 'microsoft_graph'
                        }
                        
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Connection test error: {str(e)}',
                'provider': 'microsoft_graph'
            }