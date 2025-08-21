#!/bin/bash
# Test script for real invoice documents
echo "🔍 Testing CashUp Agent with Real Invoice Data"
echo "=============================================="

# Function to test a single invoice
test_invoice() {
    local invoice_text="$1"
    local invoice_name="$2"
    
    echo ""
    echo "📄 Testing: $invoice_name"
    echo "----------------------------------------"
    
    # Call the DIM service
    result=$(curl -s -X POST http://localhost:8012/api/v1/parse_document \
        -H "Content-Type: application/json" \
        -d "{\"document_uris\": [\"$invoice_name\"], \"client_id\": \"real-test\"}")
    
    # Extract key information
    invoice_ids=$(echo "$result" | jq -r '.invoice_ids[]' 2>/dev/null)
    confidence=$(echo "$result" | jq -r '.confidence_score' 2>/dev/null)
    tier_used=$(echo "$result" | jq -r '.document_analysis[0].tier_used' 2>/dev/null)
    cost=$(echo "$result" | jq -r '.document_analysis[0].cost_estimate' 2>/dev/null)
    
    echo "✅ Results:"
    echo "   Invoice IDs: $invoice_ids"
    echo "   Confidence: $confidence"
    echo "   Tier Used: $tier_used"
    echo "   Cost: \$$cost"
    echo "   Raw Response: $result"
}

# Example usage - Replace these with your actual invoice text
echo "To use this script:"
echo "1. Replace the example text below with your real invoice content"
echo "2. Run: bash test-real-invoices.sh"
echo ""

# Test Invoice 1 - REPLACE THIS WITH YOUR REAL INVOICE TEXT
test_invoice "INVOICE #INV-2024-001
Date: January 15, 2024
Bill To: Your Company
Amount: \$1,250.00
Terms: Net 30" "Real Invoice 1"

# Test Invoice 2 - ADD MORE REAL INVOICES HERE
test_invoice "Invoice Number: 202401-ABC123
Vendor: ABC Corp
Total Amount: \$3,450.00
Due Date: 02/15/2024" "Real Invoice 2"

echo ""
echo "🎯 To test with YOUR invoices:"
echo "1. Copy text from your PDF invoices"
echo "2. Replace the example text in this script"
echo "3. Run the script again"
echo ""
echo "📊 Check results in Grafana: http://localhost:3000/d/cashup-ml-system"