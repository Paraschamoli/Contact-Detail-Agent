"""
LLM-based contact information extractor using Claude 3.5
Handles dirty text and obfuscated email formats
"""

import os
import json
from typing import Optional
from pydantic import BaseModel, Field
from openai import OpenAI


class CompanyContact(BaseModel):
    """Pydantic model for extracted company contact information"""
    company_name: Optional[str] = Field(default=None, description="Name of the company")
    official_email: Optional[str] = Field(default=None, description="Official email address (handles obfuscated formats like 'sales [at] company . com')")
    phone_number: Optional[str] = Field(default=None, description="Phone number")
    export_region: Optional[str] = Field(default=None, description="Export region or markets the company serves")


class LLMExtractor:
    """Extract company contact information from HTML/text using Claude 3.5 via OpenRouter.
    
    Handles dirty text, obfuscated email formats, and ensures no hallucination
    by returning null for missing fields.
    """
    
    def __init__(self, model: str = "anthropic/claude-3.5-sonnet-20241022"):
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
        """Extract company contact information from HTML content.
        
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
                temperature=0.1,  # Low temperature for consistent extraction
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            # Validate and return using Pydantic model
            return CompanyContact(**data)
            
        except Exception as e:
            print(f"Error during extraction: {e}")
            # Return empty CompanyContact on error
            return CompanyContact()
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the LLM."""
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
    
    def _build_extraction_prompt(self, html_content: str, url: Optional[str] = None) -> str:
        """Build the extraction prompt.
        
        Args:
            html_content: Raw HTML or text content
            url: Source URL for reference
            
        Returns:
            Formatted prompt string
        """
        # Limit content to avoid token limits
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
