#!/usr/bin/env python3
"""
Enhanced ERP Connectors for Kenya/East Africa
Supports Odoo, Oracle Cloud, Sage, and custom ERP systems beyond SAP
"""

import requests
import xmlrpc.client
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
import base64
import hmac
import hashlib

@dataclass
class ERPInvoice:
    """Standardized ERP invoice structure"""
    invoice_number: str
    customer_id: str
    customer_name: str
    amount_total: float
    amount_due: float
    currency: str
    invoice_date: datetime
    due_date: datetime
    status: str
    description: Optional[str] = None
    reference: Optional[str] = None
    line_items: Optional[List[Dict]] = None

@dataclass
class ERPPayment:
    """Standardized ERP payment structure"""
    payment_reference: str
    customer_id: str
    amount: float
    currency: str
    payment_date: datetime
    payment_method: str
    bank_reference: Optional[str] = None
    memo: Optional[str] = None
    applied_invoices: Optional[List[Dict]] = None

class ERPConnector(ABC):
    """Abstract base class for ERP connectors"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    @abstractmethod
    def test_connection(self) -> bool:
        """Test connection to ERP system"""
        pass
    
    @abstractmethod
    def get_open_invoices(self, customer_id: Optional[str] = None) -> List[ERPInvoice]:
        """Get open invoices from ERP"""
        pass
    
    @abstractmethod
    def create_payment(self, payment: ERPPayment) -> Dict:
        """Create payment in ERP system"""
        pass
    
    @abstractmethod
    def apply_payment_to_invoice(self, payment_id: str, invoice_id: str, amount: float) -> Dict:
        """Apply payment to specific invoice"""
        pass

class OdooConnector(ERPConnector):
    """Odoo ERP connector using XML-RPC"""
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.url = config['url']
        self.database = config['database']
        self.username = config['username']
        self.password = config['password']
        
        # XML-RPC connections
        self.common = None
        self.models = None
        self.uid = None
        
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Odoo"""
        try:
            self.common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            
            # Get server version (test connection)
            version = self.common.version()
            self.logger.info(f"Connected to Odoo version: {version}")
            
            # Authenticate
            self.uid = self.common.authenticate(self.database, self.username, self.password, {})
            
            if not self.uid:
                raise Exception("Authentication failed")
            
            self.logger.info(f"Authenticated as user ID: {self.uid}")
            
        except Exception as e:
            self.logger.error(f"Odoo authentication failed: {e}")
            raise
    
    def test_connection(self) -> bool:
        """Test Odoo connection"""
        try:
            # Try to read user info
            user_info = self.models.execute_kw(
                self.database, self.uid, self.password,
                'res.users', 'read', [self.uid], {'fields': ['name', 'login']}
            )
            
            self.logger.info(f"Connection test successful: {user_info[0]['name']}")
            return True
            
        except Exception as e:
            self.logger.error(f"Odoo connection test failed: {e}")
            return False
    
    def get_open_invoices(self, customer_id: Optional[str] = None) -> List[ERPInvoice]:
        """Get open invoices from Odoo"""
        try:
            # Search criteria for open invoices
            search_criteria = [
                ('state', '=', 'posted'),  # Posted invoices
                ('payment_state', 'in', ['not_paid', 'partial']),  # Not fully paid
                ('move_type', '=', 'out_invoice')  # Customer invoices
            ]
            
            if customer_id:
                search_criteria.append(('partner_id', '=', int(customer_id)))
            
            # Search for invoices
            invoice_ids = self.models.execute_kw(
                self.database, self.uid, self.password,
                'account.move', 'search', [search_criteria]
            )
            
            if not invoice_ids:
                return []
            
            # Read invoice details
            invoice_fields = [
                'name', 'partner_id', 'amount_total', 'amount_residual',
                'currency_id', 'invoice_date', 'invoice_date_due',
                'state', 'payment_state', 'ref'
            ]
            
            invoices_data = self.models.execute_kw(
                self.database, self.uid, self.password,
                'account.move', 'read', [invoice_ids], {'fields': invoice_fields}
            )
            
            # Convert to ERPInvoice objects
            erp_invoices = []
            for inv_data in invoices_data:
                erp_invoice = ERPInvoice(
                    invoice_number=inv_data['name'],
                    customer_id=str(inv_data['partner_id'][0]),
                    customer_name=inv_data['partner_id'][1],
                    amount_total=inv_data['amount_total'],
                    amount_due=inv_data['amount_residual'],
                    currency=inv_data['currency_id'][1] if inv_data['currency_id'] else 'KES',
                    invoice_date=datetime.strptime(inv_data['invoice_date'], '%Y-%m-%d') if inv_data['invoice_date'] else datetime.now(),
                    due_date=datetime.strptime(inv_data['invoice_date_due'], '%Y-%m-%d') if inv_data['invoice_date_due'] else datetime.now(),
                    status=inv_data['payment_state'],
                    reference=inv_data['ref']
                )
                erp_invoices.append(erp_invoice)
            
            self.logger.info(f"Retrieved {len(erp_invoices)} open invoices from Odoo")
            return erp_invoices
            
        except Exception as e:
            self.logger.error(f"Error retrieving Odoo invoices: {e}")
            return []
    
    def create_payment(self, payment: ERPPayment) -> Dict:
        """Create payment in Odoo"""
        try:
            # Find payment journal (bank/cash journal)
            journal_id = self._find_payment_journal(payment.payment_method)
            
            # Create payment record
            payment_data = {
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': int(payment.customer_id),
                'amount': payment.amount,
                'currency_id': self._get_currency_id(payment.currency),
                'date': payment.payment_date.strftime('%Y-%m-%d'),
                'ref': payment.payment_reference,
                'communication': payment.memo or f"Payment {payment.payment_reference}",
                'journal_id': journal_id,
            }
            
            # Create payment
            payment_id = self.models.execute_kw(
                self.database, self.uid, self.password,
                'account.payment', 'create', [payment_data]
            )
            
            # Confirm payment
            self.models.execute_kw(
                self.database, self.uid, self.password,
                'account.payment', 'action_post', [payment_id]
            )
            
            self.logger.info(f"Created Odoo payment: {payment_id}")
            
            return {
                'success': True,
                'payment_id': payment_id,
                'odoo_reference': f"PAY/{payment.payment_date.year:04d}/{payment_id:05d}"
            }
            
        except Exception as e:
            self.logger.error(f"Error creating Odoo payment: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def apply_payment_to_invoice(self, payment_id: str, invoice_id: str, amount: float) -> Dict:
        """Apply payment to specific invoice in Odoo"""
        try:
            # Get payment and invoice records
            payment_data = self.models.execute_kw(
                self.database, self.uid, self.password,
                'account.payment', 'read', [int(payment_id)],
                {'fields': ['move_id', 'state']}
            )[0]
            
            if payment_data['state'] != 'posted':
                raise Exception("Payment must be posted before application")
            
            # Get the payment move lines
            payment_move_id = payment_data['move_id'][0]
            payment_lines = self.models.execute_kw(
                self.database, self.uid, self.password,
                'account.move.line', 'search', [
                    [('move_id', '=', payment_move_id), ('credit', '>', 0)]
                ]
            )
            
            # Get invoice move lines
            invoice_lines = self.models.execute_kw(
                self.database, self.uid, self.password,
                'account.move.line', 'search', [
                    [('move_id', '=', int(invoice_id)), ('debit', '>', 0)]
                ]
            )
            
            if payment_lines and invoice_lines:
                # Reconcile payment with invoice
                reconcile_data = {
                    'line_ids': payment_lines + invoice_lines
                }
                
                # Create reconciliation
                self.models.execute_kw(
                    self.database, self.uid, self.password,
                    'account.move.line', 'reconcile', [], reconcile_data
                )
                
                return {
                    'success': True,
                    'message': f"Applied payment {payment_id} to invoice {invoice_id}"
                }
            else:
                return {
                    'success': False,
                    'error': "Could not find payment or invoice lines for reconciliation"
                }
                
        except Exception as e:
            self.logger.error(f"Error applying Odoo payment: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _find_payment_journal(self, payment_method: str) -> int:
        """Find appropriate payment journal based on payment method"""
        journal_mapping = {
            'mpesa': ['M-Pesa', 'Mobile Money', 'MPESA'],
            'bank_transfer': ['Bank', 'Bank and Cash'],
            'cash': ['Cash'],
            'cheque': ['Bank', 'Cheque']
        }
        
        search_names = journal_mapping.get(payment_method.lower(), ['Bank'])
        
        for name in search_names:
            journal_ids = self.models.execute_kw(
                self.database, self.uid, self.password,
                'account.journal', 'search',
                [[('name', 'ilike', name), ('type', 'in', ['bank', 'cash'])]]
            )
            
            if journal_ids:
                return journal_ids[0]
        
        # Fallback: get first bank journal
        journal_ids = self.models.execute_kw(
            self.database, self.uid, self.password,
            'account.journal', 'search',
            [[('type', '=', 'bank')]]
        )
        
        return journal_ids[0] if journal_ids else 1
    
    def _get_currency_id(self, currency_code: str) -> int:
        """Get currency ID from currency code"""
        currency_ids = self.models.execute_kw(
            self.database, self.uid, self.password,
            'res.currency', 'search',
            [[('name', '=', currency_code)]]
        )
        
        return currency_ids[0] if currency_ids else 1  # Default to company currency

class OracleCloudConnector(ERPConnector):
    """Oracle Cloud ERP connector using REST APIs"""
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config['base_url']
        self.username = config['username']
        self.password = config['password']
        
        # Setup session with authentication
        self.session = requests.Session()
        self.session.auth = (self.username, self.password)
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def test_connection(self) -> bool:
        """Test Oracle Cloud connection"""
        try:
            response = self.session.get(f"{self.base_url}/fscmRestApi/resources/11.13.18.05/invoices?limit=1")
            response.raise_for_status()
            
            self.logger.info("Oracle Cloud connection test successful")
            return True
            
        except Exception as e:
            self.logger.error(f"Oracle Cloud connection test failed: {e}")
            return False
    
    def get_open_invoices(self, customer_id: Optional[str] = None) -> List[ERPInvoice]:
        """Get open invoices from Oracle Cloud"""
        try:
            # Build query parameters
            params = {
                'q': "Status='Open'",
                'limit': 1000,
                'fields': 'InvoiceId,InvoiceNumber,CustomerId,CustomerName,InvoiceAmount,OutstandingAmount,InvoiceDate,DueDate,InvoiceCurrency,Description'
            }
            
            if customer_id:
                params['q'] += f" AND CustomerId='{customer_id}'"
            
            response = self.session.get(
                f"{self.base_url}/fscmRestApi/resources/11.13.18.05/receivablesInvoices",
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            invoices_data = data.get('items', [])
            
            # Convert to ERPInvoice objects
            erp_invoices = []
            for inv_data in invoices_data:
                erp_invoice = ERPInvoice(
                    invoice_number=inv_data['InvoiceNumber'],
                    customer_id=str(inv_data['CustomerId']),
                    customer_name=inv_data['CustomerName'],
                    amount_total=inv_data['InvoiceAmount'],
                    amount_due=inv_data['OutstandingAmount'],
                    currency=inv_data.get('InvoiceCurrency', 'USD'),
                    invoice_date=datetime.fromisoformat(inv_data['InvoiceDate'].replace('Z', '+00:00')),
                    due_date=datetime.fromisoformat(inv_data['DueDate'].replace('Z', '+00:00')),
                    status='Open',
                    description=inv_data.get('Description')
                )
                erp_invoices.append(erp_invoice)
            
            self.logger.info(f"Retrieved {len(erp_invoices)} open invoices from Oracle Cloud")
            return erp_invoices
            
        except Exception as e:
            self.logger.error(f"Error retrieving Oracle Cloud invoices: {e}")
            return []
    
    def create_payment(self, payment: ERPPayment) -> Dict:
        """Create payment in Oracle Cloud"""
        try:
            payment_data = {
                'ReceiptNumber': payment.payment_reference,
                'ReceiptAmount': payment.amount,
                'ReceiptDate': payment.payment_date.isoformat(),
                'CurrencyCode': payment.currency,
                'CustomerId': int(payment.customer_id),
                'PaymentMethod': payment.payment_method,
                'Comments': payment.memo,
                'ReceiptMethod': self._map_payment_method_oracle(payment.payment_method)
            }
            
            response = self.session.post(
                f"{self.base_url}/fscmRestApi/resources/11.13.18.05/receipts",
                json=payment_data
            )
            response.raise_for_status()
            
            result = response.json()
            
            self.logger.info(f"Created Oracle Cloud payment: {result.get('ReceiptId')}")
            
            return {
                'success': True,
                'payment_id': result.get('ReceiptId'),
                'oracle_reference': result.get('ReceiptNumber')
            }
            
        except Exception as e:
            self.logger.error(f"Error creating Oracle Cloud payment: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def apply_payment_to_invoice(self, payment_id: str, invoice_id: str, amount: float) -> Dict:
        """Apply payment to invoice in Oracle Cloud"""
        try:
            application_data = {
                'ReceiptId': int(payment_id),
                'InvoiceId': int(invoice_id),
                'AmountApplied': amount,
                'ApplicationDate': datetime.now().isoformat()
            }
            
            response = self.session.post(
                f"{self.base_url}/fscmRestApi/resources/11.13.18.05/receiptApplications",
                json=application_data
            )
            response.raise_for_status()
            
            result = response.json()
            
            return {
                'success': True,
                'application_id': result.get('ApplicationId'),
                'message': f"Applied payment {payment_id} to invoice {invoice_id}"
            }
            
        except Exception as e:
            self.logger.error(f"Error applying Oracle Cloud payment: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _map_payment_method_oracle(self, payment_method: str) -> str:
        """Map payment method to Oracle Cloud receipt method"""
        method_mapping = {
            'mpesa': 'MOBILE_MONEY',
            'bank_transfer': 'WIRE_TRANSFER',
            'cash': 'CASH',
            'cheque': 'CHECK'
        }
        
        return method_mapping.get(payment_method.lower(), 'ELECTRONIC')

class SageConnector(ERPConnector):
    """Sage ERP connector"""
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config['base_url']
        self.api_key = config['api_key']
        
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def test_connection(self) -> bool:
        """Test Sage connection"""
        try:
            response = self.session.get(f"{self.base_url}/core/v3-1/companies")
            response.raise_for_status()
            
            self.logger.info("Sage connection test successful")
            return True
            
        except Exception as e:
            self.logger.error(f"Sage connection test failed: {e}")
            return False
    
    def get_open_invoices(self, customer_id: Optional[str] = None) -> List[ERPInvoice]:
        """Get open invoices from Sage"""
        try:
            params = {
                'attributes': 'id,displayed_as,reference,customer,total_amount,outstanding_amount,date,due_date,currency,notes',
                'where': 'outstanding_amount.gt.0'
            }
            
            if customer_id:
                params['where'] += f' AND customer.id.eq.{customer_id}'
            
            response = self.session.get(
                f"{self.base_url}/accounts/v1/sales_invoices",
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            invoices_data = data.get('items', [])
            
            # Convert to ERPInvoice objects
            erp_invoices = []
            for inv_data in invoices_data:
                erp_invoice = ERPInvoice(
                    invoice_number=inv_data['reference'],
                    customer_id=str(inv_data['customer']['id']),
                    customer_name=inv_data['customer']['displayed_as'],
                    amount_total=inv_data['total_amount'],
                    amount_due=inv_data['outstanding_amount'],
                    currency=inv_data['currency']['displayed_as'] if inv_data['currency'] else 'KES',
                    invoice_date=datetime.fromisoformat(inv_data['date']),
                    due_date=datetime.fromisoformat(inv_data['due_date']),
                    status='Outstanding',
                    description=inv_data.get('notes')
                )
                erp_invoices.append(erp_invoice)
            
            self.logger.info(f"Retrieved {len(erp_invoices)} open invoices from Sage")
            return erp_invoices
            
        except Exception as e:
            self.logger.error(f"Error retrieving Sage invoices: {e}")
            return []
    
    def create_payment(self, payment: ERPPayment) -> Dict:
        """Create payment in Sage"""
        try:
            payment_data = {
                'customer': {'id': int(payment.customer_id)},
                'reference': payment.payment_reference,
                'total_amount': payment.amount,
                'date': payment.payment_date.strftime('%Y-%m-%d'),
                'payment_method': {'displayed_as': payment.payment_method},
                'currency': {'displayed_as': payment.currency},
                'details': payment.memo or f"Payment {payment.payment_reference}"
            }
            
            response = self.session.post(
                f"{self.base_url}/accounts/v1/customer_payments",
                json={'customer_payment': payment_data}
            )
            response.raise_for_status()
            
            result = response.json()
            
            self.logger.info(f"Created Sage payment: {result['id']}")
            
            return {
                'success': True,
                'payment_id': result['id'],
                'sage_reference': result['reference']
            }
            
        except Exception as e:
            self.logger.error(f"Error creating Sage payment: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def apply_payment_to_invoice(self, payment_id: str, invoice_id: str, amount: float) -> Dict:
        """Apply payment to invoice in Sage"""
        try:
            # In Sage, payment application is typically done during payment creation
            # For existing payments, we need to allocate them
            allocation_data = {
                'payment_id': int(payment_id),
                'invoice_id': int(invoice_id),
                'amount': amount,
                'date': datetime.now().strftime('%Y-%m-%d')
            }
            
            response = self.session.post(
                f"{self.base_url}/accounts/v1/payment_allocations",
                json={'payment_allocation': allocation_data}
            )
            response.raise_for_status()
            
            result = response.json()
            
            return {
                'success': True,
                'allocation_id': result.get('id'),
                'message': f"Applied payment {payment_id} to invoice {invoice_id}"
            }
            
        except Exception as e:
            self.logger.error(f"Error applying Sage payment: {e}")
            return {
                'success': False,
                'error': str(e)
            }

class CustomERPConnector(ERPConnector):
    """Generic connector for custom ERP systems using REST APIs"""
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config['base_url']
        self.auth_type = config.get('auth_type', 'bearer')
        
        self.session = requests.Session()
        
        # Setup authentication
        if self.auth_type == 'bearer':
            self.session.headers.update({
                'Authorization': f"Bearer {config['api_token']}"
            })
        elif self.auth_type == 'basic':
            self.session.auth = (config['username'], config['password'])
        elif self.auth_type == 'api_key':
            key_header = config.get('api_key_header', 'X-API-Key')
            self.session.headers.update({
                key_header: config['api_key']
            })
        
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        # API endpoints configuration
        self.endpoints = config.get('endpoints', {})
    
    def test_connection(self) -> bool:
        """Test custom ERP connection"""
        try:
            test_endpoint = self.endpoints.get('test', '/health')
            response = self.session.get(f"{self.base_url}{test_endpoint}")
            response.raise_for_status()
            
            self.logger.info("Custom ERP connection test successful")
            return True
            
        except Exception as e:
            self.logger.error(f"Custom ERP connection test failed: {e}")
            return False
    
    def get_open_invoices(self, customer_id: Optional[str] = None) -> List[ERPInvoice]:
        """Get open invoices from custom ERP"""
        try:
            invoices_endpoint = self.endpoints.get('invoices', '/invoices')
            params = {'status': 'open'}
            
            if customer_id:
                params['customer_id'] = customer_id
            
            response = self.session.get(
                f"{self.base_url}{invoices_endpoint}",
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            invoices_data = data if isinstance(data, list) else data.get('data', [])
            
            # Convert to ERPInvoice objects (assuming standard field names)
            erp_invoices = []
            for inv_data in invoices_data:
                erp_invoice = ERPInvoice(
                    invoice_number=inv_data.get('invoice_number', inv_data.get('number')),
                    customer_id=str(inv_data.get('customer_id')),
                    customer_name=inv_data.get('customer_name', inv_data.get('customer', {}).get('name', '')),
                    amount_total=float(inv_data.get('total_amount', 0)),
                    amount_due=float(inv_data.get('amount_due', inv_data.get('outstanding_amount', 0))),
                    currency=inv_data.get('currency', 'KES'),
                    invoice_date=self._parse_date(inv_data.get('invoice_date')),
                    due_date=self._parse_date(inv_data.get('due_date')),
                    status=inv_data.get('status', 'open'),
                    description=inv_data.get('description'),
                    reference=inv_data.get('reference')
                )
                erp_invoices.append(erp_invoice)
            
            self.logger.info(f"Retrieved {len(erp_invoices)} open invoices from custom ERP")
            return erp_invoices
            
        except Exception as e:
            self.logger.error(f"Error retrieving custom ERP invoices: {e}")
            return []
    
    def create_payment(self, payment: ERPPayment) -> Dict:
        """Create payment in custom ERP"""
        try:
            payments_endpoint = self.endpoints.get('payments', '/payments')
            
            payment_data = asdict(payment)
            payment_data['payment_date'] = payment.payment_date.isoformat()
            
            response = self.session.post(
                f"{self.base_url}{payments_endpoint}",
                json=payment_data
            )
            response.raise_for_status()
            
            result = response.json()
            
            self.logger.info(f"Created custom ERP payment: {result.get('id')}")
            
            return {
                'success': True,
                'payment_id': result.get('id'),
                'reference': result.get('reference', payment.payment_reference)
            }
            
        except Exception as e:
            self.logger.error(f"Error creating custom ERP payment: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def apply_payment_to_invoice(self, payment_id: str, invoice_id: str, amount: float) -> Dict:
        """Apply payment to invoice in custom ERP"""
        try:
            application_endpoint = self.endpoints.get('payment_applications', '/payment-applications')
            
            application_data = {
                'payment_id': payment_id,
                'invoice_id': invoice_id,
                'amount': amount,
                'application_date': datetime.now().isoformat()
            }
            
            response = self.session.post(
                f"{self.base_url}{application_endpoint}",
                json=application_data
            )
            response.raise_for_status()
            
            result = response.json()
            
            return {
                'success': True,
                'application_id': result.get('id'),
                'message': f"Applied payment {payment_id} to invoice {invoice_id}"
            }
            
        except Exception as e:
            self.logger.error(f"Error applying custom ERP payment: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string in various formats"""
        if not date_str:
            return datetime.now()
        
        formats = [
            '%Y-%m-%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%d/%m/%Y',
            '%m/%d/%Y'
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        return datetime.now()

class ERPConnectorFactory:
    """Factory for creating ERP connectors"""
    
    @staticmethod
    def get_connector(erp_type: str, config: Dict) -> ERPConnector:
        """Get appropriate ERP connector"""
        connectors = {
            'odoo': OdooConnector,
            'oracle': OracleCloudConnector,
            'oracle_cloud': OracleCloudConnector,
            'sage': SageConnector,
            'custom': CustomERPConnector
        }
        
        connector_class = connectors.get(erp_type.lower())
        if not connector_class:
            raise ValueError(f"Unsupported ERP system: {erp_type}")
        
        return connector_class(config)

# Example usage
if __name__ == "__main__":
    # Example Odoo configuration
    odoo_config = {
        'url': 'https://your-odoo-instance.com',
        'database': 'your_database',
        'username': 'admin',
        'password': 'admin_password'
    }
    
    # Test Odoo connector
    try:
        odoo_connector = OdooConnector(odoo_config)
        
        if odoo_connector.test_connection():
            print("✅ Odoo connection successful")
            
            # Get open invoices
            invoices = odoo_connector.get_open_invoices()
            print(f"Found {len(invoices)} open invoices")
            
            for invoice in invoices[:3]:  # Show first 3
                print(f"- {invoice.invoice_number}: {invoice.amount_due} {invoice.currency}")
        else:
            print("❌ Odoo connection failed")
            
    except Exception as e:
        print(f"Error testing Odoo connector: {e}")