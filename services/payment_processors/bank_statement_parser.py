#!/usr/bin/env python3
"""
Kenya Bank Statement Parsers
Handles major Kenyan banks: Equity, KCB, Co-op, Absa, Stanbic, Family Bank, etc.
"""

import pandas as pd
import re
from datetime import datetime
from typing import Dict, List, Optional, Union
import io
import logging
from dataclasses import dataclass
from abc import ABC, abstractmethod

from .mobile_money_parser import PaymentTransaction

class BankStatementParser(ABC):
    """Abstract base class for bank statement parsers"""
    
    def __init__(self, bank_name: str, bank_code: str):
        self.bank_name = bank_name
        self.bank_code = bank_code
        self.logger = logging.getLogger(__name__)
    
    @abstractmethod
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse bank statement and return standardized transactions"""
        pass
    
    def normalize_amount(self, amount_str: str) -> float:
        """Normalize amount string to float"""
        if pd.isna(amount_str) or amount_str == '':
            return 0.0
        
        # Remove currency symbols and commas
        amount_str = str(amount_str).replace('KES', '').replace('Ksh', '').replace(',', '').strip()
        
        # Handle negative amounts in parentheses
        if amount_str.startswith('(') and amount_str.endswith(')'):
            amount_str = '-' + amount_str[1:-1]
        
        try:
            return float(amount_str)
        except ValueError:
            self.logger.warning(f"Could not parse amount: {amount_str}")
            return 0.0
    
    def parse_date(self, date_str: str) -> datetime:
        """Parse various date formats used by Kenyan banks"""
        date_str = str(date_str).strip()
        
        formats = [
            '%d/%m/%Y',           # 15/08/2024
            '%d-%m-%Y',           # 15-08-2024
            '%Y-%m-%d',           # 2024-08-15
            '%d/%m/%y',           # 15/08/24
            '%d-%m-%y',           # 15-08-24
            '%d %b %Y',           # 15 Aug 2024
            '%d-%b-%Y',           # 15-Aug-2024
            '%Y/%m/%d',           # 2024/08/15
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        self.logger.warning(f"Could not parse date: {date_str}, using current date")
        return datetime.now()

class EquityBankParser(BankStatementParser):
    """Equity Bank statement parser"""
    
    def __init__(self):
        super().__init__("Equity Bank", "EQBNKE")
    
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse Equity Bank CSV/Excel statement"""
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        transactions = []
        
        try:
            # Try CSV format first
            df = pd.read_csv(io.StringIO(content))
            
            # Map common Equity Bank column names
            column_mapping = {
                'Date': ['Date', 'Transaction Date', 'Value Date'],
                'Description': ['Description', 'Details', 'Narrative', 'Transaction Details'],
                'Reference': ['Reference', 'Ref', 'Transaction Reference', 'Cheque Number'],
                'Debit': ['Debit', 'Dr', 'Withdrawal', 'Out'],
                'Credit': ['Credit', 'Cr', 'Deposit', 'In'],
                'Balance': ['Balance', 'Running Balance', 'Account Balance']
            }
            
            # Find actual column names
            actual_columns = {}
            for standard_name, possible_names in column_mapping.items():
                for possible_name in possible_names:
                    if possible_name in df.columns:
                        actual_columns[standard_name] = possible_name
                        break
            
            for _, row in df.iterrows():
                # Process credit transactions (money coming in)
                credit_amount = self.normalize_amount(row.get(actual_columns.get('Credit', ''), 0))
                
                if credit_amount > 0:
                    transaction = PaymentTransaction(
                        source=f"{self.bank_code.lower()}_bank",
                        transaction_id=self._generate_transaction_id(row, actual_columns),
                        amount=credit_amount,
                        currency='KES',
                        transaction_date=self.parse_date(row[actual_columns['Date']]),
                        counterparty=self._parse_equity_counterparty(
                            row.get(actual_columns.get('Description', ''), '')
                        ),
                        memo=str(row.get(actual_columns.get('Description', ''), '')),
                        status='COMPLETED',
                        balance_after=self.normalize_amount(row.get(actual_columns.get('Balance', ''), None)),
                        raw_data=row.to_dict()
                    )
                    transactions.append(transaction)
        
        except Exception as e:
            self.logger.error(f"Error parsing Equity Bank statement: {e}")
            # Try alternative parsing methods
            transactions.extend(self._parse_equity_text_format(content))
        
        return transactions
    
    def _generate_transaction_id(self, row: pd.Series, columns: Dict) -> str:
        """Generate transaction ID from available data"""
        ref = row.get(columns.get('Reference', ''), '')
        if ref and str(ref) != 'nan':
            return f"EQB_{ref}"
        
        # Fallback: generate from date and amount
        date_str = str(row.get(columns.get('Date', ''), datetime.now().strftime('%Y%m%d')))
        amount = str(row.get(columns.get('Credit', ''), '0')).replace('.', '').replace(',', '')
        return f"EQB_{date_str}_{amount}"
    
    def _parse_equity_counterparty(self, description: str) -> Dict:
        """Parse counterparty information from Equity Bank description"""
        if not description:
            return {'type': 'unknown'}
        
        description = str(description).upper()
        
        # Common patterns in Equity Bank descriptions
        patterns = [
            # Mobile money patterns
            (r'MPESA.*?(\+?254\d{9})', 'mpesa_transfer'),
            (r'AIRTEL.*?(\+?254\d{9})', 'airtel_money'),
            
            # Bank transfer patterns
            (r'FROM\s+([A-Z\s]+)\s+A/C\s+(\d+)', 'bank_transfer'),
            (r'RTGS.*?FROM\s+([A-Z\s]+)', 'rtgs_transfer'),
            (r'EFT.*?FROM\s+([A-Z\s]+)', 'eft_transfer'),
            
            # Cheque patterns
            (r'CHQ.*?(\d+)', 'cheque'),
            
            # Standing order patterns
            (r'STANDING ORDER.*?FROM\s+([A-Z\s]+)', 'standing_order'),
        ]
        
        for pattern, transfer_type in patterns:
            match = re.search(pattern, description)
            if match:
                if transfer_type == 'bank_transfer':
                    return {
                        'name': match.group(1).strip(),
                        'account': match.group(2) if len(match.groups()) > 1 else None,
                        'type': transfer_type
                    }
                elif transfer_type in ['mpesa_transfer', 'airtel_money']:
                    return {
                        'phone': match.group(1),
                        'type': transfer_type,
                        'name': self._extract_name_from_description(description)
                    }
                else:
                    return {
                        'reference': match.group(1),
                        'type': transfer_type,
                        'name': self._extract_name_from_description(description)
                    }
        
        # If no pattern matches, extract any name-like strings
        return {
            'name': self._extract_name_from_description(description),
            'type': 'bank_transfer',
            'raw_description': description
        }
    
    def _extract_name_from_description(self, description: str) -> str:
        """Extract person/company name from transaction description"""
        # Remove common banking terms
        terms_to_remove = [
            'MPESA', 'AIRTEL', 'FROM', 'TO', 'A/C', 'CHQ', 'RTGS', 'EFT',
            'STANDING ORDER', 'TRANSFER', 'DEPOSIT', 'WITHDRAWAL'
        ]
        
        cleaned = description
        for term in terms_to_remove:
            cleaned = cleaned.replace(term, ' ')
        
        # Extract words that look like names (2+ characters, mostly letters)
        words = [word.strip() for word in cleaned.split() if len(word) > 1 and word.isalpha()]
        
        return ' '.join(words[:3]) if words else 'UNKNOWN'  # Take first 3 name words
    
    def _parse_equity_text_format(self, content: str) -> List[PaymentTransaction]:
        """Parse Equity Bank text/PDF format as fallback"""
        transactions = []
        lines = content.split('\n')
        
        for line in lines:
            # Look for credit entries (money coming in)
            credit_pattern = r'(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+Cr'
            match = re.search(credit_pattern, line)
            
            if match:
                transaction = PaymentTransaction(
                    source=f"{self.bank_code.lower()}_bank",
                    transaction_id=f"EQB_TEXT_{len(transactions)}",
                    amount=float(match.group(3).replace(',', '')),
                    currency='KES',
                    transaction_date=self.parse_date(match.group(1)),
                    counterparty=self._parse_equity_counterparty(match.group(2)),
                    memo=match.group(2).strip(),
                    status='COMPLETED'
                )
                transactions.append(transaction)
        
        return transactions

class KCBParser(BankStatementParser):
    """Kenya Commercial Bank statement parser"""
    
    def __init__(self):
        super().__init__("Kenya Commercial Bank", "KCBLKE")
    
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse KCB statement"""
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        transactions = []
        
        try:
            # KCB typically uses tab-separated or CSV format
            separator = '\t' if '\t' in content else ','
            df = pd.read_csv(io.StringIO(content), sep=separator)
            
            # KCB column mapping
            for _, row in df.iterrows():
                # Look for credit entries
                if 'Credit' in df.columns and pd.notna(row['Credit']) and float(row['Credit']) > 0:
                    transaction = PaymentTransaction(
                        source=f"{self.bank_code.lower()}_bank",
                        transaction_id=self._generate_kcb_id(row),
                        amount=float(row['Credit']),
                        currency='KES',
                        transaction_date=self.parse_date(row['Date']),
                        counterparty=self._parse_kcb_counterparty(row.get('Description', '')),
                        memo=str(row.get('Description', '')),
                        status='COMPLETED',
                        balance_after=self.normalize_amount(row.get('Balance', None)),
                        raw_data=row.to_dict()
                    )
                    transactions.append(transaction)
        
        except Exception as e:
            self.logger.error(f"Error parsing KCB statement: {e}")
        
        return transactions
    
    def _generate_kcb_id(self, row: pd.Series) -> str:
        """Generate KCB transaction ID"""
        ref = row.get('Reference', '')
        if ref and str(ref) != 'nan':
            return f"KCB_{ref}"
        
        date_str = str(row.get('Date', datetime.now().strftime('%Y%m%d')))
        amount = str(row.get('Credit', '0')).replace('.', '').replace(',', '')
        return f"KCB_{date_str}_{amount}"
    
    def _parse_kcb_counterparty(self, description: str) -> Dict:
        """Parse KCB transaction description"""
        if not description:
            return {'type': 'unknown'}
        
        description = str(description).upper()
        
        # KCB-specific patterns
        if 'MPESA' in description:
            phone_match = re.search(r'(\+?254\d{9})', description)
            return {
                'phone': phone_match.group(1) if phone_match else None,
                'type': 'mpesa_transfer',
                'name': self._extract_name_from_description(description)
            }
        
        if 'RTGS' in description or 'EFT' in description:
            name_match = re.search(r'FROM\s+([A-Z\s]+)', description)
            return {
                'name': name_match.group(1).strip() if name_match else 'UNKNOWN',
                'type': 'bank_transfer'
            }
        
        return {
            'name': self._extract_name_from_description(description),
            'type': 'bank_transfer',
            'raw_description': description
        }

class CooperativeBankParser(BankStatementParser):
    """Co-operative Bank statement parser (supports MT940 format)"""
    
    def __init__(self):
        super().__init__("Co-operative Bank", "COOPKE")
    
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse Co-op Bank statement (CSV or MT940)"""
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        transactions = []
        
        # Check if it's MT940 format
        if self._is_mt940_format(content):
            transactions.extend(self._parse_mt940_format(content))
        else:
            # Try CSV format
            transactions.extend(self._parse_coop_csv(content))
        
        return transactions
    
    def _is_mt940_format(self, content: str) -> bool:
        """Check if content is MT940 format"""
        return ':20:' in content or ':61:' in content or ':86:' in content
    
    def _parse_mt940_format(self, content: str) -> List[PaymentTransaction]:
        """Parse Co-op Bank MT940 format"""
        transactions = []
        current_transaction = {}
        
        for line in content.split('\n'):
            line = line.strip()
            
            if line.startswith(':61:'):
                # Transaction line: :61:YYMMDDMMDDCRAMT,Transaction Details
                if current_transaction:
                    # Process previous transaction
                    if 'amount' in current_transaction and current_transaction['amount'] > 0:
                        transactions.append(self._create_mt940_transaction(current_transaction))
                
                # Parse new transaction
                current_transaction = self._parse_mt940_transaction_line(line)
            
            elif line.startswith(':86:') and current_transaction:
                # Additional transaction details
                current_transaction['description'] = line[4:]  # Remove :86:
        
        # Process last transaction
        if current_transaction and 'amount' in current_transaction:
            transactions.append(self._create_mt940_transaction(current_transaction))
        
        return transactions
    
    def _parse_mt940_transaction_line(self, line: str) -> Dict:
        """Parse MT940 :61: transaction line"""
        transaction_data = line[4:]  # Remove :61:
        
        try:
            # Parse date (positions 0-5: YYMMDD)
            date_part = transaction_data[:6]
            
            # Find amount (look for CR followed by amount)
            cr_pos = transaction_data.find('CR')
            if cr_pos > 0:
                amount_start = cr_pos + 2
                # Amount ends at next non-numeric character
                amount_str = ''
                for char in transaction_data[amount_start:]:
                    if char.isdigit() or char in ',.':
                        amount_str += char
                    else:
                        break
                
                return {
                    'date': self._parse_mt940_date(date_part),
                    'amount': float(amount_str.replace(',', '')) if amount_str else 0,
                    'raw_line': line
                }
        except Exception as e:
            self.logger.error(f"Error parsing MT940 line: {e}")
        
        return {}
    
    def _parse_mt940_date(self, date_str: str) -> datetime:
        """Parse MT940 date format (YYMMDD)"""
        try:
            year = int('20' + date_str[:2])  # Assume 20xx
            month = int(date_str[2:4])
            day = int(date_str[4:6])
            return datetime(year, month, day)
        except ValueError:
            return datetime.now()
    
    def _create_mt940_transaction(self, transaction_data: Dict) -> PaymentTransaction:
        """Create PaymentTransaction from MT940 data"""
        return PaymentTransaction(
            source=f"{self.bank_code.lower()}_bank_mt940",
            transaction_id=f"COOP_MT940_{transaction_data['date'].strftime('%Y%m%d')}_{int(transaction_data['amount'])}",
            amount=transaction_data['amount'],
            currency='KES',
            transaction_date=transaction_data['date'],
            counterparty=self._parse_coop_counterparty(transaction_data.get('description', '')),
            memo=transaction_data.get('description', ''),
            status='COMPLETED',
            raw_data=transaction_data
        )
    
    def _parse_coop_csv(self, content: str) -> List[PaymentTransaction]:
        """Parse Co-op Bank CSV format"""
        transactions = []
        
        try:
            df = pd.read_csv(io.StringIO(content))
            
            for _, row in df.iterrows():
                credit_amount = self.normalize_amount(row.get('Credit', 0))
                if credit_amount > 0:
                    transaction = PaymentTransaction(
                        source=f"{self.bank_code.lower()}_bank",
                        transaction_id=f"COOP_{row.get('Reference', len(transactions))}",
                        amount=credit_amount,
                        currency='KES',
                        transaction_date=self.parse_date(row['Date']),
                        counterparty=self._parse_coop_counterparty(row.get('Description', '')),
                        memo=str(row.get('Description', '')),
                        status='COMPLETED',
                        balance_after=self.normalize_amount(row.get('Balance', None)),
                        raw_data=row.to_dict()
                    )
                    transactions.append(transaction)
        
        except Exception as e:
            self.logger.error(f"Error parsing Co-op CSV: {e}")
        
        return transactions
    
    def _parse_coop_counterparty(self, description: str) -> Dict:
        """Parse Co-op Bank counterparty info"""
        if not description:
            return {'type': 'unknown'}
        
        description = str(description).upper()
        
        # Co-op specific patterns
        if 'MOBILE MONEY' in description or 'MSHWARI' in description:
            return {
                'type': 'mobile_money',
                'name': self._extract_name_from_description(description)
            }
        
        return {
            'name': self._extract_name_from_description(description),
            'type': 'bank_transfer',
            'raw_description': description
        }

class AbsaBankParser(BankStatementParser):
    """Absa Bank (formerly Barclays) statement parser"""
    
    def __init__(self):
        super().__init__("Absa Bank", "BARCKE")
    
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse Absa Bank statement"""
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        transactions = []
        
        try:
            df = pd.read_csv(io.StringIO(content))
            
            for _, row in df.iterrows():
                # Absa typically has 'Amount' column with positive/negative values
                amount = self.normalize_amount(row.get('Amount', 0))
                if amount > 0:  # Only positive amounts (credits)
                    transaction = PaymentTransaction(
                        source=f"{self.bank_code.lower()}_bank",
                        transaction_id=f"ABSA_{row.get('Reference', len(transactions))}",
                        amount=amount,
                        currency='KES',
                        transaction_date=self.parse_date(row['Date']),
                        counterparty=self._parse_absa_counterparty(row.get('Description', '')),
                        memo=str(row.get('Description', '')),
                        status='COMPLETED',
                        balance_after=self.normalize_amount(row.get('Balance', None)),
                        raw_data=row.to_dict()
                    )
                    transactions.append(transaction)
        
        except Exception as e:
            self.logger.error(f"Error parsing Absa statement: {e}")
        
        return transactions
    
    def _parse_absa_counterparty(self, description: str) -> Dict:
        """Parse Absa transaction description"""
        if not description:
            return {'type': 'unknown'}
        
        description = str(description).upper()
        
        # Absa-specific patterns
        if 'TIMIZA' in description or 'MOBILE' in description:
            return {
                'type': 'mobile_banking',
                'name': self._extract_name_from_description(description)
            }
        
        return {
            'name': self._extract_name_from_description(description),
            'type': 'bank_transfer',
            'raw_description': description
        }

class BankParserFactory:
    """Factory for creating bank statement parsers"""
    
    @staticmethod
    def get_parser(bank_identifier: str) -> BankStatementParser:
        """Get appropriate parser based on bank identifier"""
        bank_identifier = bank_identifier.lower().replace(' ', '_')
        
        parsers = {
            'equity': EquityBankParser,
            'equity_bank': EquityBankParser,
            'eqbnke': EquityBankParser,
            
            'kcb': KCBParser,
            'kenya_commercial_bank': KCBParser,
            'kcblke': KCBParser,
            
            'coop': CooperativeBankParser,
            'cooperative': CooperativeBankParser,
            'cooperative_bank': CooperativeBankParser,
            'coopke': CooperativeBankParser,
            
            'absa': AbsaBankParser,
            'absa_bank': AbsaBankParser,
            'barclays': AbsaBankParser,
            'barcke': AbsaBankParser,
        }
        
        parser_class = parsers.get(bank_identifier)
        if not parser_class:
            raise ValueError(f"Unsupported bank: {bank_identifier}")
        
        return parser_class()

# Example usage
if __name__ == "__main__":
    # Example Equity Bank CSV
    equity_csv = """Date,Description,Reference,Debit,Credit,Balance
15/08/2024,MPESA TRANSFER FROM 254712345678 JOHN DOE,MPE123456,,5000.00,45000.00
16/08/2024,RTGS FROM ACME SUPPLIERS LTD,RTG789123,,25000.00,70000.00
17/08/2024,STANDING ORDER FROM EMPLOYEE SALARY,,SO001,15000.00,55000.00"""

    # Parse Equity Bank transactions
    parser = EquityBankParser()
    transactions = parser.parse_statement(equity_csv)
    
    for transaction in transactions:
        print(f"Bank: {transaction.source}")
        print(f"Transaction ID: {transaction.transaction_id}")
        print(f"Amount: {transaction.amount} {transaction.currency}")
        print(f"From: {transaction.counterparty}")
        print(f"Date: {transaction.transaction_date}")
        print("---")