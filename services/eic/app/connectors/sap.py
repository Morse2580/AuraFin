

# services/eic/app/connectors/sap.py

from typing import List, Dict, Any, Optional
import aiohttp
import json
from datetime import datetime, timedelta

from .base import BaseERPConnector, ERPCredentials
from shared.models import Invoice, MatchResult
from shared.exceptions import ERPConnectionError, ERPAuthenticationError, ERPDataError
from shared.logging_config import get_logger

logger = get_logger(__name__)

class SAPConnector(BaseERPConnector):
    """SAP ERP connector using OData APIs"""
    
    def __init__(self, credentials: ERPCredentials, client_config: Dict[str, Any] = None):
        super().__init__(credentials, client_config)
        
        self.base_url = credentials.additional_params.get('base_url', '')
        self.username = credentials.client_id
        self.password = credentials.client_secret
        self.client_id = credentials.additional_params.get('oauth_client_id', '')
        
        if not self.base_url:
            raise ERPAuthenticationError("SAP base URL is required")
    
    async def authenticate(self) -> bool:
        """Authenticate with SAP using OAuth 2.0 or Basic Auth"""
        try:
            if self.client_id:
                # OAuth 2.0 flow
                return await self._oauth_authenticate()
            else:
                # Basic authentication
                return await self._basic_authenticate()
                
        except Exception as e:
            logger.error(f"SAP authentication failed: {str(e)}")
            raise ERPAuthenticationError(f"SAP auth failed: {str(e)}")
    
    async def _oauth_authenticate(self) -> bool:
        """OAuth 2.0 authentication flow"""
        token_url = f"{self.base_url}/oauth/token"
        
        auth_data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.password,
            'scope': 'read write'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=auth_data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    self._access_token = token_data['access_token']
                    expires_in = token_data.get('expires_in', 3600)
                    self._token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                    logger.info("SAP OAuth authentication successful")
                    return True
                else:
                    error_text = await response.text()
                    raise ERPAuthenticationError(f"OAuth failed: {response.status} - {error_text}")
    
    async def _basic_authenticate(self) -> bool:
        """Basic authentication test"""
        test_result = await self.test_connection()
        if test_result.get('status') == 'success':
            self._access_token = f"{self.username}:{self.password}"
            self._token_expires_at = datetime.utcnow() + timedelta(hours=24)
            logger.info("SAP Basic authentication successful")
            return True
        else:
            raise ERPAuthenticationError("SAP Basic authentication failed")
    
    async def get_invoices(self, invoice_ids: List[str]) -> List[Invoice]:
        """Retrieve invoices from SAP using OData"""
        await self.ensure_authenticated()
        
        logger.info(f"Fetching {len(invoice_ids)} invoices from SAP")
        
        try:
            invoices = []
            
            # SAP OData typically requires individual queries or batch requests
            for invoice_id in invoice_ids:
                invoice = await self._get_single_invoice(invoice_id)
                if invoice:
                    invoices.append(invoice)
            
            logger.info(f"Successfully retrieved {len(invoices)} invoices from SAP")
            return invoices
            
        except Exception as e:
            logger.error(f"Failed to retrieve invoices from SAP: {str(e)}")
            raise ERPDataError(f"SAP invoice retrieval failed: {str(e)}")
    
    async def _get_single_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """Get a single invoice from SAP"""
        try:
            # Build OData query
            odata_url = f"{self.base_url}/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV/A_BillingDocument('{invoice_id}')"
            
            headers = self._build_headers()
            
            async with aiohttp.ClientSession() as session:
                async with session.get(odata_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_sap_invoice(data.get('d', {}))
                    elif response.status == 404:
                        logger.warning(f"Invoice {invoice_id} not found in SAP")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"SAP query failed for {invoice_id}: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"Failed to retrieve invoice {invoice_id} from SAP: {str(e)}")
            return None
    
    async def post_application(self, match_result: MatchResult) -> Dict[str, Any]:
        """Post cash application to SAP"""
        await self.ensure_authenticated()
        
        logger.info(f"Posting cash application to SAP for transaction {match_result.transaction_id}")
        
        try:
            # Build payment application payload for SAP
            application_payload = {
                "DocumentType": "DZ",  # Payment document type
                "CompanyCode": self.client_config.get('company_code', '1000'),
                "PostingDate": datetime.now().strftime("%Y-%m-%d"),
                "DocumentHeaderText": f"Auto-applied payment {match_result.transaction_id}",
                "LineItems": []
            }
            
            # Add line items for each matched invoice
            line_number = 1
            for invoice_id, amount in match_result.matched_pairs.items():
                application_payload["LineItems"].append({
                    "LineItemNumber": f"{line_number:03d}",
                    "Account": self._get_customer_account(invoice_id),
                    "Amount": float(amount),
                    "Currency": "USD",  # Should be dynamic
                    "Reference": invoice_id,
                    "Assignment": match_result.transaction_id
                })
                line_number += 1
            
            # Post to SAP
            posting_url = f"{self.base_url}/sap/opu/odata/sap/API_JOURNALENTRY_SRV/A_JournalEntry"
            headers = self._build_headers()
            headers['Content-Type'] = 'application/json'
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    posting_url, 
                    json=application_payload, 
                    headers=headers
                ) as response:
                    if response.status == 201:
                        result = await response.json()
                        
                        logger.info(f"Cash application posted successfully to SAP")
                        return {
                            'success': True,
                            'erp_transaction_id': result.get('d', {}).get('AccountingDocument', ''),
                            'message': 'Cash application posted successfully to SAP'
                        }
                    else:
                        error_text = await response.text()
                        raise ERPConnectionError(f"SAP posting failed: {response.status} - {error_text}")
        
        except Exception as e:
            logger.error(f"Failed to post application to SAP: {str(e)}")
            raise ERPDataError(f"SAP application posting failed: {str(e)}")
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test SAP connection"""
        try:
            test_url = f"{self.base_url}/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV/$metadata"
            headers = self._build_headers()
            
            async with aiohttp.ClientSession() as session:
                async with session.get(test_url, headers=headers) as response:
                    if response.status == 200:
                        return {
                            'status': 'success',
                            'message': 'SAP connection successful',
                            'system_info': {
                                'base_url': self.base_url,
                                'auth_method': 'oauth' if self.client_id else 'basic'
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
    
    def _build_headers(self) -> Dict[str, str]:
        """Build authentication headers for SAP requests"""
        if self.client_id and self._access_token:
            # OAuth 2.0
            return {
                'Authorization': f'Bearer {self._access_token}',
                'Accept': 'application/json',
                'X-CSRF-Token': 'Fetch'
            }
        else:
            # Basic authentication
            import base64
            auth_string = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            return {
                'Authorization': f'Basic {auth_string}',
                'Accept': 'application/json',
                'X-CSRF-Token': 'Fetch'
            }
    
    def _parse_sap_invoice(self, data: Dict[str, Any]) -> Invoice:
        """Parse SAP OData response into Invoice object"""
        try:
            # Map SAP fields to our Invoice model
            return Invoice(
                invoice_id=data.get('BillingDocument', ''),
                customer_id=data.get('SoldToParty', ''),
                amount_due=Decimal(str(data.get('TotalNetAmount', 0))),
                currency=data.get('TransactionCurrency', 'USD'),
                status='Open' if data.get('BillingDocumentIsCancelled') != 'X' else 'Closed'
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Failed to parse SAP invoice data: {data} - Error: {e}")
            raise ERPDataError(f"SAP invoice data parsing failed: {str(e)}")
    
    def _get_customer_account(self, invoice_id: str) -> str:
        """Get customer account number for invoice (simplified)"""
        # In practice, this would query SAP to get the customer account
        # For now, return a placeholder
        return "100000"  # Default customer account
