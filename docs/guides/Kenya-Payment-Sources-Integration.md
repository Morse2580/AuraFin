# 🇰🇪 Kenya Payment Sources Integration Guide
## M-Pesa, Airtel Money, and Bank Statement Processing

---

## 📱 M-Pesa Integration Specifications

### **M-Pesa C2B Statement Processing**

#### **CSV Format Adapter:**
```python
class MPesaC2BAdapter:
    def __init__(self):
        self.expected_columns = [
            'Receipt No', 'Completion Time', 'Details', 'Transaction Status',
            'Paid In', 'Withdrawn', 'Balance', 'Reason Type', 'Other Party Info'
        ]
    
    def parse_csv(self, csv_content: str):
        """Parse M-Pesa C2B CSV export"""
        df = pd.read_csv(io.StringIO(csv_content))
        
        payments = []
        for _, row in df.iterrows():
            if pd.notna(row['Paid In']) and row['Paid In'] > 0:
                payment = {
                    'source': 'mpesa_c2b',
                    'reference': row['Receipt No'],
                    'amount': float(row['Paid In']),
                    'currency': 'KES',
                    'transaction_date': self.parse_mpesa_datetime(row['Completion Time']),
                    'counterparty': self.extract_sender_info(row['Other Party Info']),
                    'memo': row['Details'],
                    'status': row['Transaction Status'],
                    'balance_after': float(row['Balance']) if pd.notna(row['Balance']) else None
                }
                payments.append(payment)
        
        return payments
    
    def extract_sender_info(self, party_info: str):
        """Extract sender details from M-Pesa party info"""
        # Format: "254712345678 - JOHN DOE"
        if ' - ' in party_info:
            phone, name = party_info.split(' - ', 1)
            return {
                'phone': phone.strip(),
                'name': name.strip(),
                'type': 'individual'
            }
        return {'raw': party_info, 'type': 'unknown'}

# Usage Example
adapter = MPesaC2BAdapter()
payments = adapter.parse_csv(mpesa_csv_content)
```

### **M-Pesa B2B Processing:**
```python
class MPesaB2BAdapter:
    def parse_statement(self, statement_content: str):
        """Parse M-Pesa B2B transaction statement"""
        payments = []
        
        # M-Pesa B2B format processing
        lines = statement_content.strip().split('\n')
        
        for line in lines[1:]:  # Skip header
            parts = line.split(',')
            if len(parts) >= 8 and parts[3] == 'Completed':
                payment = {
                    'source': 'mpesa_b2b',
                    'reference': parts[0],  # Transaction ID
                    'amount': float(parts[4]),
                    'currency': 'KES',
                    'transaction_date': self.parse_datetime(parts[1]),
                    'counterparty': {
                        'business_shortcode': parts[5],
                        'account_reference': parts[6],
                        'type': 'business'
                    },
                    'memo': parts[7] if len(parts) > 7 else '',
                    'transaction_type': 'B2B_PAYMENT'
                }
                payments.append(payment)
        
        return payments
```

---

## 🏦 Bank Statement Processing

### **Equity Bank CSV Adapter:**
```python
class EquityBankAdapter:
    def __init__(self):
        self.bank_code = 'EQUITY_KE'
        
    def parse_csv_statement(self, csv_content: str):
        """Parse Equity Bank CSV statement"""
        df = pd.read_csv(io.StringIO(csv_content))
        
        payments = []
        for _, row in df.iterrows():
            if row['Credit'] > 0:  # Only process credits (incoming payments)
                payment = {
                    'source': 'equity_bank',
                    'reference': row['Reference'],
                    'amount': float(row['Credit']),
                    'currency': 'KES',
                    'transaction_date': pd.to_datetime(row['Date']),
                    'counterparty': {
                        'name': row['Description'],
                        'account': self.extract_account_from_desc(row['Description']),
                        'type': 'bank_transfer'
                    },
                    'memo': row['Description'],
                    'balance_after': float(row['Balance']),
                    'bank_reference': row['Reference']
                }
                payments.append(payment)
        
        return payments
    
    def extract_account_from_desc(self, description: str):
        """Extract account number from transaction description"""
        # Pattern: "FROM: 1234567890 - CUSTOMER NAME"
        import re
        account_pattern = r'FROM:\s*(\d{10,})'
        match = re.search(account_pattern, description)
        return match.group(1) if match else None
```

### **Co-operative Bank MT940 Parser:**
```python
class CoopBankMT940Adapter:
    def parse_mt940(self, mt940_content: str):
        """Parse Co-operative Bank MT940 format"""
        payments = []
        current_transaction = {}
        
        for line in mt940_content.split('\n'):
            line = line.strip()
            
            if line.startswith(':61:'):
                # Transaction line: :61:YYMMDDMMDDCRAMT,Transaction Details
                transaction_data = line[4:]  # Remove :61:
                
                # Parse date and amount
                date_part = transaction_data[:6]  # YYMMDD
                amount_start = transaction_data.find('CR') + 2
                amount_end = transaction_data.find(',', amount_start)
                
                if amount_end > amount_start:
                    amount = float(transaction_data[amount_start:amount_end])
                    
                    payment = {
                        'source': 'coop_bank_mt940',
                        'amount': amount,
                        'currency': 'KES',
                        'transaction_date': self.parse_mt940_date(date_part),
                        'raw_mt940_line': line
                    }
                    payments.append(payment)
            
            elif line.startswith(':86:'):
                # Additional transaction details
                if payments:
                    details = line[4:]  # Remove :86:
                    payments[-1]['memo'] = details
                    payments[-1]['counterparty'] = self.extract_counterparty_mt940(details)
        
        return payments
```

---

## 📧 Payment Matching Logic for Kenya

### **Customer Alias Mapping for Kenya:**
```python
class KenyaCustomerMapper:
    def __init__(self):
        self.alias_map = {
            # Common M-Pesa name variations
            'JOHN DOE': ['JOHN', 'J DOE', 'JOHN D', 'DOE JOHN'],
            'MARY WANJIKU': ['MARY W', 'M WANJIKU', 'WANJIKU M'],
            
            # Business name variations  
            'EAST AFRICAN BREWERIES': ['EABL', 'EA BREWERIES', 'EAST AFR BREW'],
            'KENYA COMMERCIAL BANK': ['KCB', 'KCB BANK', 'KCB LTD'],
            
            # Common M-Pesa business shortcodes to company mapping
            '174379': 'SAFARICOM_LTD',
            '400200': 'EQUITY_BANK',
            '522522': 'KCB_BANK'
        }
    
    def find_customer_match(self, payment_counterparty: str, customer_list: list):
        """Find customer match using fuzzy matching and alias mapping"""
        from fuzzywuzzy import fuzz
        
        best_match = None
        best_score = 0
        
        for customer in customer_list:
            # Check exact alias matches first
            if payment_counterparty.upper() in self.alias_map.get(customer['name'].upper(), []):
                return customer, 100
            
            # Fuzzy matching
            score = fuzz.ratio(payment_counterparty.upper(), customer['name'].upper())
            if score > best_score and score > 85:  # 85% threshold
                best_match = customer
                best_score = score
        
        return best_match, best_score
```

### **Kenya-Specific Matching Rules:**
```python
class KenyaPaymentMatcher:
    def __init__(self, tolerance_percentage=0.02):
        self.tolerance = tolerance_percentage
        self.customer_mapper = KenyaCustomerMapper()
    
    def match_payment_to_invoice(self, payment: dict, open_invoices: list):
        """Match payment to open invoices using Kenya-specific logic"""
        matches = []
        
        for invoice in open_invoices:
            # Rule 1: Exact amount match
            if abs(payment['amount'] - invoice['amount_due']) < 0.01:
                matches.append({
                    'invoice': invoice,
                    'confidence': 0.95,
                    'rule': 'exact_amount',
                    'amount_to_apply': payment['amount']
                })
                continue
            
            # Rule 2: Amount within tolerance + customer match
            amount_diff = abs(payment['amount'] - invoice['amount_due'])
            if amount_diff <= (invoice['amount_due'] * self.tolerance):
                customer_match, match_score = self.customer_mapper.find_customer_match(
                    payment['counterparty']['name'], 
                    [invoice['customer']]
                )
                
                if customer_match and match_score > 85:
                    matches.append({
                        'invoice': invoice,
                        'confidence': 0.85 * (match_score / 100),
                        'rule': 'amount_tolerance_customer_match',
                        'amount_to_apply': min(payment['amount'], invoice['amount_due'])
                    })
            
            # Rule 3: M-Pesa reference number in invoice description
            if payment['source'].startswith('mpesa') and 'reference' in payment:
                if payment['reference'] in invoice.get('description', ''):
                    matches.append({
                        'invoice': invoice,
                        'confidence': 0.90,
                        'rule': 'mpesa_reference_match',
                        'amount_to_apply': min(payment['amount'], invoice['amount_due'])
                    })
        
        # Sort by confidence, return best match
        matches.sort(key=lambda x: x['confidence'], reverse=True)
        return matches
    
    def handle_overpayment(self, payment: dict, invoice: dict, overpayment_amount: float):
        """Handle overpayments common in M-Pesa transactions"""
        if overpayment_amount < 10:  # Small overpayments (< 10 KES) - likely rounding
            return {
                'action': 'apply_full_write_off_difference',
                'amount_to_apply': invoice['amount_due'],
                'write_off_amount': overpayment_amount,
                'reason': 'minor_overpayment_tolerance'
            }
        else:
            return {
                'action': 'apply_partial_create_credit',
                'amount_to_apply': invoice['amount_due'], 
                'credit_amount': overpayment_amount,
                'reason': 'overpayment_credit_memo'
            }
```

---

## 🔗 ERP Integration Updates

### **Enhanced SAP Integration for Kenya:**
```python
class EABLKenyaSAPIntegration(EABLSAPIntegration):
    def __init__(self, config):
        super().__init__(config)
        self.kenya_config = config['kenya_specific']
    
    def post_mpesa_payment(self, payment: dict, matched_invoice: dict):
        """Post M-Pesa payment to SAP with Kenya-specific handling"""
        
        # Create payment document
        payment_doc = {
            'DocumentType': 'DZ',  # Payment document
            'CompanyCode': '1000',  # Kenya company code
            'DocumentDate': payment['transaction_date'].strftime('%Y-%m-%d'),
            'PostingDate': datetime.now().strftime('%Y-%m-%d'),
            'Reference': f"MPESA-{payment['reference']}",
            'DocumentHeaderText': f"M-Pesa Payment - {payment['counterparty']['name']}",
            
            # Payment details
            'PaymentMethod': 'M',  # M-Pesa payment method
            'BankAccount': self.kenya_config['mpesa_clearing_account'],
            'Amount': payment['amount'],
            'Currency': 'KES',
            
            # Customer application
            'Customer': matched_invoice['customer_code'],
            'InvoiceReference': matched_invoice['invoice_number'],
            'ApplicationAmount': min(payment['amount'], matched_invoice['amount_due']),
            
            # M-Pesa specific fields
            'MpesaTransactionId': payment['reference'],
            'MpesaSenderPhone': payment['counterparty'].get('phone', ''),
            'MpesaSenderName': payment['counterparty'].get('name', '')
        }
        
        return self.sap_connector.create_payment_document(payment_doc)
    
    def handle_partial_payment(self, payment: dict, invoice: dict, application_amount: float):
        """Handle partial payments common in Kenya"""
        remaining_amount = payment['amount'] - application_amount
        
        if remaining_amount > 5:  # Significant remainder
            # Create customer prepayment for remainder
            prepayment_doc = {
                'DocumentType': 'DZ',
                'CompanyCode': '1000', 
                'Customer': invoice['customer_code'],
                'Amount': remaining_amount,
                'Currency': 'KES',
                'Reference': f"MPESA-PREPAY-{payment['reference']}",
                'SpecialGLIndicator': 'A',  # Customer prepayment
                'Text': f"M-Pesa prepayment from {payment['counterparty']['name']}"
            }
            
            return self.sap_connector.create_prepayment_document(prepayment_doc)
        
        return None  # Small remainder - ignore
```

---

## 📊 Kenya-Specific Monitoring

### **M-Pesa Transaction Monitoring:**
```python
class KenyaPaymentMonitoring:
    def __init__(self):
        self.metrics = {
            'mpesa_processing_rate': Gauge('mpesa_transactions_per_hour'),
            'bank_processing_rate': Gauge('bank_transactions_per_hour'),
            'matching_accuracy': Gauge('payment_matching_accuracy_percent'),
            'sap_posting_success': Counter('sap_posting_success_total', ['source']),
            'exception_queue_depth': Gauge('exception_queue_depth')
        }
    
    def record_payment_processing(self, payment: dict, match_result: dict):
        """Record payment processing metrics"""
        source = payment['source']
        
        # Update source-specific metrics
        if source.startswith('mpesa'):
            self.metrics['mpesa_processing_rate'].inc()
        elif 'bank' in source:
            self.metrics['bank_processing_rate'].inc()
        
        # Record matching accuracy
        if match_result and match_result.get('confidence', 0) > 0.8:
            self.metrics['matching_accuracy'].set(match_result['confidence'] * 100)
        
        # Record SAP posting success
        if match_result.get('sap_posted'):
            self.metrics['sap_posting_success'].labels(source=source).inc()
```

---

## 🚨 Exception Handling for Kenya

### **Kenya-Specific Exception Types:**
```python
class KenyaExceptionHandler:
    def __init__(self):
        self.whatsapp_client = WhatsAppClient()
        self.email_client = EmailClient()
    
    def handle_exception(self, payment: dict, exception_type: str, details: dict):
        """Handle payment processing exceptions"""
        
        exception_handlers = {
            'mpesa_duplicate_reference': self.handle_mpesa_duplicate,
            'customer_not_found': self.handle_unknown_customer,
            'currency_mismatch': self.handle_currency_issue,
            'amount_too_large': self.handle_large_amount,
            'bank_format_error': self.handle_bank_format_error
        }
        
        handler = exception_handlers.get(exception_type, self.handle_generic_exception)
        return handler(payment, details)
    
    def handle_mpesa_duplicate(self, payment: dict, details: dict):
        """Handle M-Pesa duplicate transaction references"""
        # Check if this is a genuine duplicate or M-Pesa system retry
        existing_payment = self.find_existing_payment(payment['reference'])
        
        if existing_payment:
            # Compare amounts and dates
            if (existing_payment['amount'] == payment['amount'] and 
                abs((existing_payment['transaction_date'] - payment['transaction_date']).seconds) < 300):
                return {
                    'action': 'ignore_duplicate',
                    'reason': 'identical_payment_within_5_minutes'
                }
        
        # Queue for manual review
        return self.queue_for_manual_review(payment, 'potential_duplicate_mpesa')
    
    def handle_unknown_customer(self, payment: dict, details: dict):
        """Handle payments from unknown customers"""
        notification = {
            'type': 'unknown_customer',
            'payment_reference': payment['reference'],
            'amount': payment['amount'],
            'customer_info': payment['counterparty'],
            'message': f"Unknown customer payment: {payment['amount']} KES from {payment['counterparty']['name']}"
        }
        
        # Send WhatsApp to AR team
        self.whatsapp_client.send_message(
            phone="+254700123456",  # AR team WhatsApp
            message=notification['message']
        )
        
        return self.queue_for_manual_review(payment, 'unknown_customer')
```

---

## 📋 Implementation Checklist for Kenya

### **Week 1-2: Payment Source Integration**
- [ ] M-Pesa C2B CSV parser implemented
- [ ] M-Pesa B2B statement processor
- [ ] Equity Bank CSV adapter  
- [ ] Co-operative Bank MT940 parser
- [ ] KCB statement format handler
- [ ] Airtel Money export processor

### **Week 3-4: Matching Engine Enhancement**
- [ ] Kenya customer alias mapping
- [ ] Fuzzy matching for Kenyan names
- [ ] M-Pesa reference matching
- [ ] Currency tolerance handling (KES)
- [ ] Overpayment/underpayment rules
- [ ] Partial payment processing

### **Week 5-6: SAP Integration Updates**
- [ ] M-Pesa payment method configuration
- [ ] Kenya company code setup (1000)
- [ ] Customer prepayment handling
- [ ] Multi-currency posting (KES primary)
- [ ] M-Pesa clearing account setup
- [ ] Audit trail enhancement

### **Week 7-8: Monitoring and Exceptions**
- [ ] WhatsApp notification integration
- [ ] Kenya-specific monitoring dashboards
- [ ] Exception handling workflows
- [ ] Manual review queue interface
- [ ] Performance optimization for high M-Pesa volumes
- [ ] Cost tracking per payment source

---

**🇰🇪 This integration guide positions CashUp Agent as the premier cash application solution for the Kenyan market, with native support for M-Pesa, major banks, and local business practices.**