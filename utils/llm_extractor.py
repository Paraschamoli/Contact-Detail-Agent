"""
LLM-based contact information extractor using Claude 3.5
Handles dirty text, obfuscated email formats, and deep detail extraction
"""

import os
import json
from typing import Optional, List
from pydantic import BaseModel, Field
from openai import OpenAI


class ExecutiveInfo(BaseModel):
    """Pydantic model for a key executive"""
    name: Optional[str] = Field(default=None, description="Executive's full name")
    title: Optional[str] = Field(default=None, description="Job title or designation")


class CompanyProfile(BaseModel):
    """Pydantic model for deep detail company extraction"""
    company_name: Optional[str] = Field(default=None, description="Official name of the company")
    direct_emails: Optional[List[str]] = Field(default=None, description="List of department-specific emails (e.g., sales@, exports@, info@). Decoded from obfuscated formats.")
    phone_numbers: Optional[List[str]] = Field(default=None, description="List of phone numbers in validated international format (e.g., +91-22-12345678)")
    key_executives: Optional[List[ExecutiveInfo]] = Field(default=None, description="List of key executives with names and titles")
    export_details: Optional[List[str]] = Field(default=None, description="Specific descriptions of what the company exports (e.g., 'Cold-rolled steel sheets' not just 'Steel')")
    certifications: Optional[List[str]] = Field(default=None, description="Certifications found (CE, ISO 9001, ISO 14001, REX registration, etc.)")
    export_region: Optional[str] = Field(default=None, description="Export markets or regions the company serves")
    website: Optional[str] = Field(default=None, description="Company website URL")
    location: Optional[str] = Field(default=None, description="Company address or location")


class CompanyContact(BaseModel):
    """Pydantic model for basic company contact information (backward compatible)"""
    company_name: Optional[str] = Field(default=None, description="Name of the company")
    official_email: Optional[str] = Field(default=None, description="Official email address (handles obfuscated formats like 'sales [at] company . com')")
    phone_number: Optional[str] = Field(default=None, description="Phone number")
    export_region: Optional[str] = Field(default=None, description="Export region or markets the company serves")


class LLMExtractor:
    """Extract company contact information from HTML/text using Claude 3.5 via OpenRouter.
    
    Handles dirty text, obfuscated email formats, and ensures no hallucination
    by returning null for missing fields. Supports both basic and deep detail extraction.
    """
    
    def __init__(self, model: str = "anthropic/claude-3.5-sonnet"):
        """Initialize the LLM extractor.
        
        Args:
            model: Model identifier for OpenRouter. Defaults to Claude 3.5 Sonnet.
        """
        self.model = model
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
        
        # Initialize OpenRouter client
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )
    
    def extract_contacts(self, html_content: str, url: Optional[str] = None) -> CompanyContact:
        """Extract basic company contact information from HTML content.
        
        Args:
            html_content: Raw HTML or text content
            url: Source URL for reference (optional)
            
        Returns:
            CompanyContact object with extracted information
        """
        prompt = self._build_extraction_prompt(html_content, url)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            return CompanyContact(**data)
            
        except Exception as e:
            print(f"Error during extraction: {e}")
            return CompanyContact()
    
    def extract_deep_profile(self, crawled_text: str, url: Optional[str] = None) -> CompanyProfile:
        """Extract deep detail company profile from combined crawled text.
        
        Synthesizes data from multiple scraped sub-pages into one clean profile
        using Claude 3.5 Sonnet with a long context window.
        
        Args:
            crawled_text: Combined text blob from deep crawl (homepage + sub-pages)
            url: Source URL for reference (optional)
            
        Returns:
            CompanyProfile object with detailed extracted information
        """
        prompt = self._build_deep_extraction_prompt(crawled_text, url)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_deep_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=4096,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            # Parse key_executives into ExecutiveInfo objects
            if data.get("key_executives"):
                parsed_executives = []
                for exec_data in data["key_executives"]:
                    if isinstance(exec_data, dict):
                        parsed_executives.append(ExecutiveInfo(**exec_data))
                    elif isinstance(exec_data, str):
                        parsed_executives.append(ExecutiveInfo(name=exec_data, title=None))
                data["key_executives"] = parsed_executives
            
            return CompanyProfile(**data)
            
        except Exception as e:
            print(f"Error during deep extraction: {e}")
            return CompanyProfile()
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for basic extraction."""
        return """You are a precise contact information extractor. Your task is to extract company details from HTML/text content.

CRITICAL RULES:
1. ONLY extract information that is explicitly present in the text
2. If a field is not found, return null for that field - DO NOT hallucinate or guess
3. Handle obfuscated email formats: convert "sales [at] company . com" to "sales@company.com"
4. Handle various email obfuscations: [at], (at), @, [at], "at", etc.
5. Remove spaces around @ symbols in emails
6. Extract the most official-looking email (e.g., info@, contact@, sales@, not personal emails)
7. For phone numbers, extract the main business phone if available
8. For export_region, look for mentions of export markets, regions served, or geographic coverage
9. Return ONLY valid JSON - no additional text or explanations

Return a JSON object with these exact fields:
- company_name (string or null)
- official_email (string or null)
- phone_number (string or null)
- export_region (string or null)"""
    
    def _get_deep_system_prompt(self) -> str:
        """Get the system prompt for deep detail extraction."""
        return """You are a precise, deep-detail company profile extractor for international trade research. Your task is to synthesize information from multiple scraped web pages (homepage, contact, about, team pages) into ONE clean, comprehensive company profile.

CRITICAL RULES:
1. ONLY extract information that is EXPLICITLY present in the text - DO NOT hallucinate, guess, or infer
2. If a field is not found, return null for that field
3. The input text may contain content from multiple pages separated by "--- HOMEPAGE ---" and "--- SUB-PAGE ---" markers. Synthesize across ALL pages.
4. Handle obfuscated email formats: convert "sales [at] company . com" to "sales@company.com"
5. Handle various email obfuscations: [at], (at), {at}, "at", &#64;, etc.
6. Remove spaces around @ symbols in emails

EXTRACTION GUIDELINES:

direct_emails: Extract ALL department-specific emails you find. Common patterns:
  - sales@, exports@, export@, marketing@, info@, contact@, support@
  - If only one generic email exists, put it in the list
  - Decode obfuscated formats: "exports [at] company . com" → "exports@company.com"
  - Return null if no emails found at all

phone_numbers: Extract ALL phone numbers in international format:
  - Include country code: +91-22-12345678, +49-89-123456, +1-555-123-4567
  - Normalize formats: "(022) 1234 5678" in India → "+91-22-12345678"
  - Separate multiple numbers (landline, mobile, fax) as separate entries
  - Return null if no phone numbers found

key_executives: Extract names and titles of leadership:
  - Look for CEO, Managing Director, Director, VP, President, Founder, Chairman, CFO, CTO
  - Look in "Our Team", "Management", "Leadership", "About Us" sections
  - Each entry should have name and title if both are available
  - Return null if no executives mentioned

export_details: Be SPECIFIC about what they export:
  - BAD: "Steel", "Textiles", "Chemicals"
  - GOOD: "Cold-rolled steel sheets", "Organic cotton yarn", "Specialty pharmaceutical intermediates"
  - Look for product catalogs, product pages, export lists, HS code mentions
  - Return null if no export products mentioned

certifications: Extract any certifications or registrations:
  - ISO 9001, ISO 14001, ISO 22000, ISO 45001, OHSAS
  - CE marking, UL listing, GMP, FSSAI
  - REX registration (EU GSP), AEO (Authorized Economic Operator)
  - BIS, FSSC 22000, IATF 16949, AS9100
  - Return null if no certifications mentioned

Return ONLY valid JSON with these exact fields:
{
  "company_name": "string or null",
  "direct_emails": ["email1@company.com", "exports@company.com"] or null,
  "phone_numbers": ["+91-22-12345678"] or null,
  "key_executives": [{"name": "John Doe", "title": "CEO"}] or null,
  "export_details": ["Cold-rolled steel sheets", "Hot-dip galvanized coils"] or null,
  "certifications": ["ISO 9001:2015", "CE", "REX registered"] or null,
  "export_region": "string or null",
  "website": "string or null",
  "location": "string or null"
}"""
    
    def _build_extraction_prompt(self, html_content: str, url: Optional[str] = None) -> str:
        """Build the extraction prompt for basic extraction.
        
        Args:
            html_content: Raw HTML or text content
            url: Source URL for reference
            
        Returns:
            Formatted prompt string
        """
        content_limit = 15000
        truncated_content = html_content[:content_limit]
        
        prompt = f"""Extract company contact information from the following content.
"""
        
        if url:
            prompt += f"Source URL: {url}\n\n"
        
        prompt += f"""Content to analyze:
{truncated_content}

Extract the following information:
- company_name: The official name of the company
- official_email: The official email address (decode obfuscated formats like 'sales [at] company . com')
- phone_number: The main business phone number
- export_region: Export markets or regions the company serves

Return ONLY a JSON object with these four fields. Use null for any missing information."""
        
        return prompt
    
    def _build_deep_extraction_prompt(self, crawled_text: str, url: Optional[str] = None) -> str:
        """Build the extraction prompt for deep detail extraction.
        
        Args:
            crawled_text: Combined text blob from deep crawl
            url: Source URL for reference
            
        Returns:
            Formatted prompt string
        """
        # Use a larger limit for deep extraction (Claude 3.5 supports long context)
        content_limit = 50000
        truncated_content = crawled_text[:content_limit]
        
        prompt = f"""Extract a comprehensive deep-detail company profile from the following crawled content.
"""
        
        if url:
            prompt += f"Source URL: {url}\n\n"
        
        prompt += f"""CRAWLED CONTENT (may include multiple pages):
{truncated_content}

Extract ALL of the following:
- company_name: Official company name
- direct_emails: ALL department emails found (sales@, exports@, info@, etc.) - decode obfuscated formats
- phone_numbers: ALL phone numbers in international format with country codes
- key_executives: Names and titles of key leadership personnel
- export_details: SPECIFIC product descriptions of what they export (not generic categories)
- certifications: Any certifications mentioned (ISO, CE, REX, etc.)
- export_region: Export markets or regions served
- website: Company website URL
- location: Company address or location

Return ONLY a JSON object. Use null for any field where no information is found. Use empty arrays [] only if the field type is a list and you found zero items but the section exists (e.g., a "Contact" page with no emails). Otherwise use null."""
        
        return prompt
    
    def extract_from_multiple_pages(self, content_dict: dict, base_url: Optional[str] = None) -> CompanyContact:
        """Extract from multiple pages (main, contact, about) and merge results.
        
        Args:
            content_dict: Dictionary with page content (keys: 'main', 'contact', 'about')
            base_url: Base URL for reference
            
        Returns:
            CompanyContact object with merged information
        """
        merged_contact = CompanyContact()
        
        for page_type, content in content_dict.items():
            if content:
                try:
                    page_contact = self.extract_contacts(content, base_url)
                    
                    # Merge: use non-null values from page_contact
                    if page_contact.company_name and not merged_contact.company_name:
                        merged_contact.company_name = page_contact.company_name
                    if page_contact.official_email and not merged_contact.official_email:
                        merged_contact.official_email = page_contact.official_email
                    if page_contact.phone_number and not merged_contact.phone_number:
                        merged_contact.phone_number = page_contact.phone_number
                    if page_contact.export_region and not merged_contact.export_region:
                        merged_contact.export_region = page_contact.export_region
                        
                except Exception as e:
                    print(f"Error extracting from {page_type} page: {e}")
                    continue
        
        return merged_contact
    
    def extract_deep_from_crawled_text(self, crawled_text: str, url: Optional[str] = None) -> CompanyProfile:
        """Extract deep profile from the combined crawled text blob.
        
        This is the primary method for the deep detail pipeline - it takes the
        combined text from deep_crawl_company() and synthesizes it into one
        clean CompanyProfile using Claude 3.5's long context window.
        
        Args:
            crawled_text: Combined text blob from CrawlerToolkit.deep_crawl_company()
            url: Source URL for reference
            
        Returns:
            CompanyProfile with detailed extracted information
        """
        if not crawled_text or len(crawled_text.strip()) < 50:
            print(f"  [deep_extract] Text too short for extraction ({len(crawled_text) if crawled_text else 0} chars)")
            return CompanyProfile(website=url)
        
        print(f"  [deep_extract] Extracting deep profile from {len(crawled_text)} chars...")
        profile = self.extract_deep_profile(crawled_text, url)
        
        # Log extraction results
        fields_found = sum(1 for field in [
            profile.company_name, profile.direct_emails, profile.phone_numbers,
            profile.key_executives, profile.export_details, profile.certifications,
            profile.export_region, profile.website, profile.location
        ] if field is not None)
        
        print(f"  [deep_extract] Extracted {fields_found}/9 fields")
        if profile.direct_emails:
            print(f"  [deep_extract]   Emails: {len(profile.direct_emails)} found")
        if profile.phone_numbers:
            print(f"  [deep_extract]   Phones: {len(profile.phone_numbers)} found")
        if profile.key_executives:
            print(f"  [deep_extract]   Executives: {len(profile.key_executives)} found")
        if profile.export_details:
            print(f"  [deep_extract]   Export products: {len(profile.export_details)} found")
        if profile.certifications:
            print(f"  [deep_extract]   Certifications: {len(profile.certifications)} found")
        
        return profile
