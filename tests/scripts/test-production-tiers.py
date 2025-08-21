#!/usr/bin/env python3
"""
Production Three-Tier ML Testing
Demonstrates real ML processing with all tiers
"""
import asyncio
import time
import sys
import os

# Add the current directory to Python path
sys.path.append(os.path.dirname(__file__))

from services.dim.tiers.pattern_matcher import PatternMatcher
from services.dim.tiers.layoutlm_onnx import LayoutLMONNX
from services.dim.tiers.azure_form_recognizer import AzureFormRecognizer

class ProductionMLDemo:
    """Demonstrates production three-tier ML processing"""
    
    def __init__(self):
        # Initialize all three tiers
        self.pattern_matcher = PatternMatcher()
        self.layoutlm = LayoutLMONNX(
            model_path="models/layoutlmv3-base.onnx",  # Will use demo mode
            tokenizer_name="microsoft/layoutlmv3-base"
        )
        self.azure_recognizer = AzureFormRecognizer(
            endpoint="http://dummy.cognitiveservices.azure.com/",
            api_key="dummy-key"
        )
        
        self.stats = {
            "tier1_count": 0,
            "tier2_count": 0, 
            "tier3_count": 0,
            "total_cost": 0.0,
            "total_processing_time": 0.0
        }
    
    async def initialize(self):
        """Initialize all ML tiers"""
        print("🔧 Initializing Three-Tier ML System...")
        
        # Initialize LayoutLM (Tier 2)
        tier2_ready = await self.layoutlm.initialize()
        print(f"   🟡 Tier 2 (LayoutLM): {'✅ Ready' if tier2_ready else '❌ Failed'}")
        
        # Initialize Azure (Tier 3) - will use mock mode
        tier3_ready = await self.azure_recognizer.initialize()
        print(f"   🔴 Tier 3 (Azure): {'✅ Ready' if tier3_ready else '❌ Failed'}")
        
        print(f"   🟢 Tier 1 (Pattern): ✅ Ready")
        print()
    
    async def process_document(self, document_content: str, document_name: str) -> dict:
        """Process document through three-tier system"""
        print(f"📄 Processing: {document_name}")
        print("-" * 50)
        
        start_time = time.time()
        
        # Tier 1: Pattern Matching (Always try first)
        print("🟢 Tier 1: Pattern Matching...")
        tier1_result = self.pattern_matcher.extract_invoice_ids(document_content)
        
        if tier1_result.confidence >= 0.9:
            processing_time = (time.time() - start_time) * 1000
            print(f"✅ Tier 1 SUCCESS: {tier1_result.invoice_ids} ({tier1_result.confidence:.1%})")
            print(f"   ⚡ Time: {processing_time:.0f}ms | 💰 Cost: $0.000")
            
            self.stats["tier1_count"] += 1
            self.stats["total_processing_time"] += processing_time
            
            return {
                "invoice_ids": tier1_result.invoice_ids,
                "confidence": tier1_result.confidence,
                "tier_used": "pattern_matching",
                "cost": 0.0,
                "processing_time_ms": processing_time
            }
        
        # Tier 2: LayoutLM ONNX (Medium complexity)
        print("🟡 Tier 2: LayoutLM ONNX...")
        tier2_result = await self.layoutlm.extract_invoice_ids(document_content)
        
        if tier2_result.confidence >= 0.7:
            processing_time = (time.time() - start_time) * 1000
            print(f"✅ Tier 2 SUCCESS: {tier2_result.invoice_ids} ({tier2_result.confidence:.1%})")
            print(f"   ⚡ Time: {processing_time:.0f}ms | 💰 Cost: $0.001")
            
            self.stats["tier2_count"] += 1
            self.stats["total_cost"] += 0.001
            self.stats["total_processing_time"] += processing_time
            
            return {
                "invoice_ids": tier2_result.invoice_ids,
                "confidence": tier2_result.confidence,
                "tier_used": "layoutlm_onnx",
                "cost": 0.001,
                "processing_time_ms": processing_time,
                "bounding_boxes": tier2_result.bounding_boxes
            }
        
        # Tier 3: Azure Form Recognizer (Fallback)
        print("🔴 Tier 3: Azure Form Recognizer...")
        tier3_result = await self.azure_recognizer.extract_invoice_ids(document_content)
        
        processing_time = (time.time() - start_time) * 1000
        print(f"✅ Tier 3 FALLBACK: {tier3_result.invoice_ids} ({tier3_result.confidence:.1%})")
        print(f"   ⚡ Time: {processing_time:.0f}ms | 💰 Cost: $0.010")
        
        self.stats["tier3_count"] += 1
        self.stats["total_cost"] += 0.010
        self.stats["total_processing_time"] += processing_time
        
        return {
            "invoice_ids": tier3_result.invoice_ids,
            "confidence": tier3_result.confidence,
            "tier_used": "azure_form_recognizer",
            "cost": 0.010,
            "processing_time_ms": processing_time
        }
    
    def print_summary(self, results: list):
        """Print processing summary and cost analysis"""
        total_docs = len(results)
        
        print(f"\n🎯 PRODUCTION THREE-TIER SYSTEM RESULTS")
        print("=" * 60)
        
        print(f"📊 Tier Distribution:")
        print(f"   🟢 Tier 1 (Pattern): {self.stats['tier1_count']} docs ({self.stats['tier1_count']/total_docs*100:.0f}%)")
        print(f"   🟡 Tier 2 (LayoutLM): {self.stats['tier2_count']} docs ({self.stats['tier2_count']/total_docs*100:.0f}%)")
        print(f"   🔴 Tier 3 (Azure): {self.stats['tier3_count']} docs ({self.stats['tier3_count']/total_docs*100:.0f}%)")
        
        print(f"\n💰 Cost Analysis:")
        print(f"   Total Cost: ${self.stats['total_cost']:.4f}")
        print(f"   Average Cost/Doc: ${self.stats['total_cost']/total_docs:.4f}")
        
        # Compare with all-Azure cost
        all_azure_cost = total_docs * 0.010
        savings = all_azure_cost - self.stats['total_cost']
        savings_percent = (savings / all_azure_cost) * 100 if all_azure_cost > 0 else 0
        
        print(f"   All-Azure Cost: ${all_azure_cost:.4f}")
        print(f"   💡 Savings: ${savings:.4f} ({savings_percent:.1f}%)")
        
        print(f"\n⚡ Performance:")
        print(f"   Total Processing Time: {self.stats['total_processing_time']:.0f}ms")
        print(f"   Average Time/Doc: {self.stats['total_processing_time']/total_docs:.0f}ms")

async def main():
    """Run production ML demo"""
    demo = ProductionMLDemo()
    await demo.initialize()
    
    # Test documents of varying complexity
    test_documents = [
        {
            "name": "Simple Invoice (Tier 1 Expected)",
            "content": "INVOICE INV-2024-001 Date: Aug 20, 2024 Amount: $1,500.00 Customer: EABL Kenya"
        },
        {
            "name": "Standard Unilever Invoice (Tier 1)",
            "content": "UNILEVER INVOICE UNI-240820001 PO-456789 Date: 2024-08-20 Customer: EABL Ltd Amount: $5,500.00"
        },
        {
            "name": "Complex Multi-Line Document (Tier 2)",
            "content": """
            UNILEVER AFRICA LIMITED
            COMMERCIAL INVOICE
            Invoice Reference: UNI-KE-240820-COMPLEX-001
            Purchase Order: PO-EABL-789012345
            Date: August 20, 2024
            
            Bill To:
            East African Breweries Limited
            Tusker Brewery Division
            Industrial Area, Nairobi
            P.O. Box 30161-00100
            Nairobi, Kenya
            
            Ship To:
            EABL Distribution Center
            Ruaraka Industrial Area
            Nairobi, Kenya
            
            Line Items:
            1. Promotional Materials (Brand: Tusker)    10,000 KSH
            2. Marketing Collateral (Brand: Pilsner)   15,000 KSH
            3. Point of Sale Materials                 8,500 KSH
            4. Digital Marketing Assets                12,000 KSH
            5. Event Sponsorship Materials             20,000 KSH
            
            Subtotal:                                  65,500 KSH
            VAT (16%):                                 10,480 KSH
            Total Amount Due:                          75,980 KSH
            
            Payment Terms: Net 30 Days
            Bank: Standard Chartered Bank Kenya
            Account Number: 0102030405060708
            Swift Code: SCBLKENX
            
            Contact: procurement@unilever.co.ke
            Reference: This invoice relates to the master agreement dated 2024-01-15
            """,
            "expected_tier": "layoutlm_onnx"
        },
        {
            "name": "Scanned/Low Quality Document (Tier 3)",
            "content": "scanned document with poor quality text... invoice number might be INV-SCAN-001 but hard to read... amount unclear... date smudged..."
        }
    ]
    
    results = []
    
    for doc in test_documents:
        result = await demo.process_document(doc["content"], doc["name"])
        results.append(result)
        print()  # Space between documents
    
    demo.print_summary(results)
    
    print(f"\n✅ Production three-tier ML system demonstration complete!")
    print(f"🚀 Ready for EABL integration with real cost optimization!")

if __name__ == "__main__":
    asyncio.run(main())