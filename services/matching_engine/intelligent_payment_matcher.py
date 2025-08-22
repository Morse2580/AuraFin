#!/usr/bin/env python3
"""
Intelligent Payment Matching Engine for Kenya/East Africa
Advanced fuzzy matching, customer alias resolution, and multi-payment scenarios
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging
from dataclasses import dataclass, field
from fuzzywuzzy import fuzz, process
import pandas as pd
from difflib import SequenceMatcher
from collections import defaultdict
import json

@dataclass
class MatchRule:
    """Payment matching rule definition"""
    name: str
    priority: int
    confidence_threshold: float
    tolerance_percentage: float
    date_window_days: int
    required_fields: List[str]
    
@dataclass
class PaymentMatch:
    """Payment to invoice match result"""
    payment_id: str
    invoice_id: str
    confidence_score: float
    match_rule: str
    amount_to_apply: float
    remaining_payment: float
    remaining_invoice: float
    match_details: Dict[str, Any]
    
@dataclass
class CustomerAlias:
    """Customer name alias mapping"""
    canonical_name: str
    aliases: List[str] = field(default_factory=list)
    phone_numbers: List[str] = field(default_factory=list)
    account_numbers: List[str] = field(default_factory=list)
    mpesa_names: List[str] = field(default_factory=list)

class KenyaCustomerAliasManager:
    """Manages customer name variations and aliases for Kenya market"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.aliases: Dict[str, CustomerAlias] = {}
        self.phone_to_customer: Dict[str, str] = {}
        self.account_to_customer: Dict[str, str] = {}
        
        # Load common Kenyan name patterns
        self._initialize_kenyan_patterns()
    
    def _initialize_kenyan_patterns(self):
        """Initialize common Kenyan name patterns and variations"""
        
        # Common Kenyan name variations
        self.common_variations = {
            'JOHN': ['JON', 'JOHNY', 'J'],
            'MARY': ['MARIE', 'MARIA', 'M'],
            'DAVID': ['DAVE', 'DAVIDE', 'D'],
            'PETER': ['PETE', 'PETRO', 'P'],
            'GRACE': ['GRACIE', 'G'],
            'JAMES': ['JIM', 'JIMMY', 'J'],
            'CATHERINE': ['KATE', 'CATHY', 'CATHERINE'],
            'STEPHEN': ['STEVE', 'STEVEN', 'STEVO'],
            'MICHAEL': ['MIKE', 'MICKY', 'MICHAEL'],
            'ELIZABETH': ['LIZ', 'LIZZY', 'BETTY', 'ELIZA']
        }
        
        # Common business name abbreviations
        self.business_abbreviations = {
            'LIMITED': ['LTD', 'LTD.', 'LIMIT'],
            'COMPANY': ['CO', 'CO.', 'COMP'],
            'CORPORATION': ['CORP', 'CORP.'],
            'ENTERPRISES': ['ENT', 'ENTER'],
            'SERVICES': ['SERV', 'SVC'],
            'TRADING': ['TRAD', 'TRD'],
            'SUPPLIES': ['SUPP', 'SUPPLY'],
            'KENYA': ['KE', 'K'],
            'EAST AFRICAN': ['EA', 'EAST AFR', 'E.A.'],
            'INTERNATIONAL': ['INTL', 'INT\'L', 'INT']
        }
        
        # M-Pesa name cleaning patterns
        self.mpesa_cleanup_patterns = [
            r'\b\d{10,}\b',  # Remove phone numbers
            r'\bMPESA\b',    # Remove MPESA
            r'\bFROM\b',     # Remove FROM
            r'\bTO\b',       # Remove TO
            r'\b\d{4,}\b'    # Remove transaction IDs
        ]
    
    def add_customer_alias(self, customer_id: str, canonical_name: str, aliases: List[str] = None, 
                          phone_numbers: List[str] = None, account_numbers: List[str] = None):
        """Add customer with aliases"""
        
        aliases = aliases or []
        phone_numbers = phone_numbers or []
        account_numbers = account_numbers or []
        
        # Generate common variations automatically
        auto_aliases = self._generate_name_variations(canonical_name)
        all_aliases = list(set(aliases + auto_aliases))
        
        customer_alias = CustomerAlias(
            canonical_name=canonical_name,
            aliases=all_aliases,
            phone_numbers=phone_numbers,
            account_numbers=account_numbers
        )
        
        self.aliases[customer_id] = customer_alias
        
        # Build reverse lookup maps
        for phone in phone_numbers:
            self.phone_to_customer[self._normalize_phone(phone)] = customer_id
        
        for account in account_numbers:
            self.account_to_customer[account] = customer_id
    
    def find_customer_match(self, payment_counterparty: Dict, customer_list: List[Dict]) -> Tuple[Optional[str], float, str]:
        """Find best customer match for payment counterparty"""
        
        best_match = None
        best_score = 0
        match_method = 'none'
        
        # Extract counterparty information
        counterparty_name = payment_counterparty.get('name', '').upper().strip()
        counterparty_phone = payment_counterparty.get('phone', '')
        counterparty_account = payment_counterparty.get('account', '')
        
        # Method 1: Phone number match (highest confidence)
        if counterparty_phone:
            normalized_phone = self._normalize_phone(counterparty_phone)
            if normalized_phone in self.phone_to_customer:
                customer_id = self.phone_to_customer[normalized_phone]
                return customer_id, 0.98, 'phone_exact'
        
        # Method 2: Account number match
        if counterparty_account:
            if counterparty_account in self.account_to_customer:
                customer_id = self.account_to_customer[counterparty_account]
                return customer_id, 0.95, 'account_exact'
        
        # Method 3: Name matching with aliases
        if counterparty_name:
            cleaned_name = self._clean_mpesa_name(counterparty_name)
            
            for customer in customer_list:
                customer_id = customer.get('id', customer.get('customer_id'))
                customer_name = customer.get('name', customer.get('customer_name', '')).upper()
                
                # Exact name match
                if cleaned_name == customer_name:
                    return customer_id, 0.92, 'name_exact'
                
                # Check aliases if available
                if customer_id in self.aliases:
                    aliases = self.aliases[customer_id].aliases
                    
                    # Exact alias match
                    for alias in aliases:
                        if cleaned_name == alias.upper():
                            return customer_id, 0.90, 'alias_exact'
                    
                    # Fuzzy alias match
                    alias_scores = [(alias, fuzz.ratio(cleaned_name, alias.upper())) for alias in aliases]
                    best_alias_score = max(alias_scores, key=lambda x: x[1]) if alias_scores else (None, 0)
                    
                    if best_alias_score[1] > 85:
                        if best_alias_score[1] > best_score:
                            best_match = customer_id
                            best_score = best_alias_score[1] / 100
                            match_method = 'alias_fuzzy'
                
                # Fuzzy name match
                name_score = fuzz.ratio(cleaned_name, customer_name)
                if name_score > 85 and name_score > best_score * 100:
                    best_match = customer_id
                    best_score = name_score / 100
                    match_method = 'name_fuzzy'
        
        return best_match, best_score, match_method
    
    def _generate_name_variations(self, name: str) -> List[str]:
        """Generate common variations of a name"""
        variations = []
        name_upper = name.upper()
        
        # Split into parts
        parts = name_upper.split()
        
        for part in parts:
            # Check for common variations
            if part in self.common_variations:
                variations.extend(self.common_variations[part])
            
            # Check for business abbreviations
            if part in self.business_abbreviations:
                variations.extend(self.business_abbreviations[part])
        
        # Generate combinations
        if len(parts) >= 2:
            # First name + last initial
            variations.append(f"{parts[0]} {parts[-1][0]}")
            # First initial + last name
            variations.append(f"{parts[0][0]} {parts[-1]}")
            # Just first name
            variations.append(parts[0])
            # Just last name
            variations.append(parts[-1])
        
        return variations
    
    def _clean_mpesa_name(self, mpesa_name: str) -> str:
        """Clean M-Pesa name removing transaction artifacts"""
        cleaned = mpesa_name.upper()
        
        for pattern in self.mpesa_cleanup_patterns:
            cleaned = re.sub(pattern, '', cleaned)
        
        # Remove extra whitespace
        cleaned = ' '.join(cleaned.split())
        
        return cleaned
    
    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number to standard format"""
        phone = re.sub(r'[^\d+]', '', phone)
        
        # Kenya numbers
        if phone.startswith('0') and len(phone) == 10:
            return f"+254{phone[1:]}"
        elif phone.startswith('254') and len(phone) == 12:
            return f"+{phone}"
        elif phone.startswith('+254'):
            return phone
        
        return phone

class IntelligentPaymentMatcher:
    """Advanced payment matching engine with fuzzy logic and multi-scenario handling"""
    
    def __init__(self, config: Dict = None):
        self.logger = logging.getLogger(__name__)
        self.config = config or {}
        
        # Initialize customer alias manager
        self.alias_manager = KenyaCustomerAliasManager()
        
        # Matching rules configuration
        self.matching_rules = self._initialize_matching_rules()
        
        # Matching statistics
        self.match_stats = defaultdict(int)
    
    def _initialize_matching_rules(self) -> List[MatchRule]:
        """Initialize payment matching rules"""
        return [
            MatchRule(
                name='exact_amount_and_reference',
                priority=1,
                confidence_threshold=0.95,
                tolerance_percentage=0.001,  # 0.1% tolerance
                date_window_days=7,
                required_fields=['amount', 'reference_match']
            ),
            MatchRule(
                name='exact_amount_and_customer',
                priority=2,
                confidence_threshold=0.90,
                tolerance_percentage=0.01,   # 1% tolerance
                date_window_days=30,
                required_fields=['amount', 'customer_match']
            ),
            MatchRule(
                name='amount_tolerance_strong_customer',
                priority=3,
                confidence_threshold=0.85,
                tolerance_percentage=0.05,   # 5% tolerance
                date_window_days=14,
                required_fields=['customer_match']
            ),
            MatchRule(
                name='reference_match_amount_tolerance',
                priority=4,
                confidence_threshold=0.82,
                tolerance_percentage=0.10,   # 10% tolerance
                date_window_days=45,
                required_fields=['reference_match']
            ),
            MatchRule(
                name='partial_payment_customer_match',
                priority=5,
                confidence_threshold=0.75,
                tolerance_percentage=0.00,   # Exact or less than invoice
                date_window_days=60,
                required_fields=['customer_match', 'partial_payment']
            ),
            MatchRule(
                name='overpayment_tolerance',
                priority=6,
                confidence_threshold=0.70,
                tolerance_percentage=0.20,   # 20% overpayment tolerance
                date_window_days=30,
                required_fields=['customer_match', 'overpayment']
            )
        ]
    
    def match_payments_to_invoices(self, payments: List[Dict], invoices: List[Dict]) -> List[PaymentMatch]:
        """Match multiple payments to invoices using intelligent rules"""
        
        matches = []
        unmatched_payments = payments.copy()
        unmatched_invoices = invoices.copy()
        
        # Sort rules by priority
        sorted_rules = sorted(self.matching_rules, key=lambda x: x.priority)
        
        for rule in sorted_rules:
            self.logger.info(f"Applying rule: {rule.name}")
            
            # Apply rule to remaining unmatched items
            rule_matches = self._apply_matching_rule(rule, unmatched_payments, unmatched_invoices)
            
            for match in rule_matches:
                # Remove matched items from unmatched lists
                unmatched_payments = [p for p in unmatched_payments if p['id'] != match.payment_id]
                unmatched_invoices = [i for i in unmatched_invoices if i['id'] != match.invoice_id]
                
                matches.append(match)
                self.match_stats[rule.name] += 1
        
        self.logger.info(f"Matched {len(matches)} payments using {len([r for r in self.match_stats if self.match_stats[r] > 0])} rules")
        return matches
    
    def _apply_matching_rule(self, rule: MatchRule, payments: List[Dict], invoices: List[Dict]) -> List[PaymentMatch]:
        """Apply a specific matching rule"""
        
        matches = []
        
        for payment in payments:
            payment_matches = []
            
            for invoice in invoices:
                match_score = self._evaluate_payment_invoice_match(payment, invoice, rule)
                
                if match_score and match_score['confidence'] >= rule.confidence_threshold:
                    payment_match = PaymentMatch(
                        payment_id=payment['id'],
                        invoice_id=invoice['id'],
                        confidence_score=match_score['confidence'],
                        match_rule=rule.name,
                        amount_to_apply=match_score['amount_to_apply'],
                        remaining_payment=match_score['remaining_payment'],
                        remaining_invoice=match_score['remaining_invoice'],
                        match_details=match_score['details']
                    )
                    payment_matches.append(payment_match)
            
            # Select best match for this payment
            if payment_matches:
                best_match = max(payment_matches, key=lambda x: x.confidence_score)
                matches.append(best_match)
        
        return matches
    
    def _evaluate_payment_invoice_match(self, payment: Dict, invoice: Dict, rule: MatchRule) -> Optional[Dict]:
        """Evaluate if payment matches invoice according to rule"""
        
        match_details = {}
        confidence_factors = []
        
        # Extract payment information
        payment_amount = float(payment.get('amount', 0))
        payment_date = payment.get('transaction_date')
        payment_counterparty = payment.get('counterparty', {})
        payment_memo = payment.get('memo', '').upper()
        payment_reference = payment.get('reference', '').upper()
        
        # Extract invoice information
        invoice_amount = float(invoice.get('amount_due', invoice.get('amount_total', 0)))
        invoice_date = invoice.get('invoice_date', invoice.get('due_date'))
        invoice_number = invoice.get('invoice_number', '').upper()
        invoice_reference = invoice.get('reference', '').upper()
        invoice_customer = invoice.get('customer', {})
        
        # 1. Amount matching
        amount_diff = abs(payment_amount - invoice_amount)
        amount_tolerance = invoice_amount * rule.tolerance_percentage
        amount_match_score = 0
        
        if amount_diff <= amount_tolerance:
            amount_match_score = max(0, 1 - (amount_diff / max(invoice_amount, 0.01)))
            confidence_factors.append(('amount', amount_match_score))
            match_details['amount_difference'] = amount_diff
            match_details['amount_tolerance'] = amount_tolerance
        elif 'partial_payment' in rule.required_fields and payment_amount < invoice_amount:
            # Partial payment scenario
            amount_match_score = 0.8  # Base score for partial payments
            confidence_factors.append(('partial_payment', amount_match_score))
            match_details['payment_type'] = 'partial'
        elif 'overpayment' in rule.required_fields and payment_amount > invoice_amount:
            # Overpayment scenario
            overpayment_ratio = (payment_amount - invoice_amount) / invoice_amount
            if overpayment_ratio <= rule.tolerance_percentage:
                amount_match_score = max(0.6, 1 - overpayment_ratio)
                confidence_factors.append(('overpayment', amount_match_score))
                match_details['payment_type'] = 'overpayment'
                match_details['overpayment_amount'] = payment_amount - invoice_amount
        
        # 2. Customer matching
        if 'customer_match' in rule.required_fields:
            customer_match_id, customer_score, match_method = self.alias_manager.find_customer_match(
                payment_counterparty, [invoice_customer]
            )
            
            if customer_match_id and customer_score > 0.7:
                confidence_factors.append(('customer', customer_score))
                match_details['customer_match_method'] = match_method
                match_details['customer_match_score'] = customer_score
        
        # 3. Reference matching
        if 'reference_match' in rule.required_fields:
            reference_score = self._match_references(payment_reference, payment_memo, invoice_number, invoice_reference)
            if reference_score > 0.7:
                confidence_factors.append(('reference', reference_score))
                match_details['reference_match_score'] = reference_score
        
        # 4. Date proximity matching
        if payment_date and invoice_date:
            date_score = self._calculate_date_proximity_score(payment_date, invoice_date, rule.date_window_days)
            if date_score > 0.5:
                confidence_factors.append(('date', date_score))
                match_details['date_proximity_score'] = date_score
        
        # Calculate overall confidence
        if not confidence_factors:
            return None
        
        # Weight the confidence factors
        weights = {
            'amount': 0.4,
            'customer': 0.3,
            'reference': 0.2,
            'date': 0.05,
            'partial_payment': 0.3,
            'overpayment': 0.25
        }
        
        total_confidence = sum(score * weights.get(factor, 0.1) for factor, score in confidence_factors)
        total_weight = sum(weights.get(factor, 0.1) for factor, _ in confidence_factors)
        
        if total_weight > 0:
            final_confidence = min(1.0, total_confidence / total_weight)
        else:
            final_confidence = 0
        
        # Calculate amounts to apply
        amount_to_apply = min(payment_amount, invoice_amount)
        remaining_payment = max(0, payment_amount - amount_to_apply)
        remaining_invoice = max(0, invoice_amount - amount_to_apply)
        
        return {
            'confidence': final_confidence,
            'amount_to_apply': amount_to_apply,
            'remaining_payment': remaining_payment,
            'remaining_invoice': remaining_invoice,
            'details': match_details,
            'confidence_factors': confidence_factors
        }
    
    def _match_references(self, payment_ref: str, payment_memo: str, invoice_number: str, invoice_ref: str) -> float:
        """Match payment references with invoice identifiers"""
        
        # Combine payment identifiers
        payment_text = f"{payment_ref} {payment_memo}".upper()
        invoice_text = f"{invoice_number} {invoice_ref}".upper()
        
        # Exact matches
        if invoice_number in payment_text or payment_ref in invoice_text:
            return 0.95
        
        # Fuzzy matching
        invoice_score = fuzz.partial_ratio(payment_text, invoice_number) / 100
        ref_score = fuzz.partial_ratio(payment_text, invoice_ref) / 100
        
        return max(invoice_score, ref_score)
    
    def _calculate_date_proximity_score(self, payment_date: datetime, invoice_date: datetime, max_days: int) -> float:
        """Calculate score based on date proximity"""
        
        if isinstance(payment_date, str):
            payment_date = datetime.fromisoformat(payment_date.replace('Z', '+00:00'))
        if isinstance(invoice_date, str):
            invoice_date = datetime.fromisoformat(invoice_date.replace('Z', '+00:00'))
        
        day_diff = abs((payment_date - invoice_date).days)
        
        if day_diff > max_days:
            return 0
        
        return max(0, 1 - (day_diff / max_days))
    
    def handle_complex_scenarios(self, matches: List[PaymentMatch]) -> List[PaymentMatch]:
        """Handle complex scenarios like split payments, overpayments, etc."""
        
        enhanced_matches = []
        
        # Group by payment and invoice
        payment_groups = defaultdict(list)
        invoice_groups = defaultdict(list)
        
        for match in matches:
            payment_groups[match.payment_id].append(match)
            invoice_groups[match.invoice_id].append(match)
        
        # Handle one-to-many (payment split across multiple invoices)
        for payment_id, payment_matches in payment_groups.items():
            if len(payment_matches) > 1:
                enhanced_matches.extend(self._handle_payment_split(payment_matches))
            else:
                enhanced_matches.extend(payment_matches)
        
        # Handle many-to-one (multiple payments for one invoice)
        consolidated_matches = []
        processed_invoices = set()
        
        for match in enhanced_matches:
            if match.invoice_id not in processed_invoices:
                invoice_matches = [m for m in enhanced_matches if m.invoice_id == match.invoice_id]
                
                if len(invoice_matches) > 1:
                    consolidated_matches.append(self._handle_multiple_payments_one_invoice(invoice_matches))
                else:
                    consolidated_matches.append(match)
                
                processed_invoices.add(match.invoice_id)
        
        return consolidated_matches
    
    def _handle_payment_split(self, payment_matches: List[PaymentMatch]) -> List[PaymentMatch]:
        """Handle payment split across multiple invoices"""
        
        # Sort by confidence score
        sorted_matches = sorted(payment_matches, key=lambda x: x.confidence_score, reverse=True)
        
        total_payment = sorted_matches[0].amount_to_apply + sorted_matches[0].remaining_payment
        remaining_amount = total_payment
        
        split_matches = []
        
        for match in sorted_matches:
            if remaining_amount <= 0:
                break
            
            # Calculate amount to allocate to this invoice
            allocated_amount = min(remaining_amount, match.amount_to_apply)
            remaining_amount -= allocated_amount
            
            # Update match
            split_match = PaymentMatch(
                payment_id=match.payment_id,
                invoice_id=match.invoice_id,
                confidence_score=match.confidence_score * 0.9,  # Slight penalty for splits
                match_rule=f"{match.match_rule}_split",
                amount_to_apply=allocated_amount,
                remaining_payment=remaining_amount if match == sorted_matches[-1] else 0,
                remaining_invoice=max(0, match.amount_to_apply - allocated_amount),
                match_details={**match.match_details, 'split_payment': True}
            )
            
            split_matches.append(split_match)
        
        return split_matches
    
    def _handle_multiple_payments_one_invoice(self, invoice_matches: List[PaymentMatch]) -> PaymentMatch:
        """Handle multiple payments for one invoice"""
        
        # Sort by confidence and date
        sorted_matches = sorted(invoice_matches, key=lambda x: x.confidence_score, reverse=True)
        
        # Consolidate into single match record
        total_applied = sum(match.amount_to_apply for match in sorted_matches)
        payment_ids = [match.payment_id for match in sorted_matches]
        
        consolidated_match = PaymentMatch(
            payment_id=','.join(payment_ids),  # Multiple payment IDs
            invoice_id=sorted_matches[0].invoice_id,
            confidence_score=sum(match.confidence_score for match in sorted_matches) / len(sorted_matches),
            match_rule=f"{sorted_matches[0].match_rule}_consolidated",
            amount_to_apply=total_applied,
            remaining_payment=0,  # Assume full application
            remaining_invoice=max(0, sorted_matches[0].amount_to_apply + sorted_matches[0].remaining_invoice - total_applied),
            match_details={
                'consolidated_payments': len(sorted_matches),
                'payment_details': [match.match_details for match in sorted_matches]
            }
        )
        
        return consolidated_match
    
    def get_matching_statistics(self) -> Dict:
        """Get matching statistics and performance metrics"""
        return {
            'rule_usage': dict(self.match_stats),
            'total_matches': sum(self.match_stats.values()),
            'rules_used': len([r for r in self.match_stats if self.match_stats[r] > 0])
        }

# Example usage
if __name__ == "__main__":
    # Initialize matcher
    matcher = IntelligentPaymentMatcher()
    
    # Add some customer aliases for testing
    matcher.alias_manager.add_customer_alias(
        customer_id="CUST001",
        canonical_name="JOHN DOE ENTERPRISES LTD",
        aliases=["JOHN DOE ENT", "J DOE LTD", "JOHN ENTERPRISES"],
        phone_numbers=["+254712345678", "+254798765432"],
        account_numbers=["1234567890"]
    )
    
    # Sample payments
    payments = [
        {
            'id': 'PAY001',
            'amount': 5000.00,
            'transaction_date': datetime(2024, 8, 15),
            'counterparty': {
                'name': 'JOHN DOE',
                'phone': '+254712345678',
                'type': 'mpesa_transfer'
            },
            'memo': 'Payment for invoice INV001',
            'reference': 'MPE123456'
        }
    ]
    
    # Sample invoices
    invoices = [
        {
            'id': 'INV001',
            'invoice_number': 'INV-2024-001',
            'amount_due': 5000.00,
            'invoice_date': datetime(2024, 8, 10),
            'customer': {
                'id': 'CUST001',
                'name': 'JOHN DOE ENTERPRISES LTD'
            },
            'reference': 'PO-2024-001'
        }
    ]
    
    # Perform matching
    matches = matcher.match_payments_to_invoices(payments, invoices)
    
    for match in matches:
        print(f"Match: Payment {match.payment_id} -> Invoice {match.invoice_id}")
        print(f"Confidence: {match.confidence_score:.2f}")
        print(f"Rule: {match.match_rule}")
        print(f"Amount to apply: {match.amount_to_apply}")
        print("---")