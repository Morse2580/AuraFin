
# services/cm/app/services/slack_client.py

import aiohttp
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from shared.models import MatchResult
from shared.logging_config import get_logger
from shared.exceptions import CommunicationError

logger = get_logger(__name__)

class SlackClient:
    """Slack API client for sending notifications"""
    
    def __init__(self, bot_token: str, default_channel: str = None):
        self.bot_token = bot_token
        self.default_channel = default_channel or "#alerts"
        self.base_url = "https://slack.com/api"
        
        logger.info("Slack client initialized")
    
    async def send_internal_alert(self, 
                                match_result: MatchResult,
                                channel: str = None,
                                custom_message: str = None) -> Dict[str, Any]:
        """Send internal alert to Slack channel"""
        
        target_channel = channel or self.default_channel
        
        logger.info(f"Sending Slack alert for transaction {match_result.transaction_id} to {target_channel}")
        
        try:
            # Build Slack message
            if custom_message:
                message = custom_message
            else:
                message = self._build_alert_message(match_result)
            
            # Send to Slack
            result = await self._send_message(target_channel, message)
            
            logger.info(f"Slack alert sent successfully: {result.get('ts')}")
            
            return {
                'success': True,
                'message_id': result.get('ts'),
                'channel': target_channel,
                'provider': 'slack',
                'sent_at': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {str(e)}")
            raise CommunicationError(f"Slack alert failed: {str(e)}")
    
    async def send_batch_alerts(self, 
                              alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send multiple alerts to Slack"""
        
        logger.info(f"Sending batch of {len(alerts)} Slack alerts")
        
        results = {
            'successful': [],
            'failed': [],
            'total_processed': len(alerts)
        }
        
        for alert in alerts:
            try:
                result = await self.send_internal_alert(
                    alert['match_result'],
                    alert.get('channel'),
                    alert.get('custom_message')
                )
                results['successful'].append({
                    'transaction_id': alert['match_result'].transaction_id,
                    'result': result
                })
                
            except Exception as e:
                logger.error(f"Batch Slack alert failed: {str(e)}")
                results['failed'].append({
                    'transaction_id': alert.get('match_result', {}).get('transaction_id', 'unknown'),
                    'error': str(e)
                })
        
        return results
    
    async def send_summary_report(self, 
                                report_data: Dict[str, Any],
                                channel: str = None) -> Dict[str, Any]:
        """Send daily/weekly summary report to Slack"""
        
        target_channel = channel or self.default_channel
        
        logger.info(f"Sending summary report to {target_channel}")
        
        try:
            # Build summary message
            message = self._build_summary_message(report_data)
            
            result = await self._send_message(target_channel, message)
            
            return {
                'success': True,
                'message_id': result.get('ts'),
                'channel': target_channel,
                'provider': 'slack'
            }
            
        except Exception as e:
            logger.error(f"Failed to send summary report: {str(e)}")
            raise CommunicationError(f"Slack summary report failed: {str(e)}")
    
    async def _send_message(self, channel: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Send message to Slack channel"""
        
        headers = {
            'Authorization': f'Bearer {self.bot_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'channel': channel,
            **message
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat.postMessage",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    if result.get('ok'):
                        return result
                    else:
                        error = result.get('error', 'Unknown error')
                        raise CommunicationError(f"Slack API error: {error}")
                else:
                    error_text = await response.text()
                    raise CommunicationError(f"Slack API failed: {response.status} - {error_text}")
    
    def _build_alert_message(self, match_result: MatchResult) -> Dict[str, Any]:
        """Build formatted Slack alert message"""
        
        # Determine alert color based on severity
        color = self._get_alert_color(match_result.discrepancy_code)
        
        # Build alert blocks
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 CashAppAgent Alert: Human Review Required"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Transaction ID:*\n{match_result.transaction_id}"
                    },
                    {
                        "type": "mrkdwn", 
                        "text": f"*Status:*\n{match_result.status}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Discrepancy:*\n{match_result.discrepancy_code or 'Unknown'}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Unapplied Amount:*\n${match_result.unapplied_amount:.2f}"
                    }
                ]
            }
        ]
        
        # Add matched pairs if any
        if match_result.matched_pairs:
            matched_text = "\n".join([
                f"• {invoice_id}: ${amount:.2f}"
                for invoice_id, amount in match_result.matched_pairs.items()
            ])
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Matched Invoices:*\n{matched_text}"
                }
            })
        
        # Add log entry
        if match_result.log_entry:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Details:*\n```{match_result.log_entry}```"
                }
            })
        
        # Add action button
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Review in Dashboard"
                    },
                    "url": f"https://dashboard.company.com/transaction/{match_result.transaction_id}",
                    "action_id": "review_transaction"
                }
            ]
        })
        
        return {
            "text": f"CashAppAgent Alert: {match_result.transaction_id}",
            "blocks": blocks,
            "attachments": [
                {
                    "color": color,
                    "footer": "CashAppAgent",
                    "ts": int(datetime.utcnow().timestamp())
                }
            ]
        }
    
    def _build_summary_message(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build formatted summary report message"""
        
        period = report_data.get('period', 'Daily')
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text", 
                    "text": f"📊 CashAppAgent {period} Summary"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Transactions Processed:*\n{report_data.get('total_transactions', 0)}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Auto-Applied:*\n{report_data.get('auto_applied', 0)} ({report_data.get('auto_applied_percent', 0):.1f}%)"
                    },
                    {
                        "type": "mrkdwn", 
                        "text": f"*Manual Review:*\n{report_data.get('manual_review', 0)}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Total Amount:*\n${report_data.get('total_amount', 0):,.2f}"
                    }
                ]
            }
        ]
        
        # Add error breakdown if present
        if report_data.get('errors'):
            error_text = "\n".join([
                f"• {error_type}: {count}"
                for error_type, count in report_data['errors'].items()
            ])
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error Breakdown:*\n{error_text}"
                }
            })
        
        return {
            "text": f"CashAppAgent {period} Summary",
            "blocks": blocks
        }
    
    def _get_alert_color(self, discrepancy_code: str) -> str:
        """Get alert color based on discrepancy type"""
        color_mapping = {
            'INVALID_INVOICE': 'danger',
            'SUSPICIOUS_PAYMENT': 'danger', 
            'SHORT_PAYMENT': 'warning',
            'OVER_PAYMENT': 'good',
            'PARTIAL_MATCH': 'warning'
        }
        return color_mapping.get(discrepancy_code, 'warning')
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test Slack connectivity"""
        try:
            headers = {'Authorization': f'Bearer {self.bot_token}'}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/auth.test", headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        
                        if result.get('ok'):
                            return {
                                'status': 'success',
                                'message': 'Slack connection successful',
                                'provider': 'slack',
                                'team': result.get('team'),
                                'user': result.get('user')
                            }
                        else:
                            return {
                                'status': 'error',
                                'message': f"Slack auth failed: {result.get('error')}",
                                'provider': 'slack'
                            }
                    else:
                        return {
                            'status': 'error',
                            'message': f'Connection test failed: {response.status}',
                            'provider': 'slack'
                        }
                        
        except Exception as e:
            return {
                'status': 'error', 
                'message': f'Connection test error: {str(e)}',
                'provider': 'slack'
            }
