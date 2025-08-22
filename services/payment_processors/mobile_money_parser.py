#!/usr/bin/env python3
"""
Mobile Money Payment Processors for Kenya/East Africa
Handles M-Pesa, Airtel Money, MTN MoMo transaction parsing
"""

import pandas as pd
import re
from datetime import datetime
from typing import Dict, List, Optional, Union
import io
import json
import logging
from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class PaymentTransaction:
    """Standardized payment transaction structure"""
    source: str
    transaction_id: str
    amount: float
    currency: str
    transaction_date: datetime
    counterparty: Dict
    memo: str
    status: str
    balance_after: Optional[float] = None
    fees: Optional[float] = None
    raw_data: Optional[Dict] = None

class MobileMoneyParser(ABC):
    """Abstract base class for mobile money parsers"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    @abstractmethod
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse mobile money statement and return standardized transactions"""
        pass
    
    def normalize_phone_number(self, phone: str) -> str:
        """Normalize phone numbers to international format"""
        phone = re.sub(r'[^\d+]', '', phone)
        
        # Kenya numbers
        if phone.startswith('0') and len(phone) == 10:
            return f"+254{phone[1:]}"
        elif phone.startswith('254') and len(phone) == 12:
            return f"+{phone}"
        elif phone.startswith('+254'):
            return phone
        
        # Uganda numbers  
        if phone.startswith('0') and len(phone) == 10 and phone[1] in '37':
            return f"+256{phone[1:]}"
        elif phone.startswith('256'):
            return f"+{phone}"
            
        # Tanzania numbers
        if phone.startswith('0') and len(phone) == 10 and phone[1] in '67':
            return f"+255{phone[1:]}"
        elif phone.startswith('255'):
            return f"+{phone}"
        
        return phone  # Return as-is if no pattern matches

class MPesaParser(MobileMoneyParser):
    """M-Pesa transaction parser for Kenya"""
    
    def __init__(self):
        super().__init__()
        self.source_name = "mpesa_kenya"
        
        # M-Pesa transaction type patterns
        self.transaction_patterns = {
            'received': [
                r'Received (.+?) Ksh([\d,]+\.?\d*) from (.+?) on (\d{1,2}\/\d{1,2}\/\d{2,4}) at (\d{1,2}:\d{2} [AP]M)',
                r'(.+?) has sent you Ksh([\d,]+\.?\d*)\. (.+?) New M-PESA balance is Ksh([\d,]+\.?\d*)'
            ],
            'sent': [
                r'(.+?) sent Ksh([\d,]+\.?\d*) to (.+?) on (\d{1,2}\/\d{1,2}\/\d{2,4}) at (\d{1,2}:\d{2} [AP]M)',
            ],
            'paybill': [
                r'(.+?) Confirmed\. Ksh([\d,]+\.?\d*) paid to (.+?)\. on (\d{1,2}\/\d{1,2}\/\d{2,4}) at (\d{1,2}:\d{2} [AP]M) New M-PESA balance is Ksh([\d,]+\.?\d*)'
            ]
        }
    
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse M-Pesa statement content"""
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        # Try different parsing methods
        transactions = []
        
        # Method 1: CSV format
        if self._is_csv_format(content):
            transactions.extend(self._parse_csv_format(content))
        
        # Method 2: PDF text extraction format
        elif self._is_text_format(content):
            transactions.extend(self._parse_text_format(content))
        
        # Method 3: SMS format (if copying from phone)
        elif self._is_sms_format(content):
            transactions.extend(self._parse_sms_format(content))
        
        self.logger.info(f"Parsed {len(transactions)} M-Pesa transactions")
        return transactions
    
    def _is_csv_format(self, content: str) -> bool:
        """Check if content is M-Pesa CSV format"""
        csv_headers = ['Receipt No', 'Completion Time', 'Details', 'Transaction Status', 'Paid In']
        return any(header in content for header in csv_headers)
    
    def _is_text_format(self, content: str) -> bool:
        """Check if content is M-Pesa text/PDF format"""
        return 'M-PESA' in content and 'Confirmation Code' in content
    
    def _is_sms_format(self, content: str) -> bool:
        """Check if content is SMS message format"""
        return 'Confirmed' in content and 'M-PESA balance' in content
    
    def _parse_csv_format(self, content: str) -> List[PaymentTransaction]:
        """Parse M-Pesa CSV export format"""
        transactions = []
        
        try:
            df = pd.read_csv(io.StringIO(content))
            
            for _, row in df.iterrows():
                # Only process completed transactions with money received
                if (row.get('Transaction Status', '').upper() == 'COMPLETED' and 
                    pd.notna(row.get('Paid In', 0)) and 
                    float(row.get('Paid In', 0)) > 0):
                    
                    transaction = PaymentTransaction(
                        source=self.source_name,
                        transaction_id=str(row['Receipt No']),
                        amount=float(row['Paid In']),
                        currency='KES',
                        transaction_date=self._parse_datetime(row['Completion Time']),
                        counterparty=self._parse_counterparty_csv(row.get('Other Party Info', '')),
                        memo=str(row.get('Details', '')),
                        status='COMPLETED',
                        balance_after=float(row['Balance']) if pd.notna(row.get('Balance')) else None,
                        raw_data=row.to_dict()
                    )
                    transactions.append(transaction)
        
        except Exception as e:
            self.logger.error(f"Error parsing M-Pesa CSV: {e}")
        
        return transactions
    
    def _parse_text_format(self, content: str) -> List[PaymentTransaction]:
        """Parse M-Pesa PDF text format"""
        transactions = []
        lines = content.split('\n')
        
        current_transaction = {}
        for line in lines:
            line = line.strip()
            
            # Look for transaction patterns
            if 'Confirmation Code:' in line:
                current_transaction['transaction_id'] = line.split(':')[-1].strip()
            elif 'Amount:' in line and 'Ksh' in line:
                amount_match = re.search(r'Ksh\s*([\d,]+\.?\d*)', line)
                if amount_match:
                    current_transaction['amount'] = float(amount_match.group(1).replace(',', ''))
            elif 'From:' in line:
                current_transaction['sender'] = line.replace('From:', '').strip()
            elif 'Date:' in line:
                current_transaction['date'] = line.replace('Date:', '').strip()
            
            # When we have complete transaction, create PaymentTransaction
            if all(k in current_transaction for k in ['transaction_id', 'amount', 'sender', 'date']):
                transaction = PaymentTransaction(
                    source=self.source_name,
                    transaction_id=current_transaction['transaction_id'],
                    amount=current_transaction['amount'],
                    currency='KES',
                    transaction_date=self._parse_datetime(current_transaction['date']),
                    counterparty={'name': current_transaction['sender'], 'type': 'mpesa_user'},
                    memo=f"M-Pesa transfer from {current_transaction['sender']}",
                    status='COMPLETED'
                )
                transactions.append(transaction)
                current_transaction = {}
        
        return transactions
    
    def _parse_sms_format(self, content: str) -> List[PaymentTransaction]:
        """Parse M-Pesa SMS message format"""
        transactions = []
        
        for transaction_type, patterns in self.transaction_patterns.items():
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                
                for match in matches:
                    if transaction_type == 'received' and len(match) >= 4:
                        transaction = PaymentTransaction(
                            source=self.source_name,
                            transaction_id=match[0] if len(match[0]) > 5 else f"SMS_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                            amount=float(match[1].replace(',', '')),
                            currency='KES',
                            transaction_date=self._parse_datetime(f"{match[3]} {match[4]}" if len(match) > 4 else match[3]),
                            counterparty=self._parse_counterparty_name(match[2]),
                            memo=f"M-Pesa received from {match[2]}",
                            status='COMPLETED'
                        )
                        transactions.append(transaction)
        
        return transactions
    
    def _parse_counterparty_csv(self, party_info: str) -> Dict:
        """Parse counterparty info from M-Pesa CSV format"""
        if not party_info:
            return {'type': 'unknown'}
        
        # Format: "254712345678 - JOHN DOE"
        if ' - ' in party_info:
            phone, name = party_info.split(' - ', 1)
            return {
                'phone': self.normalize_phone_number(phone.strip()),
                'name': name.strip(),
                'type': 'individual'
            }
        
        # Business shortcode format
        if party_info.isdigit() and len(party_info) <= 6:
            return {
                'shortcode': party_info,
                'type': 'business',
                'name': self._get_business_name_from_shortcode(party_info)
            }
        
        return {'raw': party_info, 'type': 'unknown'}
    
    def _parse_counterparty_name(self, name: str) -> Dict:
        """Parse counterparty from name string"""
        # Check if it's a phone number
        if re.match(r'^\+?254\d{9}$', name.replace(' ', '')):
            return {
                'phone': self.normalize_phone_number(name),
                'type': 'individual'
            }
        
        return {
            'name': name.strip(),
            'type': 'individual'
        }
    
    def _get_business_name_from_shortcode(self, shortcode: str) -> str:
        """Map M-Pesa business shortcodes to company names"""
        shortcode_map = {
            '174379': 'Safaricom Ltd',
            '400200': 'Equity Bank',
            '522522': 'Kenya Commercial Bank',
            '888880': 'Co-operative Bank',
            '444444': 'Family Bank',
            '300300': 'EABL - Tusker',
            '600100': 'Standard Chartered Bank'
        }
        return shortcode_map.get(shortcode, f'Business {shortcode}')
    
    def _parse_datetime(self, date_str: str) -> datetime:
        """Parse various M-Pesa date formats"""
        date_str = date_str.strip()
        
        # Try different date formats
        formats = [
            '%d/%m/%Y %I:%M %p',  # 15/08/2024 2:30 PM
            '%d/%m/%Y %H:%M:%S',  # 15/08/2024 14:30:45
            '%Y-%m-%d %H:%M:%S',  # 2024-08-15 14:30:45
            '%d/%m/%Y',           # 15/08/2024
            '%Y-%m-%d',           # 2024-08-15
            '%d %b %Y %I:%M %p',  # 15 Aug 2024 2:30 PM
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # If all else fails, return current time
        self.logger.warning(f"Could not parse date: {date_str}, using current time")
        return datetime.now()

class AirtelMoneyParser(MobileMoneyParser):
    """Airtel Money transaction parser"""
    
    def __init__(self):
        super().__init__()
        self.source_name = "airtel_money"
    
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse Airtel Money statement"""
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        transactions = []
        
        # Airtel Money CSV format
        if 'Transaction ID' in content and 'Amount' in content:
            transactions.extend(self._parse_airtel_csv(content))
        
        return transactions
    
    def _parse_airtel_csv(self, content: str) -> List[PaymentTransaction]:
        """Parse Airtel Money CSV format"""
        transactions = []
        
        try:
            df = pd.read_csv(io.StringIO(content))
            
            for _, row in df.iterrows():
                if row.get('Type', '').upper() == 'CREDIT' and float(row.get('Amount', 0)) > 0:
                    transaction = PaymentTransaction(
                        source=self.source_name,
                        transaction_id=str(row['Transaction ID']),
                        amount=float(row['Amount']),
                        currency=row.get('Currency', 'KES'),
                        transaction_date=self._parse_datetime(row['Date Time']),
                        counterparty=self._parse_airtel_counterparty(row.get('From/To', '')),
                        memo=str(row.get('Description', '')),
                        status=row.get('Status', 'COMPLETED'),
                        balance_after=float(row['Balance']) if pd.notna(row.get('Balance')) else None,
                        raw_data=row.to_dict()
                    )
                    transactions.append(transaction)
        
        except Exception as e:
            self.logger.error(f"Error parsing Airtel Money CSV: {e}")
        
        return transactions
    
    def _parse_airtel_counterparty(self, counterparty_str: str) -> Dict:
        """Parse Airtel Money counterparty information"""
        if not counterparty_str:
            return {'type': 'unknown'}
        
        # Phone number pattern
        phone_pattern = r'(\+?256\d{9}|\+?254\d{9})'  # Uganda or Kenya
        phone_match = re.search(phone_pattern, counterparty_str)
        
        if phone_match:
            return {
                'phone': self.normalize_phone_number(phone_match.group(1)),
                'name': counterparty_str.replace(phone_match.group(1), '').strip(),
                'type': 'individual'
            }
        
        return {
            'name': counterparty_str.strip(),
            'type': 'individual'
        }
    
    def _parse_datetime(self, date_str: str) -> datetime:
        """Parse Airtel Money date formats"""
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%d/%m/%Y %H:%M:%S',
            '%Y-%m-%d',
            '%d/%m/%Y'
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        
        return datetime.now()

class MTNMoMoParser(MobileMoneyParser):
    """MTN Mobile Money parser for Uganda/Rwanda"""
    
    def __init__(self, country='uganda'):
        super().__init__()
        self.source_name = f"mtn_momo_{country}"
        self.country = country
    
    def parse_statement(self, content: Union[str, bytes]) -> List[PaymentTransaction]:
        """Parse MTN MoMo statement"""
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        transactions = []
        
        # MTN MoMo Excel/CSV format
        if any(header in content for header in ['Transaction Reference', 'Transaction Date', 'Amount']):
            transactions.extend(self._parse_mtn_csv(content))
        
        return transactions
    
    def _parse_mtn_csv(self, content: str) -> List[PaymentTransaction]:
        """Parse MTN MoMo CSV/Excel format"""
        transactions = []
        
        try:
            # Handle both CSV and tab-separated values
            separator = '\t' if '\t' in content else ','
            df = pd.read_csv(io.StringIO(content), sep=separator)
            
            for _, row in df.iterrows():
                # Look for credit transactions
                if (row.get('Transaction Type', '').upper() in ['RECEIVE', 'CREDIT'] and 
                    float(row.get('Amount', 0)) > 0):
                    
                    currency = 'UGX' if self.country == 'uganda' else 'RWF'
                    
                    transaction = PaymentTransaction(
                        source=self.source_name,
                        transaction_id=str(row['Transaction Reference']),
                        amount=float(row['Amount']),
                        currency=currency,
                        transaction_date=self._parse_datetime(row['Transaction Date']),
                        counterparty=self._parse_mtn_counterparty(row.get('Other Party', '')),
                        memo=str(row.get('Description', '')),
                        status=row.get('Status', 'COMPLETED'),
                        fees=float(row.get('Charge', 0)) if pd.notna(row.get('Charge')) else None,
                        raw_data=row.to_dict()
                    )
                    transactions.append(transaction)
        
        except Exception as e:
            self.logger.error(f"Error parsing MTN MoMo CSV: {e}")
        
        return transactions
    
    def _parse_mtn_counterparty(self, counterparty_str: str) -> Dict:
        """Parse MTN MoMo counterparty information"""
        if not counterparty_str:
            return {'type': 'unknown'}
        
        # Phone number patterns for Uganda/Rwanda
        phone_patterns = [
            r'(\+?256[37]\d{8})',  # Uganda
            r'(\+?250[78]\d{8})',  # Rwanda
        ]
        
        for pattern in phone_patterns:
            phone_match = re.search(pattern, counterparty_str)
            if phone_match:
                return {
                    'phone': self.normalize_phone_number(phone_match.group(1)),
                    'name': counterparty_str.replace(phone_match.group(1), '').strip(),
                    'type': 'individual'
                }
        
        return {
            'name': counterparty_str.strip(),
            'type': 'individual'
        }
    
    def _parse_datetime(self, date_str: str) -> datetime:
        """Parse MTN MoMo date formats"""
        formats = [
            '%d/%m/%Y %H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%d-%m-%Y %H:%M:%S',
            '%d/%m/%Y',
            '%Y-%m-%d'
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        
        return datetime.now()

class MobileMoneyParserFactory:
    """Factory class for creating mobile money parsers"""
    
    @staticmethod
    def get_parser(source_type: str, **kwargs) -> MobileMoneyParser:
        """Get appropriate parser based on source type"""
        parsers = {
            'mpesa': MPesaParser,
            'mpesa_kenya': MPesaParser,
            'airtel_money': AirtelMoneyParser,
            'mtn_momo_uganda': lambda: MTNMoMoParser(country='uganda'),
            'mtn_momo_rwanda': lambda: MTNMoMoParser(country='rwanda'),
        }
        
        parser_class = parsers.get(source_type.lower())
        if not parser_class:
            raise ValueError(f"Unsupported mobile money source: {source_type}")
        
        return parser_class() if callable(parser_class) else parser_class(**kwargs)

# Example usage
if __name__ == "__main__":
    # Example M-Pesa CSV content
    mpesa_csv = """Receipt No,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance,Reason Type,Other Party Info
QEJ7H8KL9M,15/08/2024 2:30 PM,Customer payment for invoice INV001,Completed,5000.00,,45000.00,Pay Merchant,254712345678 - JOHN DOE
QEJ7H8KL9N,15/08/2024 3:45 PM,Payment for services,Completed,2500.00,,47500.00,Send Money,254798765432 - MARY WANJIKU"""

    # Parse M-Pesa transactions
    parser = MPesaParser()
    transactions = parser.parse_statement(mpesa_csv)
    
    for transaction in transactions:
        print(f"Transaction ID: {transaction.transaction_id}")
        print(f"Amount: {transaction.amount} {transaction.currency}")
        print(f"From: {transaction.counterparty}")
        print(f"Date: {transaction.transaction_date}")
        print("---")