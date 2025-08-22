#!/usr/bin/env python3
"""
eTIMS (Electronic Tax Invoice Management System) Integration
Kenya Revenue Authority (KRA) compliance for invoice validation and tax reporting
"""

import requests
import json
import hashlib
import hmac
import base64
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import logging
from dataclasses import dataclass, asdict
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
import asyncio

@dataclass
class ETIMSInvoice:
    """eTIMS invoice structure"""
    invoice_number: str
    supplier_pin: str
    supplier_name: str
    buyer_pin: Optional[str]
    buyer_name: str
    buyer_id_type: str  # "P" for PIN, "I" for ID, "N" for None
    buyer_id: Optional[str]
    invoice_date: datetime
    invoice_type: str  # "S" for Sale, "R" for Return
    currency: str
    exchange_rate: float
    total_amount: float
    tax_amount: float
    items: List[Dict]
    payment_type: str
    confirmation_datetime: Optional[datetime] = None
    control_unit_id: Optional[str] = None
    receipt_signature: Optional[str] = None

@dataclass
class ETIMSResponse:
    """eTIMS API response"""
    success: bool
    message: str
    control_unit_id: Optional[str] = None
    receipt_signature: Optional[str] = None
    qr_code: Optional[str] = None
    invoice_number: Optional[str] = None
    raw_response: Optional[Dict] = None

class ETIMSClient:
    """Kenya Revenue Authority eTIMS API client"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # eTIMS API configuration
        self.base_url = config.get('base_url', 'https://etims.kra.go.ke/khub-etl-api')
        self.api_key = config['api_key']
        self.secret_key = config['secret_key']
        self.supplier_pin = config['supplier_pin']
        self.device_serial = config.get('device_serial', 'DEFAULT001')
        
        # Environment (sandbox vs production)
        self.is_sandbox = config.get('sandbox', True)
        if self.is_sandbox:
            self.base_url = config.get('sandbox_url', 'https://etims-api-sbx.kra.go.ke/khub-etl-api')
        
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'CashUpAgent/1.0'
        })
        
        self.logger.info(f"eTIMS client initialized for {'SANDBOX' if self.is_sandbox else 'PRODUCTION'}")
    
    def _generate_signature(self, data: str, timestamp: str) -> str:
        """Generate HMAC signature for eTIMS request"""
        message = f"{data}{timestamp}{self.api_key}"
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return base64.b64encode(signature.encode()).decode()
    
    def _make_request(self, endpoint: str, data: Dict) -> Dict:
        """Make authenticated request to eTIMS API"""
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        data_json = json.dumps(data, separators=(',', ':'))
        
        headers = {
            'X-KRA-API-KEY': self.api_key,
            'X-KRA-TIMESTAMP': timestamp,
            'X-KRA-SIGNATURE': self._generate_signature(data_json, timestamp),
            'X-KRA-DEVICE-SERIAL': self.device_serial
        }
        
        self.session.headers.update(headers)
        
        try:
            response = self.session.post(f"{self.base_url}/{endpoint}", json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            self.logger.info(f"eTIMS request to {endpoint} successful")
            
            return result
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"eTIMS request failed: {e}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON response from eTIMS: {e}")
            raise
    
    def validate_pin(self, pin: str) -> Dict:
        """Validate KRA PIN number"""
        data = {
            'pin': pin
        }
        
        try:
            result = self._make_request('pin/validate', data)
            
            return {
                'valid': result.get('resultCd') == '000',
                'name': result.get('taxpayerName', ''),
                'status': result.get('taxpayerStatus', ''),
                'registration_date': result.get('registrationDate', ''),
                'message': result.get('resultMsg', '')
            }
            
        except Exception as e:
            self.logger.error(f"PIN validation failed: {e}")
            return {
                'valid': False,
                'message': f'Validation error: {str(e)}'
            }
    
    def submit_invoice(self, invoice: ETIMSInvoice) -> ETIMSResponse:
        """Submit invoice to eTIMS system"""
        
        # Prepare invoice data according to eTIMS schema
        invoice_data = {
            'supplierPin': invoice.supplier_pin or self.supplier_pin,
            'supplierName': invoice.supplier_name,
            'buyerPin': invoice.buyer_pin,
            'buyerName': invoice.buyer_name,
            'buyerIdType': invoice.buyer_id_type,
            'buyerId': invoice.buyer_id,
            'invoiceNo': invoice.invoice_number,
            'invoiceDate': invoice.invoice_date.strftime('%Y%m%d%H%M%S'),
            'invoiceType': invoice.invoice_type,
            'salesType': 'N',  # Normal sale
            'currency': invoice.currency,
            'exchangeRate': invoice.exchange_rate,
            'totalAmount': invoice.total_amount,
            'taxAmount': invoice.tax_amount,
            'paymentType': invoice.payment_type,
            'itemList': []
        }
        
        # Add line items
        for idx, item in enumerate(invoice.items):
            item_data = {
                'itemSeq': idx + 1,
                'itemCode': item.get('code', f'ITEM{idx:03d}'),
                'itemName': item['name'],
                'quantity': item['quantity'],
                'unitPrice': item['unit_price'],
                'totalAmount': item['total_amount'],
                'taxType': item.get('tax_type', 'B'),  # B = VAT
                'taxAmount': item.get('tax_amount', 0),
                'discountAmount': item.get('discount_amount', 0)
            }
            invoice_data['itemList'].append(item_data)
        
        try:
            result = self._make_request('invoice/submit', invoice_data)
            
            return ETIMSResponse(
                success=result.get('resultCd') == '000',
                message=result.get('resultMsg', ''),
                control_unit_id=result.get('controlUnitId'),
                receipt_signature=result.get('receiptSignature'),
                qr_code=result.get('qrCode'),
                invoice_number=result.get('invoiceNumber'),
                raw_response=result
            )
            
        except Exception as e:
            self.logger.error(f"Invoice submission failed: {e}")
            return ETIMSResponse(
                success=False,
                message=f'Submission error: {str(e)}'
            )
    
    def validate_invoice(self, invoice_number: str, supplier_pin: str = None) -> Dict:
        """Validate existing invoice in eTIMS"""
        data = {
            'supplierPin': supplier_pin or self.supplier_pin,
            'invoiceNo': invoice_number
        }
        
        try:
            result = self._make_request('invoice/validate', data)
            
            return {
                'valid': result.get('resultCd') == '000',
                'status': result.get('invoiceStatus', ''),
                'control_unit_id': result.get('controlUnitId', ''),
                'receipt_signature': result.get('receiptSignature', ''),
                'submission_date': result.get('submissionDate', ''),
                'message': result.get('resultMsg', '')
            }
            
        except Exception as e:
            self.logger.error(f"Invoice validation failed: {e}")
            return {
                'valid': False,
                'message': f'Validation error: {str(e)}'
            }
    
    def get_tax_types(self) -> List[Dict]:
        """Get available tax types from eTIMS"""
        try:
            result = self._make_request('master/tax-types', {})
            
            tax_types = []
            for tax_type in result.get('taxTypes', []):
                tax_types.append({
                    'code': tax_type.get('taxTypeCode'),
                    'name': tax_type.get('taxTypeName'),
                    'rate': tax_type.get('taxRate'),
                    'category': tax_type.get('category')
                })
            
            return tax_types
            
        except Exception as e:
            self.logger.error(f"Failed to get tax types: {e}")
            return []
    
    def get_item_classifications(self) -> List[Dict]:
        """Get item classification codes from eTIMS"""
        try:
            result = self._make_request('master/item-classifications', {})
            
            classifications = []
            for item in result.get('itemClassifications', []):
                classifications.append({
                    'code': item.get('classificationCode'),
                    'name': item.get('classificationName'),
                    'tax_type': item.get('defaultTaxType'),
                    'description': item.get('description')
                })
            
            return classifications
            
        except Exception as e:
            self.logger.error(f"Failed to get item classifications: {e}")
            return []

class CashUpETIMSIntegration:
    """CashUp Agent eTIMS integration for automatic compliance"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize eTIMS client
        self.etims_client = ETIMSClient(config['etims'])
        
        # Mapping configurations
        self.customer_pin_mapping = config.get('customer_pin_mapping', {})
        self.item_classification_mapping = config.get('item_classification_mapping', {})
        
        # Validation settings
        self.require_buyer_pin = config.get('require_buyer_pin', False)
        self.validate_before_payment = config.get('validate_before_payment', True)
        self.auto_submit_invoices = config.get('auto_submit_invoices', False)
    
    async def validate_payment_invoice(self, payment: Dict, invoice: Dict) -> Dict:
        """Validate invoice against eTIMS before applying payment"""
        
        if not self.validate_before_payment:
            return {'valid': True, 'message': 'Validation disabled'}
        
        invoice_number = invoice.get('invoice_number', invoice.get('number'))
        supplier_pin = invoice.get('supplier_pin', self.config['etims']['supplier_pin'])
        
        self.logger.info(f"Validating invoice {invoice_number} in eTIMS")
        
        try:
            validation_result = self.etims_client.validate_invoice(invoice_number, supplier_pin)
            
            if validation_result['valid']:
                self.logger.info(f"Invoice {invoice_number} is valid in eTIMS")
                return {
                    'valid': True,
                    'message': 'Invoice validated in eTIMS',
                    'etims_status': validation_result['status'],
                    'control_unit_id': validation_result['control_unit_id']
                }
            else:
                self.logger.warning(f"Invoice {invoice_number} not found or invalid in eTIMS")
                
                # If auto-submit is enabled, try to create the invoice
                if self.auto_submit_invoices:
                    return await self._auto_submit_invoice(invoice)
                
                return {
                    'valid': False,
                    'message': f'Invoice not found in eTIMS: {validation_result["message"]}',
                    'requires_submission': True
                }
                
        except Exception as e:
            self.logger.error(f"eTIMS validation error for invoice {invoice_number}: {e}")
            return {
                'valid': False,
                'message': f'eTIMS validation error: {str(e)}',
                'error': True
            }
    
    async def _auto_submit_invoice(self, invoice: Dict) -> Dict:
        """Automatically submit invoice to eTIMS"""
        
        try:
            # Convert invoice to eTIMS format
            etims_invoice = await self._convert_to_etims_invoice(invoice)
            
            # Submit to eTIMS
            result = self.etims_client.submit_invoice(etims_invoice)
            
            if result.success:
                self.logger.info(f"Successfully submitted invoice {invoice['invoice_number']} to eTIMS")
                return {
                    'valid': True,
                    'message': 'Invoice automatically submitted to eTIMS',
                    'auto_submitted': True,
                    'control_unit_id': result.control_unit_id,
                    'receipt_signature': result.receipt_signature
                }
            else:
                self.logger.error(f"Failed to auto-submit invoice: {result.message}")
                return {
                    'valid': False,
                    'message': f'Auto-submission failed: {result.message}',
                    'requires_manual_submission': True
                }
                
        except Exception as e:
            self.logger.error(f"Auto-submit error: {e}")
            return {
                'valid': False,
                'message': f'Auto-submission error: {str(e)}',
                'error': True
            }
    
    async def _convert_to_etims_invoice(self, invoice: Dict) -> ETIMSInvoice:
        """Convert internal invoice format to eTIMS format"""
        
        # Get customer information
        customer = invoice.get('customer', {})
        customer_name = customer.get('name', customer.get('customer_name', ''))
        customer_pin = self._get_customer_pin(customer)
        
        # Determine buyer ID type and ID
        buyer_id_type = 'P' if customer_pin else 'N'  # PIN or None
        buyer_id = customer_pin if customer_pin else None
        
        # Convert line items
        items = []
        line_items = invoice.get('line_items', invoice.get('items', []))
        
        for item in line_items:
            tax_amount = item.get('tax_amount', item.get('amount', 0) * 0.16)  # Default 16% VAT
            
            items.append({
                'code': item.get('item_code', item.get('sku', 'MISC')),
                'name': item.get('description', item.get('name', 'Miscellaneous Item')),
                'quantity': item.get('quantity', 1),
                'unit_price': item.get('unit_price', item.get('amount', 0)),
                'total_amount': item.get('amount', item.get('total_amount', 0)),
                'tax_type': 'B',  # VAT
                'tax_amount': tax_amount,
                'discount_amount': item.get('discount_amount', 0)
            })
        
        # Calculate totals
        total_amount = float(invoice.get('amount_total', invoice.get('total_amount', 0)))
        tax_amount = float(invoice.get('tax_amount', total_amount * 0.16))  # Default 16% VAT
        
        return ETIMSInvoice(
            invoice_number=invoice.get('invoice_number', invoice.get('number')),
            supplier_pin=self.config['etims']['supplier_pin'],
            supplier_name=self.config['etims'].get('supplier_name', 'Your Company Ltd'),
            buyer_pin=customer_pin,
            buyer_name=customer_name,
            buyer_id_type=buyer_id_type,
            buyer_id=buyer_id,
            invoice_date=self._parse_date(invoice.get('invoice_date', invoice.get('date'))),
            invoice_type='S',  # Sale
            currency=invoice.get('currency', 'KES'),
            exchange_rate=1.0,  # Assume KES base currency
            total_amount=total_amount,
            tax_amount=tax_amount,
            items=items,
            payment_type='01'  # Cash/Electronic payment
        )
    
    def _get_customer_pin(self, customer: Dict) -> Optional[str]:
        """Get customer KRA PIN from mapping or customer data"""
        
        customer_id = customer.get('id', customer.get('customer_id'))
        customer_name = customer.get('name', customer.get('customer_name', ''))
        
        # Check PIN mapping first
        if customer_id in self.customer_pin_mapping:
            return self.customer_pin_mapping[customer_id]
        
        # Check if PIN is directly in customer data
        pin = customer.get('kra_pin', customer.get('pin', customer.get('tax_number')))
        if pin and self._is_valid_kra_pin_format(pin):
            return pin
        
        # Try to extract from customer name if it contains PIN
        pin_match = self._extract_pin_from_name(customer_name)
        if pin_match:
            return pin_match
        
        return None
    
    def _is_valid_kra_pin_format(self, pin: str) -> bool:
        """Validate KRA PIN format"""
        # KRA PIN format: Letter + 9 digits + Letter (e.g., P051234567M)
        import re
        pattern = r'^[A-Z]\d{9}[A-Z]$'
        return bool(re.match(pattern, pin.upper()))
    
    def _extract_pin_from_name(self, name: str) -> Optional[str]:
        """Extract KRA PIN from customer name"""
        import re
        
        # Look for PIN pattern in name
        pin_pattern = r'([A-Z]\d{9}[A-Z])'
        match = re.search(pin_pattern, name.upper())
        
        return match.group(1) if match else None
    
    def _parse_date(self, date_str: Any) -> datetime:
        """Parse date from various formats"""
        if isinstance(date_str, datetime):
            return date_str
        
        if not date_str:
            return datetime.now()
        
        # Try different date formats
        formats = [
            '%Y-%m-%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%d/%m/%Y',
            '%m/%d/%Y'
        ]
        
        date_str = str(date_str)
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # If all else fails, return current date
        self.logger.warning(f"Could not parse date: {date_str}, using current date")
        return datetime.now()
    
    async def validate_customer_pin(self, customer_pin: str) -> Dict:
        """Validate customer KRA PIN"""
        
        if not customer_pin:
            return {'valid': False, 'message': 'No PIN provided'}
        
        if not self._is_valid_kra_pin_format(customer_pin):
            return {'valid': False, 'message': 'Invalid PIN format'}
        
        try:
            result = self.etims_client.validate_pin(customer_pin)
            return result
            
        except Exception as e:
            self.logger.error(f"PIN validation error: {e}")
            return {'valid': False, 'message': f'Validation error: {str(e)}'}
    
    def generate_compliance_report(self, start_date: datetime, end_date: datetime) -> Dict:
        """Generate eTIMS compliance report"""
        
        report = {
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_invoices_processed': 0,
                'etims_validated': 0,
                'etims_submitted': 0,
                'validation_failures': 0,
                'compliance_rate': 0.0
            },
            'issues': [],
            'recommendations': []
        }
        
        # This would typically query your database for actual statistics
        # For now, we'll return a template structure
        
        return report
    
    async def sync_master_data(self):
        """Sync master data from eTIMS (tax types, item classifications)"""
        
        try:
            self.logger.info("Syncing master data from eTIMS")
            
            # Get tax types
            tax_types = self.etims_client.get_tax_types()
            self.logger.info(f"Retrieved {len(tax_types)} tax types")
            
            # Get item classifications
            classifications = self.etims_client.get_item_classifications()
            self.logger.info(f"Retrieved {len(classifications)} item classifications")
            
            # Store in configuration or database
            master_data = {
                'tax_types': tax_types,
                'item_classifications': classifications,
                'last_updated': datetime.now().isoformat()
            }
            
            return master_data
            
        except Exception as e:
            self.logger.error(f"Master data sync failed: {e}")
            raise

# Example usage and configuration
if __name__ == "__main__":
    
    # Example configuration
    config = {
        'etims': {
            'api_key': 'your_etims_api_key',
            'secret_key': 'your_etims_secret_key',
            'supplier_pin': 'P051234567M',
            'supplier_name': 'EAST AFRICAN BREWERIES LIMITED',
            'device_serial': 'CU001001',
            'sandbox': True
        },
        'customer_pin_mapping': {
            'CUST001': 'P051987654N',
            'CUST002': 'P052345678K'
        },
        'require_buyer_pin': False,
        'validate_before_payment': True,
        'auto_submit_invoices': False
    }
    
    # Initialize integration
    etims_integration = CashUpETIMSIntegration(config)
    
    # Example invoice validation
    sample_invoice = {
        'invoice_number': 'INV-2024-001',
        'customer': {
            'id': 'CUST001',
            'name': 'JOHN DOE ENTERPRISES LTD',
            'kra_pin': 'P051987654N'
        },
        'invoice_date': '2024-08-15',
        'amount_total': 11600.00,
        'tax_amount': 1600.00,
        'currency': 'KES',
        'line_items': [
            {
                'description': 'Tusker Beer - 500ml',
                'quantity': 100,
                'unit_price': 100.00,
                'amount': 10000.00,
                'tax_amount': 1600.00
            }
        ]
    }
    
    sample_payment = {
        'id': 'PAY001',
        'amount': 11600.00,
        'reference': 'MPE123456'
    }
    
    # Test validation
    async def test_validation():
        result = await etims_integration.validate_payment_invoice(sample_payment, sample_invoice)
        print(f"Validation result: {result}")
    
    # Run test
    asyncio.run(test_validation())