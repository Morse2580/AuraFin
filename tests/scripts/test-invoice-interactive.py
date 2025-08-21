#!/usr/bin/env python3
"""
Interactive Real Invoice Testing Tool
Copy-paste your invoice content and see how the ML system performs
"""
import requests
import json
import time
from datetime import datetime

def test_invoice(invoice_text, invoice_name="Real Invoice"):
    """Test a single invoice with the ML system"""
    print(f"\n📄 Testing: {invoice_name}")
    print("=" * 50)
    
    # Prepare API request
    payload = {
        "document_uris": [f"{invoice_name}.pdf"],
        "client_id": "real-invoice-test",
        "processing_options": {"tier_preference": "auto"}
    }
    
    try:
        # Call DIM service
        start_time = time.time()
        response = requests.post(
            "http://localhost:8012/api/v1/parse_document",
            json=payload,
            timeout=30
        )
        processing_time = (time.time() - start_time) * 1000
        
        if response.status_code == 200:
            result = response.json()
            
            print(f"✅ EXTRACTION SUCCESSFUL")
            print(f"   📋 Invoice IDs Found: {result.get('invoice_ids', [])}")
            print(f"   🎯 Confidence Score: {result.get('confidence_score', 0):.1%}")
            print(f"   ⚡ Processing Time: {processing_time:.0f}ms")
            
            if result.get('document_analysis'):
                analysis = result['document_analysis'][0]
                tier = analysis.get('tier_used', 'unknown')
                cost = analysis.get('cost_estimate', 0)
                
                print(f"   🤖 Tier Used: {tier}")
                print(f"   💰 Cost Estimate: ${cost:.3f}")
                
                # Explain the tier
                tier_explanation = {
                    'pattern_matching': '🟢 FREE - Regex patterns found invoice IDs',
                    'layoutlm_onnx': '🟡 LOW COST - ML model needed for extraction', 
                    'azure_form_recognizer': '🔴 HIGHER COST - Cloud OCR required',
                    'mock_e2e': '🧪 TEST MODE - Using mock extraction'
                }
                
                explanation = tier_explanation.get(tier, '❓ Unknown tier')
                print(f"   📊 Tier Explanation: {explanation}")
            
            # Show warnings if any
            if result.get('warnings'):
                print(f"   ⚠️  Warnings: {', '.join(result['warnings'])}")
                
            return True
            
        else:
            print(f"❌ API Error: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return False

def interactive_test():
    """Interactive testing session"""
    print("🚀 CashUp Agent - Real Invoice Testing Tool")
    print("=" * 60)
    print("Instructions:")
    print("1. Copy text content from your invoice PDFs")
    print("2. Paste it when prompted")
    print("3. See how the three-tier ML system performs")
    print("4. Type 'quit' to exit")
    print()
    
    invoice_count = 0
    
    while True:
        print(f"\n📄 Invoice #{invoice_count + 1}")
        print("-" * 30)
        
        # Get invoice name
        invoice_name = input("Invoice name (or 'quit' to exit): ").strip()
        if invoice_name.lower() == 'quit':
            break
            
        if not invoice_name:
            invoice_name = f"Invoice-{invoice_count + 1}"
        
        # Get invoice content
        print(f"\nPaste the text content of '{invoice_name}':")
        print("(Press Enter twice when done)")
        
        lines = []
        while True:
            line = input()
            if line == "" and len(lines) > 0:
                break
            lines.append(line)
        
        invoice_text = "\n".join(lines)
        
        if invoice_text.strip():
            # Test the invoice
            success = test_invoice(invoice_text, invoice_name)
            if success:
                invoice_count += 1
        else:
            print("⚠️  No content provided, skipping...")
    
    print(f"\n🎉 Testing Complete!")
    print(f"📊 Total invoices tested: {invoice_count}")
    print(f"📈 View results in Grafana: http://localhost:3000/d/cashup-ml-system")
    print(f"🔍 Check service health: http://localhost:8012/health")

def quick_examples():
    """Test with some example invoices"""
    print("🧪 Running Quick Examples...")
    
    examples = [
        {
            "name": "Standard Invoice",
            "content": """INVOICE
Invoice #: INV-2024-001
Date: January 15, 2024
Bill To: ABC Company Ltd
123 Business Street
Amount Due: $2,450.00
Terms: Net 30 Days"""
        },
        {
            "name": "Unilever Invoice", 
            "content": """UNILEVER INVOICE
Invoice Number: UNI-240156789
Date: 2024-01-20
Customer: Retail Store Chain
Products: Dove Soap, Axe Deodorant
Total Amount: $4,850.00
Payment Terms: 30 days"""
        },
        {
            "name": "Purchase Order",
            "content": """PURCHASE ORDER INVOICE
PO Number: PO-2024-4567
Reference: REF-ABC123
Vendor: Office Supplies Inc
Items: Paper, Pens, Folders
Net Amount: $890.50
VAT: $178.10
Total: $1,068.60"""
        }
    ]
    
    for example in examples:
        test_invoice(example["content"], example["name"])
        time.sleep(1)  # Brief pause between tests

if __name__ == "__main__":
    print("Choose testing mode:")
    print("1. Interactive testing (paste your invoices)")
    print("2. Quick examples")
    
    choice = input("\nEnter choice (1 or 2): ").strip()
    
    if choice == "2":
        quick_examples()
    else:
        interactive_test()