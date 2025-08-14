# shared/test_data.py
"""
Test data generation for CashAppAgent
Provides realistic test data for development and testing
"""

import random
import string
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from uuid import uuid4

from .models import (
    PaymentTransaction, Invoice, MatchResult, DocumentParsingResult,
    TransactionStatus, InvoiceStatus, DiscrepancyCode
)

class TestDataGenerator:
    """
    Generates realistic test data for CashAppAgent testing
    Provides various scenarios including edge cases
    """
    
    def __init__(self, seed: int = None):
        if seed:
            random.seed(seed)
        
        # Test data pools
        self.currencies = ['EUR', 'USD', 'GBP', 'CAD']
        self.customer_names = [
            'Acme Corp', 'Global Solutions Ltd', 'Tech Innovations Inc',
            'Manufacturing Co', 'Services Group', 'Digital Systems'
        ]
        self.invoice_prefixes = ['INV', 'INVOICE', 'PO', 'REF', 'ORDER', 'BILL']
    
    def create_payment_transaction(self, 
                                 amount: Decimal = None,
                                 currency: str = None,
                                 remittance_data: str = None,
                                 customer_identifier: str = None,
                                 document_uris: List[str] = None) -> PaymentTransaction:
        """
        Create test payment transaction
        
        Args:
            amount: Payment amount (random if None)
            currency: Currency code (random if None)
            remittance_data: Remittance text (generated if None)
            customer_identifier: Customer ID (generated if None)
            document_uris: Document URIs (generated if None)
            
        Returns:
            PaymentTransaction instance
        """
        if amount is None:
            amount = Decimal(f"{random.uniform(100, 50000):.2f}")
        
        if currency is None:
            currency = random.choice(self.currencies)
        
        if remittance_data is None:
            # Generate realistic remittance data
            invoice_ids = self.create_test_invoice_ids(random.randint(1, 3))
            remittance_data = f"Payment for {' '.join(invoice_ids)} - {random.choice(self.customer_names)}"
        
        if customer_identifier is None:
            customer_identifier = f"CUST-{random.randint(1000, 9999)}"
        
        if document_uris is None:
            document_uris = self.create_test_document_uris(random.randint(0, 2))
        
        transaction_id = f"TXN-{int(datetime.now(timezone.utc).timestamp())}-{random.randint(1000, 9999)}"
        
        return PaymentTransaction(
            transaction_id=transaction_id,
            source_account_ref=f"ACC-{random.randint(100000, 999999)}",
            amount=amount,
            currency=currency,
            value_date=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 7)),
            raw_remittance_data=remittance_data,
            customer_identifier=customer_identifier,
            associated_document_uris=document_uris,
            processing_status=TransactionStatus.PENDING
        )
    
    def create_invoice(self, 
                      invoice_id: str = None,
                      customer_id: str = None,
                      amount_due: Decimal = None,
                      currency: str = None,
                      status: InvoiceStatus = None) -> Invoice:
        """
        Create test invoice
        
        Args:
            invoice_id: Invoice ID (generated if None)
            customer_id: Customer ID (generated if None)
            amount_due: Amount due (random if None)
            currency: Currency code (random if None)
            status: Invoice status (open if None)
            
        Returns:
            Invoice instance
        """
        if invoice_id is None:
            prefix = random.choice(self.invoice_prefixes)
            number = random.randint(10000, 99999)
            invoice_id = f"{prefix}-{number}"
        
        if customer_id is None:
            customer_id = f"CUST-{random.randint(1000, 9999)}"
        
        if amount_due is None:
            amount_due = Decimal(f"{random.uniform(100, 10000):.2f}")
        
        if currency is None:
            currency = random.choice(self.currencies)
        
        if status is None:
            status = InvoiceStatus.OPEN
        
        original_amount = amount_due if status == InvoiceStatus.OPEN else amount_due + Decimal(f"{random.uniform(0, 1000):.2f}")
        
        return Invoice(
            invoice_id=invoice_id,
            customer_id=customer_id,
            customer_name=random.choice(self.customer_names),
            amount_due=amount_due,
            original_amount=original_amount,
            currency=currency,
            status=status,
            due_date=datetime.now(timezone.utc) + timedelta(days=random.randint(1, 60)),
            created_date=datetime.now(timezone.utc) - timedelta(days=random.randint(1, 365))
        )
    
    def create_match_result(self, 
                           transaction_id: str = None,
                           status: TransactionStatus = None,
                           matched_pairs: Dict[str, Decimal] = None,
                           requires_review: bool = None) -> MatchResult:
        """
        Create test match result
        
        Args:
            transaction_id: Transaction ID (generated if None)
            status: Match status (random if None)
            matched_pairs: Invoice matches (generated if None)
            requires_review: Review flag (random if None)
            
        Returns:
            MatchResult instance
        """
        if transaction_id is None:
            transaction_id = f"TXN-{int(datetime.now(timezone.utc).timestamp())}-{random.randint(1000, 9999)}"
        
        if status is None:
            status = random.choice(list(TransactionStatus))
        
        if matched_pairs is None:
            if status in [TransactionStatus.MATCHED, TransactionStatus.PARTIALLY_MATCHED]:
                # Generate some matches
                invoice_count = random.randint(1, 3)
                matched_pairs = {}
                for i in range(invoice_count):
                    invoice_id = f"INV-{random.randint(10000, 99999)}"
                    amount = Decimal(f"{random.uniform(100, 5000):.2f}")
                    matched_pairs[invoice_id] = amount
            else:
                matched_pairs = {}
        
        if requires_review is None:
            requires_review = status in [TransactionStatus.UNMATCHED, TransactionStatus.ERROR]
        
        total_matched = sum(matched_pairs.values()) if matched_pairs else Decimal('0')
        payment_amount = total_matched + Decimal(f"{random.uniform(0, 1000):.2f}")
        unapplied_amount = payment_amount - total_matched
        
        # Determine discrepancy code
        discrepancy_code = None
        if status == TransactionStatus.PARTIALLY_MATCHED:
            discrepancy_code = DiscrepancyCode.SHORT_PAYMENT
        elif unapplied_amount > 0 and status == TransactionStatus.MATCHED:
            discrepancy_code = DiscrepancyCode.OVER_PAYMENT
        elif status == TransactionStatus.UNMATCHED:
            discrepancy_code = DiscrepancyCode.INVALID_INVOICE
        
        return MatchResult(
            transaction_id=transaction_id,
            status=status,
            matched_pairs=matched_pairs,
            unapplied_amount=unapplied_amount,
            discrepancy_code=discrepancy_code,
            log_entry=f"Test match result for {transaction_id}",
            confidence_score=random.uniform(0.6, 1.0),
            processing_time_ms=random.randint(100, 5000),
            requires_human_review=requires_review
        )
    
    def create_document_parsing_result(self, 
                                     document_uri: str = None,
                                     invoice_ids: List[str] = None,
                                     confidence_score: float = None) -> DocumentParsingResult:
        """Create test document parsing result"""
        if document_uri is None:
            document_uri = f"https://storage.blob.core.windows.net/documents/test-{uuid4()}.pdf"
        
        if invoice_ids is None:
            invoice_ids = self.create_test_invoice_ids(random.randint(1, 3))
        
        if confidence_score is None:
            confidence_score = random.uniform(0.7, 0.95)
        
        return DocumentParsingResult(
            document_uri=document_uri,
            invoice_ids=invoice_ids,
            confidence_score=confidence_score,
            processing_time_ms=random.randint(500, 3000)
        )
    
    def create_test_invoice_ids(self, count: int = 3) -> List[str]:
        """Create list of test invoice IDs"""
        invoice_ids = []
        for _ in range(count):
            prefix = random.choice(self.invoice_prefixes)
            number = random.randint(10000, 99999)
            invoice_ids.append(f"{prefix}-{number}")
        return invoice_ids
    
    def create_test_document_uris(self, count: int = 2) -> List[str]:
        """Create list of test document URIs"""
        return [
            f"https://storage.blob.core.windows.net/documents/test-{uuid4()}.pdf"
            for _ in range(count)
        ]
    
    def create_test_dataset(self, 
                           transaction_count: int = 50,
                           include_edge_cases: bool = True) -> Dict[str, List[Any]]:
        """
        Create comprehensive test dataset
        
        Args:
            transaction_count: Number of transactions to generate
            include_edge_cases: Include edge cases and error scenarios
            
        Returns:
            Dictionary with all test data
        """
        transactions = []
        invoices = []
        match_results = []
        
        # Generate base transactions
        for i in range(transaction_count):
            # Create transaction
            transaction = self.create_payment_transaction()
            transactions.append(transaction)
            
            # Create corresponding invoices
            invoice_count = random.randint(1, 3)
            txn_invoices = []
            total_invoice_amount = Decimal('0')
            
            for j in range(invoice_count):
                invoice = self.create_invoice(
                    customer_id=transaction.customer_identifier,
                    currency=transaction.currency
                )
                invoices.append(invoice)
                txn_invoices.append(invoice)
                total_invoice_amount += invoice.amount_due
            
            # Create match result
            if total_invoice_amount == transaction.amount:
                # Perfect match
                status = TransactionStatus.MATCHED
                matched_pairs = {inv.invoice_id: inv.amount_due for inv in txn_invoices}
                unapplied_amount = Decimal('0')
                discrepancy_code = None
            elif total_invoice_amount > transaction.amount:
                # Short payment
                status = TransactionStatus.PARTIALLY_MATCHED
                matched_pairs = {}
                remaining = transaction.amount
                for inv in txn_invoices:
                    if remaining <= 0:
                        break
                    applied = min(remaining, inv.amount_due)
                    matched_pairs[inv.invoice_id] = applied
                    remaining -= applied
                unapplied_amount = Decimal('0')
                discrepancy_code = DiscrepancyCode.SHORT_PAYMENT
            else:
                # Overpayment
                status = TransactionStatus.MATCHED
                matched_pairs = {inv.invoice_id: inv.amount_due for inv in txn_invoices}
                unapplied_amount = transaction.amount - total_invoice_amount
                discrepancy_code = DiscrepancyCode.OVER_PAYMENT
            
            match_result = MatchResult(
                transaction_id=transaction.transaction_id,
                status=status,
                matched_pairs=matched_pairs,
                unapplied_amount=unapplied_amount,
                discrepancy_code=discrepancy_code,
                log_entry=f"Test match: {status.value}",
                confidence_score=random.uniform(0.8, 0.95),
                processing_time_ms=random.randint(100, 2000),
                requires_human_review=random.choice([True, False])
            )
            match_results.append(match_result)
        
        # Add edge cases if requested
        if include_edge_cases:
            edge_cases = self._create_edge_case_data()
            transactions.extend(edge_cases['transactions'])
            invoices.extend(edge_cases['invoices'])
            match_results.extend(edge_cases['match_results'])
        
        return {
            'transactions': transactions,
            'invoices': invoices,
            'match_results': match_results,
            'summary': {
                'total_transactions': len(transactions),
                'total_invoices': len(invoices),
                'total_match_results': len(match_results),
                'currencies': list(set(t.currency for t in transactions)),
                'generated_at': datetime.now(timezone.utc).isoformat()
            }
        }
    
    def _create_edge_case_data(self) -> Dict[str, List[Any]]:
        """Create edge case test data"""
        edge_transactions = []
        edge_invoices = []
        edge_match_results = []
        
        # Large amount transaction
        large_txn = self.create_payment_transaction(
            amount=Decimal('100000.00'),
            remittance_data='Large payment for INV-LARGE-001'
        )
        edge_transactions.append(large_txn)
        
        # Very small amount transaction
        small_txn = self.create_payment_transaction(
            amount=Decimal('0.01'),
            remittance_data='Minimal payment for INV-SMALL-001'
        )
        edge_transactions.append(small_txn)
        
        # Transaction with no remittance data
        no_remittance_txn = self.create_payment_transaction(
            remittance_data='',
            customer_identifier=None
        )
        edge_transactions.append(no_remittance_txn)
        
        # Transaction with multiple currencies (error case)
        multi_currency_txn = self.create_payment_transaction(
            remittance_data='Payment for INV-12345 USD and INV-12346 EUR'
        )
        edge_transactions.append(multi_currency_txn)
        
        # Create corresponding match results for edge cases
        for txn in edge_transactions:
            if txn.amount >= Decimal('50000'):
                # Large amounts require review
                match_result = self.create_match_result(
                    transaction_id=txn.transaction_id,
                    status=TransactionStatus.REQUIRES_REVIEW,
                    requires_review=True
                )
            elif txn.amount <= Decimal('1'):
                # Small amounts might be unmatched
                match_result = self.create_match_result(
                    transaction_id=txn.transaction_id,
                    status=TransactionStatus.UNMATCHED,
                    matched_pairs={},
                    requires_review=True
                )
            elif not txn.raw_remittance_data:
                # No remittance data
                match_result = self.create_match_result(
                    transaction_id=txn.transaction_id,
                    status=TransactionStatus.UNMATCHED,
                    matched_pairs={},
                    requires_review=True
                )
            else:
                # Other edge cases
                match_result = self.create_match_result(
                    transaction_id=txn.transaction_id,
                    status=TransactionStatus.ERROR,
                    matched_pairs={},
                    requires_review=True
                )
            
            edge_match_results.append(match_result)
        
        return {
            'transactions': edge_transactions,
            'invoices': edge_invoices,
            'match_results': edge_match_results
        }
    
    def create_test_client_data(self) -> Dict[str, Any]:
        """Create test client configuration data"""
        client_id = f"CLIENT-{random.randint(1000, 9999)}"
        
        return {
            'client_id': client_id,
            'client_name': f"Test Client {client_id}",
            'erp_connections': [
                {
                    'system_type': 'netsuite',
                    'endpoint_url': 'https://test.netsuite.com/api',
                    'authentication': {
                        'type': 'oauth2',
                        'client_id': 'test-client-id',
                        'client_secret': 'test-client-secret'
                    }
                }
            ],
            'primary_contact_email': f'finance@{client_id.lower()}.com',
            'finance_team_emails': [
                f'ap@{client_id.lower()}.com',
                f'controller@{client_id.lower()}.com'
            ],
            'matching_rules': {
                'min_confidence_threshold': 0.8,
                'auto_apply_threshold': 5000.0,
                'allow_partial_payments': True,
                'tolerance_percentage': 0.02
            }
        }
    
    def create_performance_test_data(self, transaction_count: int = 1000) -> List[PaymentTransaction]:
        """
        Create large dataset for performance testing
        
        Args:
            transaction_count: Number of transactions to generate
            
        Returns:
            List of payment transactions
        """
        transactions = []
        
        for i in range(transaction_count):
            # Create realistic distribution of amounts
            if i % 100 == 0:
                # 1% large transactions
                amount = Decimal(f"{random.uniform(50000, 200000):.2f}")
            elif i % 10 == 0:
                # 10% medium transactions
                amount = Decimal(f"{random.uniform(5000, 50000):.2f}")
            else:
                # 89% small transactions
                amount = Decimal(f"{random.uniform(100, 5000):.2f}")
            
            # Create realistic remittance data
            invoice_count = random.choices([1, 2, 3], weights=[70, 25, 5])[0]  # Most payments are for 1 invoice
            invoice_ids = self.create_test_invoice_ids(invoice_count)
            
            transaction = self.create_payment_transaction(
                amount=amount,
                remittance_data=f"Payment for {' '.join(invoice_ids)} - Batch {i//100}"
            )
            
            transactions.append(transaction)
        
        return transactions
    
    def create_synthetic_documents(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Create synthetic document content for testing
        
        Args:
            count: Number of documents to create
            
        Returns:
            List of document data
        """
        documents = []
        
        for i in range(count):
            doc_type = random.choice(['invoice', 'remittance_advice', 'statement'])
            
            if doc_type == 'invoice':
                content = self._create_invoice_document_content()
            elif doc_type == 'remittance_advice':
                content = self._create_remittance_document_content()
            else:
                content = self._create_statement_document_content()
            
            documents.append({
                'document_id': f"DOC-{i:04d}",
                'document_type': doc_type,
                'content': content,
                'uri': f"https://storage.blob.core.windows.net/test-docs/doc-{i:04d}.pdf"
            })
        
        return documents
    
    def _create_invoice_document_content(self) -> str:
        """Create synthetic invoice document content"""
        invoice_id = f"INV-{random.randint(10000, 99999)}"
        customer = random.choice(self.customer_names)
        amount = random.uniform(1000, 10000)
        currency = random.choice(self.currencies)
        
        return f"""
INVOICE {invoice_id}

Bill To: {customer}
Date: {datetime.now().strftime('%Y-%m-%d')}
Due Date: {(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')}

Description                     Amount
Professional Services          {amount:.2f} {currency}

Subtotal:                      {amount:.2f} {currency}
Tax:                           {amount * 0.2:.2f} {currency}
Total:                         {amount * 1.2:.2f} {currency}

Please reference invoice {invoice_id} with your payment.
        """.strip()
    
    def _create_remittance_document_content(self) -> str:
        """Create synthetic remittance advice content"""
        ref_ids = self.create_test_invoice_ids(random.randint(1, 3))
        customer = random.choice(self.customer_names)
        total_amount = sum(random.uniform(1000, 5000) for _ in ref_ids)
        
        return f"""
REMITTANCE ADVICE

From: {customer}
Date: {datetime.now().strftime('%Y-%m-%d')}

Payment Details:
Reference: {' '.join(ref_ids)}
Total Amount: {total_amount:.2f} EUR

This payment covers the following invoices:
{chr(10).join(f"- {ref_id}: {random.uniform(1000, 5000):.2f} EUR" for ref_id in ref_ids)}

Bank Reference: TXN-{random.randint(100000, 999999)}
        """.strip()
    
    def _create_statement_document_content(self) -> str:
        """Create synthetic statement document content"""
        customer = random.choice(self.customer_names)
        
        return f"""
ACCOUNT STATEMENT

Customer: {customer}
Statement Date: {datetime.now().strftime('%Y-%m-%d')}
Account Number: {random.randint(100000, 999999)}

Outstanding Invoices:
{chr(10).join(f"INV-{random.randint(10000, 99999)}: {random.uniform(1000, 10000):.2f} EUR" for _ in range(3))}

Total Outstanding: {random.uniform(10000, 50000):.2f} EUR
        """.strip()
    
    def export_test_data_to_sql(self, test_data: Dict[str, List[Any]], file_path: str):
        """
        Export test data as SQL INSERT statements
        
        Args:
            test_data: Test data from create_test_dataset
            file_path: Path to write SQL file
        """
        sql_statements = []
        
        # Payment transactions
        for txn in test_data['transactions']:
            sql_statements.append(f"""
INSERT INTO payment_transactions (transaction_id, source_account_ref, amount, currency, value_date, raw_remittance_data, customer_identifier, processing_status)
VALUES ('{txn.transaction_id}', '{txn.source_account_ref}', {txn.amount}, '{txn.currency}', '{txn.value_date.isoformat()}', '{txn.raw_remittance_data}', '{txn.customer_identifier}', '{txn.processing_status.value}');
            """.strip())
        
        # Invoices
        for inv in test_data['invoices']:
            sql_statements.append(f"""
INSERT INTO invoices (invoice_id, customer_id, customer_name, amount_due, original_amount, currency, status, due_date, created_date, erp_system)
VALUES ('{inv.invoice_id}', '{inv.customer_id}', '{inv.customer_name}', {inv.amount_due}, {inv.original_amount}, '{inv.currency}', '{inv.status.value}', '{inv.due_date.isoformat()}', '{inv.created_date.isoformat()}', 'test_erp');
            """.strip())
        
        # Write to file
        with open(file_path, 'w') as f:
            f.write("-- CashAppAgent Test Data\n")
            f.write("-- Generated test data for development and testing\n\n")
            f.write("BEGIN;\n\n")
            f.write('\n\n'.join(sql_statements))
            f.write("\n\nCOMMIT;\n")
        
        print(f"Test data exported to: {file_path}")

# Utility functions for test setup
def setup_test_database():
    """Setup test database with sample data"""
    generator = TestDataGenerator(seed=12345)  # Reproducible test data
    test_data = generator.create_test_dataset(transaction_count=20)
    
    # Export to SQL file for manual loading
    generator.export_test_data_to_sql(test_data, "test_data.sql")
    
    return test_data

def create_load_test_data(transaction_count: int = 1000):
    """Create data for load testing"""
    generator = TestDataGenerator()
    return generator.create_performance_test_data(transaction_count)

# Command line utility
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "setup":
            setup_test_database()
        elif sys.argv[1] == "load" and len(sys.argv) > 2:
            count = int(sys.argv[2])
            transactions = create_load_test_data(count)
            print(f"Generated {len(transactions)} transactions for load testing")
    else:
        # Default: create small test dataset
        generator = TestDataGenerator()
        data = generator.create_test_dataset(10)
        print(f"Generated test data: {data['summary']}")