# services/eic/app/connectors/netsuite.py

import aiohttp
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import hmac
import hashlib
import base64
from urllib.parse import quote

from .base import BaseERPConnector, ERPCredentials, ERPTransactionLog
from shared.models import Invoice, MatchResult
from shared.exceptions import ERPConnectionError, ERPAuthenticationError, ERPDataError
from shared.logging_config import get_logger

logger = get_logger(__name__)

class NetSuiteConnector(BaseERPConnector):
    """NetSuite ERP connector using SuiteQL and RESTlets"""
    
    def __init__(self, credentials: ERPCredentials, client_config: Dict[str, Any] = None):
        super().__init__(credentials, client_config)
        
        # NetSuite specific configuration
        self.account_id = credentials.additional_params.get('account_id')
        self.consumer_key = credentials.client_id
        self.consumer_secret = credentials.client_secret
        self.token_id = credentials.additional_params.get('token_id')
        self.token_secret = credentials.additional_params.get('token_secret')
        
        self.base_url = f"https://{self.account_id}.suitetalk.api.netsuite.com"
        self.restlet_url = credentials.additional_params.get('restlet_url', '')
        
        if not all([self.account_id, self.consumer_key, self.consumer_secret, 
                   self.token_id, self.token_secret]):
            raise ERPAuthenticationError("Missing required NetSuite credentials")
    
    async def authenticate(self) -> bool:
        """NetSuite uses OAuth 1.0 - no separate auth step needed"""
        try:
            # Test authentication by making a simple API call
            test_result = await self.test_connection()
            if test_result.get('status') == 'success':
                self._access_token = "oauth1_token"  # Placeholder
                self._token_expires_at = datetime.utcnow() + timedelta(hours=24)
                logger.info("NetSuite authentication successful")
                return True
            else:
                raise ERPAuthenticationError("NetSuite authentication test failed")
                
        except Exception as e:
            logger.error(f"NetSuite authentication failed: {str(e)}")
            raise ERPAuthenticationError(f"NetSuite auth failed: {str(e)}")
    
    async def get_invoices(self, invoice_ids: List[str]) -> List[Invoice]:
        """Retrieve invoices from NetSuite using SuiteQL"""
        await self.ensure_authenticated()
        
        logger.info(f"Fetching {len(invoice_ids)} invoices from NetSuite")
        
        try:
            # Build SuiteQL query
            invoice_id_list = "', '".join(invoice_ids)
            query = f"""
                SELECT 
                    tranid as invoice_id,
                    entity as customer_id,
                    total as amount_due,
                    currency.symbol as currency,
                    status.name as status,
                    duedate
                FROM transaction 
                WHERE tranid IN ('{invoice_id_list}')
                AND recordtype = 'invoice'
            """
            
            # Execute SuiteQL query
            headers = self._build_oauth_headers('GET', f"{self.base_url}/services/rest/query/v1/suiteql")
            headers['Content-Type'] = 'application/json'
            headers['Prefer'] = 'transient'
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/services/rest/query/v1/suiteql",
                    params={'q': query},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        invoices = self._parse_netsuite_invoices(data.get('items', []))
                        logger.info(f"Successfully retrieved {len(invoices)} invoices from NetSuite")
                        return invoices
                    else:
                        error_text = await response.text()
                        raise ERPConnectionError(f"NetSuite query failed: {response.status} - {error_text}")
        
        except Exception as e:
            logger.error(f"Failed to retrieve invoices from NetSuite: {str(e)}")
            raise ERPDataError(f"NetSuite invoice retrieval failed: {str(e)}")
    
    async def post_application(self, match_result: MatchResult) -> Dict[str, Any]:
        """Post cash application to NetSuite using RESTlets"""
        await self.ensure_authenticated()
        
        logger.info(f"Posting cash application to NetSuite for transaction {match_result.transaction_id}")
        
        try:
            # Build cash application payload
            application_data = {
                "transactionId": match_result.transaction_id,
                "applications": []
            }
            
            for invoice_id, amount in match_result.matched_pairs.items():
                application_data["applications"].append({
                    "invoiceId": invoice_id,
                    "amountApplied": float(amount),
                    "discrepancyCode": match_result.discrepancy_code
                })
            
            # Handle unapplied amount if any
            if match_result.unapplied_amount > 0:
                application_data["unappliedAmount"] = float(match_result.unapplied_amount)
            
            # Post to NetSuite RESTlet
            headers = self._build_oauth_headers('POST', self.restlet_url)
            headers['Content-Type'] = 'application/json'
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.restlet_url,
                    json=application_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        
                        if result.get('success'):
                            logger.info(f"Cash application posted successfully to NetSuite: {result.get('transactionId')}")
                            return {
                                'success': True,
                                'erp_transaction_id': result.get('transactionId'),
                                'journal_entries': result.get('journalEntries', []),
                                'message': 'Cash application posted successfully'
                            }
                        else:
                            raise ERPDataError(f"NetSuite application failed: {result.get('error', 'Unknown error')}")
                    else:
                        error_text = await response.text()
                        raise ERPConnectionError(f"NetSuite RESTlet failed: {response.status} - {error_text}")
        
        except Exception as e:
            logger.error(f"Failed to post application to NetSuite: {str(e)}")
            raise ERPDataError(f"NetSuite application posting failed: {str(e)}")
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test NetSuite connection"""
        try:
            # Simple query to test connectivity
            query = "SELECT COUNT(*) as record_count FROM currency WHERE isinactive = 'F'"
            
            headers = self._build_oauth_headers('GET', f"{self.base_url}/services/rest/query/v1/suiteql")
            headers['Content-Type'] = 'application/json'
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/services/rest/query/v1/suiteql",
                    params={'q': query},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return {
                            'status': 'success',
                            'message': 'NetSuite connection successful',
                            'system_info': {
                                'account_id': self.account_id,
                                'api_version': 'v1'
                            }
                        }
                    else:
                        return {
                            'status': 'error',
                            'message': f'Connection test failed: {response.status}'
                        }
        
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Connection test error: {str(e)}'
            }
    
    def _build_oauth_headers(self, method: str, url: str) -> Dict[str, str]:
        """Build OAuth 1.0 headers for NetSuite API calls"""
        import time
        import uuid
        
        # OAuth parameters
        oauth_params = {
            'oauth_consumer_key': self.consumer_key,
            'oauth_token': self.token_id,
            'oauth_signature_method': 'HMAC-SHA256',
            'oauth_timestamp': str(int(time.time())),
            'oauth_nonce': str(uuid.uuid4()),
            'oauth_version': '1.0'
        }
        
        # Build signature base string
        param_string = '&'.join([f"{quote(k)}={quote(v)}" for k, v in sorted(oauth_params.items())])
        base_string = f"{method.upper()}&{quote(url)}&{quote(param_string)}"
        
        # Build signing key
        signing_key = f"{quote(self.consumer_secret)}&{quote(self.token_secret)}"
        
        # Generate signature
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha256).digest()
        ).decode()
        
        oauth_params['oauth_signature'] = signature
        
        # Build authorization header
        auth_header = 'OAuth ' + ', '.join([f'{k}="{v}"' for k, v in sorted(oauth_params.items())])
        
        return {'Authorization': auth_header}
    
    def _parse_netsuite_invoices(self, items: List[Dict[str, Any]]) -> List[Invoice]:
        """Parse NetSuite query results into Invoice objects"""
        invoices = []
        
        for item in items:
            try:
                # Map NetSuite status to our standard statuses
                ns_status = item.get('status', '').lower()
                if 'open' in ns_status or 'pending' in ns_status:
                    status = 'Open'
                elif 'paid' in ns_status or 'closed' in ns_status:
                    status = 'Closed'
                elif 'dispute' in ns_status:
                    status = 'Disputed'
                else:
                    status = 'Open'  # Default
                
                invoice = Invoice(
                    invoice_id=item.get('invoice_id', ''),
                    customer_id=str(item.get('customer_id', '')),
                    amount_due=Decimal(str(item.get('amount_due', 0))),
                    currency=item.get('currency', 'USD'),
                    status=status
                )
                invoices.append(invoice)
                
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"Failed to parse NetSuite invoice item: {item} - Error: {e}")
                continue
        
        return invoices