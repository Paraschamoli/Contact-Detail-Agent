#!/usr/bin/env python3
"""
Simple test to verify the system works without web crawling
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agents.search_agent import SearchAgent, CompanySeed
from utils.llm_extractor import LLMExtractor, CompanyContact, CompanyProfile
from utils.output_writer import OutputWriter

async def test_search_only():
    """Test just the search agent without crawling"""
    print("=== Testing Search Agent Only ===")
    
    try:
        # Initialize Search Agent
        search_agent = SearchAgent()
        
        # Gather seed list (small test)
        seed_list = search_agent.gather_seed_list(
            commodity="textiles",
            country="India",
            industry="textiles",
            queries_per_pattern=1  # Just 1 result per query
        )
        
        print(f"Found {len(seed_list)} company URLs")
        
        # Show first few results
        for i, seed in enumerate(seed_list[:3], 1):
            print(f"{i}. {seed.company_name} -> {seed.url}")
        
        return seed_list
        
    except Exception as e:
        print(f"Error in search: {e}")
        return []

def test_llm_extraction():
    """Test LLM extraction with sample HTML"""
    print("\n=== Testing LLM Extraction ===")
    
    sample_html = """
    <html>
    <head><title>ABC Textiles Inc.</title></head>
    <body>
        <h1>ABC Textiles Inc.</h1>
        <div class="contact">
            <p>Email: info [at] abctextiles . com</p>
            <p>Phone: +91-123-456-7890</p>
            <p>We export to USA, Europe, and Asia Pacific regions</p>
        </div>
    </body>
    </html>
    """
    
    try:
        extractor = LLMExtractor()
        contact = extractor.extract_contacts(sample_html, "https://example.com")
        
        print(f"Company: {contact.company_name}")
        print(f"Email: {contact.official_email}")
        print(f"Phone: {contact.phone_number}")
        print(f"Export Region: {contact.export_region}")
        
        return contact
        
    except Exception as e:
        print(f"Error in extraction: {e}")
        return None

def test_output_writer():
    """Test output writing"""
    print("\n=== Testing Output Writer ===")
    
    try:
        # Create sample contacts
        contacts = [
            CompanyProfile(
                company_name="ABC Textiles Inc.",
                direct_emails=["info@abctextiles.com"],
                phone_numbers=["+91-123-456-7890"],
                export_region="USA, Europe, Asia Pacific",
                country="India",
                product_category="textiles",
                eu_destinations=["Germany", "France"],
                website="https://abctextiles.com",
                contact_person="Mr. Raj Patel",
                business_description="Leading textile exporter from India"
            ),
            CompanyProfile(
                company_name="XYZ Garments Ltd.",
                direct_emails=["contact@xyzgarments.com"],
                phone_numbers=["+91-987-654-3210"],
                export_region="Europe, Middle East",
                country="India",
                product_category="garments",
                eu_destinations=["Netherlands", "Belgium"],
                website="https://xyzgarments.com",
                business_description="Garment manufacturer and exporter"
            )
        ]
        
        writer = OutputWriter(output_dir="test_output")
        filepath = writer.write_pydantic_to_csv(contacts, "test_leads")
        
        print(f"Output saved to: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"Error in output: {e}")
        return None

async def main():
    """Run all tests"""
    print("Testing Contact Detail Agent Components")
    print("=" * 50)
    
    # Test 1: Search Agent
    seed_list = await test_search_only()
    
    # Test 2: LLM Extraction
    contact = test_llm_extraction()
    
    # Test 3: Output Writer
    output_file = test_output_writer()
    
    print("\n=== Test Summary ===")
    print(f"Search Agent: {'✓' if seed_list else '✗'}")
    print(f"LLM Extractor: {'✓' if contact else '✗'}")
    print(f"Output Writer: {'✓' if output_file else '✗'}")
    
    if seed_list and contact and output_file:
        print("\n✓ All components working! Ready for full pipeline.")
    else:
        print("\n✗ Some components need attention.")

if __name__ == "__main__":
    asyncio.run(main())
