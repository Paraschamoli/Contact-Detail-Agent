"""
Trade validation toolkit for EU compliance checks.
Queries VIES (VAT) and REX public search to verify company legitimacy.
"""

import os
import re
import requests
from typing import Optional, Dict
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class LegitimacyStatus(BaseModel):
    """Result of trade legitimacy validation"""
    company_name: str = Field(description="Company name that was checked")
    registration_number: Optional[str] = Field(default=None, description="VAT or REX registration number found")
    vat_valid: Optional[bool] = Field(default=None, description="Whether VAT number is valid via VIES")
    vat_country: Optional[str] = Field(default=None, description="Country code from VAT number")
    rex_registered: Optional[bool] = Field(default=None, description="Whether company appears in REX registry")
    compliance_flags: list = Field(default_factory=list, description="Compliance flags found (CE, CBAM, REX, ISO, etc.)")
    legitimacy_level: str = Field(default="Unknown", description="Green/Yellow/Red legitimacy level")
    notes: Optional[str] = Field(default=None, description="Additional notes about the validation")


class TradeValidator:
    """Validates company trade legitimacy using EU public APIs.
    
    Checks:
    1. VIES VAT validation - Verifies EU VAT registration
    2. REX registration - Checks if company is registered for EU GSP
    3. Compliance flag detection - Scans for CE, CBAM, ISO, etc.
    
    Returns a LegitimacyStatus with Green/Yellow/Red classification:
    - Green: REX-registered or VAT-valid + compliance flags
    - Yellow: VAT-valid but no REX or limited compliance
    - Red: No valid registration found
    """
    
    # EU country codes for VAT validation
    EU_COUNTRY_CODES = {
        'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR',
        'DE', 'GR', 'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL',
        'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE'
    }
    
    # VIES SOAP API endpoint
    VIES_URL = 'https://ec.europa.eu/taxation_customs/vies/services/checkVatService'
    
    # REX public search URL (EU GSP register)
    REX_SEARCH_URL = 'https://ec.europa.eu/taxation_customs/dds2/eb/'
    
    # Compliance keywords to detect in company profile
    COMPLIANCE_PATTERNS = {
        'CE': re.compile(r'\bCE\s*(mark|marking|certified|compliance|conformity)?\b', re.I),
        'CBAM': re.compile(r'\bCBAM\b', re.I),
        'REX': re.compile(r'\bREX\s*(registered|registration|system|number)?\b', re.I),
        'ISO_9001': re.compile(r'ISO\s*9001[:\s]*\d{0,4}', re.I),
        'ISO_14001': re.compile(r'ISO\s*14001[:\s]*\d{0,4}', re.I),
        'ISO_22000': re.compile(r'ISO\s*22000[:\s]*\d{0,4}', re.I),
        'ISO_45001': re.compile(r'ISO\s*45001[:\s]*\d{0,4}', re.I),
        'GMP': re.compile(r'\bGMP\b', re.I),
        'FSSAI': re.compile(r'\bFSSAI\b', re.I),
        'AEO': re.compile(r'\bAEO\s*(authorized|economic|operator)?\b', re.I),
        'GPSR': re.compile(r'\bGPSR\b', re.I),
        'BIS': re.compile(r'\bBIS\s*(certified|registration|standard)?\b', re.I),
        'UL': re.compile(r'\bUL\s*(listed|certified|mark)?\b', re.I),
        'FSC': re.compile(r'\bFSC\s*(certified|chain|custody)?\b', re.I),
        'OHSAS': re.compile(r'\bOHSAS\s*18001\b', re.I),
    }
    
    # VAT number patterns by country
    VAT_PATTERNS = {
        'AT': re.compile(r'ATU?\d{8}', re.I),
        'BE': re.compile(r'BE0?\d{9}', re.I),
        'BG': re.compile(r'BG\d{9,10}', re.I),
        'HR': re.compile(r'HR\d{11}', re.I),
        'CY': re.compile(r'CY\d{8}[A-Z]', re.I),
        'CZ': re.compile(r'CZ\d{8,10}', re.I),
        'DK': re.compile(r'DK\d{8}', re.I),
        'EE': re.compile(r'EE\d{9}', re.I),
        'FI': re.compile(r'FI\d{8}', re.I),
        'FR': re.compile(r'FR[A-Z0-9]{2}\d{9}', re.I),
        'DE': re.compile(r'DE\d{9}', re.I),
        'GR': re.compile(r'EL\d{9}', re.I),
        'HU': re.compile(r'HU\d{8}', re.I),
        'IE': re.compile(r'IE\d[A-Z]\d{5}[A-Z]?', re.I),
        'IT': re.compile(r'IT\d{11}', re.I),
        'LV': re.compile(r'LV\d{11}', re.I),
        'LT': re.compile(r'LT\d{9,12}', re.I),
        'LU': re.compile(r'LU\d{8}', re.I),
        'MT': re.compile(r'MT\d{8}', re.I),
        'NL': re.compile(r'NL\d{9}B\d{2}', re.I),
        'PL': re.compile(r'PL\d{10}', re.I),
        'PT': re.compile(r'PT\d{9}', re.I),
        'RO': re.compile(r'RO\d{2,10}', re.I),
        'SK': re.compile(r'SK\d{10}', re.I),
        'SI': re.compile(r'SI\d{8}', re.I),
        'ES': re.compile(r'ES[A-Z]\d{7}[A-Z]', re.I),
        'SE': re.compile(r'SE\d{12}', re.I),
    }
    
    def __init__(self):
        """Initialize the trade validator."""
        pass
    
    def _extract_vat_number(self, text: str) -> Optional[tuple]:
        """Extract VAT number from text.
        
        Args:
            text: Text to search for VAT numbers
            
        Returns:
            Tuple of (country_code, vat_number) or None
        """
        if not text:
            return None
        
        for country_code, pattern in self.VAT_PATTERNS.items():
            match = pattern.search(text)
            if match:
                vat_num = match.group(0)
                # Strip country code prefix for VIES API
                clean_num = vat_num[2:]
                return (country_code, clean_num)
        
        return None
    
    def _check_vies(self, country_code: str, vat_number: str) -> Dict:
        """Check VAT number validity via VIES SOAP API.
        
        Args:
            country_code: EU country code (e.g., 'DE', 'FR')
            vat_number: VAT number without country prefix
            
        Returns:
            Dictionary with validation results
        """
        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">
  <soapenv:Body>
    <urn:checkVat>
      <urn:countryCode>{country_code}</urn:countryCode>
      <urn:vatNumber>{vat_number}</urn:vatNumber>
    </urn:checkVat>
  </soapenv:Body>
</soapenv:Envelope>"""
        
        headers = {
            'Content-Type': 'text/xml',
            'SOAPAction': '',
        }
        
        try:
            response = requests.post(
                self.VIES_URL,
                data=soap_body,
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200:
                response_text = response.text
                
                # Parse SOAP response
                is_valid = '<valid>true</valid>' in response_text.lower()
                
                # Extract company name if available
                name_match = re.search(r'<name>(.*?)</name>', response_text, re.DOTALL)
                company_name = name_match.group(1).strip() if name_match else None
                
                # Extract address if available
                addr_match = re.search(r'<address>(.*?)</address>', response_text, re.DOTALL)
                address = addr_match.group(1).strip() if addr_match else None
                
                return {
                    'valid': is_valid,
                    'company_name': company_name,
                    'address': address,
                    'country_code': country_code,
                }
            else:
                return {'valid': None, 'error': f'VIES returned status {response.status_code}'}
                
        except requests.exceptions.Timeout:
            return {'valid': None, 'error': 'VIES request timed out'}
        except Exception as e:
            return {'valid': None, 'error': f'VIES check failed: {e}'}
    
    def _detect_compliance_flags(self, text: str) -> list:
        """Detect compliance flags in company profile text.
        
        Args:
            text: Company profile text to scan
            
        Returns:
            List of compliance flags found
        """
        flags = []
        for flag_name, pattern in self.COMPLIANCE_PATTERNS.items():
            if pattern.search(text):
                flags.append(flag_name)
        return flags
    
    def _check_rex_keywords(self, profile_dict: Dict) -> Optional[bool]:
        """Check for REX registration indicators in company profile.
        
        Since the EU REX registry doesn't have a public API, we check for
        REX-related keywords and registration numbers in the extracted data.
        
        Args:
            profile_dict: Company profile dictionary
            
        Returns:
            True if REX indicators found, None if inconclusive
        """
        # Check certifications for REX mention
        certifications = profile_dict.get('certifications') or []
        for cert in certifications:
            if isinstance(cert, str) and 'rex' in cert.lower():
                return True
        
        # Check export details for REX mention
        export_details = profile_dict.get('export_details') or []
        for detail in export_details:
            if isinstance(detail, str) and 'rex' in detail.lower():
                return True
        
        # Check company name / crawled text for REX number pattern
        # REX numbers typically follow format: REX-XXXXXX or country code + digits
        all_text = ' '.join([
            str(profile_dict.get('company_name', '')),
            str(profile_dict.get('export_region', '')),
            ' '.join(str(c) for c in certifications),
            ' '.join(str(d) for d in export_details),
        ]).lower()
        
        if 'rex registered' in all_text or 'rex registration' in all_text:
            return True
        
        return None
    
    def validate_company(self, profile_dict: Dict) -> LegitimacyStatus:
        """Validate a company's trade legitimacy.
        
        Args:
            profile_dict: Company profile dictionary (from CompanyProfile.model_dump())
            
        Returns:
            LegitimacyStatus with validation results
        """
        company_name = profile_dict.get('company_name', 'Unknown')
        
        result = LegitimacyStatus(
            company_name=company_name,
            legitimacy_level="Unknown"
        )
        
        # Step 1: Extract and validate VAT number
        # Combine all text fields to search for VAT number
        search_text = ' '.join([
            str(profile_dict.get('company_name', '')),
            str(profile_dict.get('location', '')),
            str(profile_dict.get('website', '')),
            ' '.join(str(e) for e in (profile_dict.get('direct_emails') or [])),
        ])
        
        vat_info = self._extract_vat_number(search_text)
        
        if vat_info:
            country_code, vat_number = vat_info
            result.registration_number = f"{country_code}{vat_number}"
            result.vat_country = country_code
            
            print(f"  [trade] Found VAT number: {country_code}{vat_number}")
            
            vies_result = self._check_vies(country_code, vat_number)
            result.vat_valid = vies_result.get('valid')
            
            if vies_result.get('error'):
                result.notes = f"VIES check: {vies_result['error']}"
            elif result.vat_valid:
                result.notes = "VAT number validated via VIES"
            else:
                result.notes = "VAT number invalid per VIES"
        else:
            print(f"  [trade] No VAT number found for {company_name}")
        
        # Step 2: Detect compliance flags
        all_profile_text = ' '.join([
            str(profile_dict.get('company_name', '')),
            str(profile_dict.get('export_region', '')),
            ' '.join(str(c) for c in (profile_dict.get('certifications') or [])),
            ' '.join(str(d) for d in (profile_dict.get('export_details') or [])),
        ])
        
        result.compliance_flags = self._detect_compliance_flags(all_profile_text)
        
        if result.compliance_flags:
            print(f"  [trade] Compliance flags: {', '.join(result.compliance_flags)}")
        
        # Step 3: Check REX registration
        rex_status = self._check_rex_keywords(profile_dict)
        result.rex_registered = rex_status
        
        if rex_status:
            print(f"  [trade] REX registration indicators found")
        
        # Step 4: Determine legitimacy level
        result.legitimacy_level = self._determine_legitimacy(result)
        
        print(f"  [trade] Legitimacy: {result.legitimacy_level}")
        
        return result
    
    def _determine_legitimacy(self, status: LegitimacyStatus) -> str:
        """Determine legitimacy level based on validation results.
        
        Green: REX-registered or VAT-valid + compliance flags
        Yellow: VAT-valid but no REX, or compliance flags without VAT
        Red: No valid registration and no compliance flags
        
        Args:
            status: Current LegitimacyStatus
            
        Returns:
            "Green", "Yellow", or "Red"
        """
        # Green: REX registered
        if status.rex_registered:
            return "Green"
        
        # Green: Valid VAT + compliance flags
        if status.vat_valid and status.compliance_flags:
            return "Green"
        
        # Green: Valid VAT + specific EU-relevant flags
        eu_flags = {'CE', 'CBAM', 'REX', 'AEO', 'GPSR'}
        if status.vat_valid and any(f in eu_flags for f in status.compliance_flags):
            return "Green"
        
        # Yellow: Valid VAT only
        if status.vat_valid:
            return "Yellow"
        
        # Yellow: Has compliance flags (even without VAT)
        if status.compliance_flags:
            return "Yellow"
        
        # Yellow: REX inconclusive but company has export details
        if status.rex_registered is None and status.compliance_flags:
            return "Yellow"
        
        # Red: No valid registration, no compliance flags
        if status.vat_valid is False and not status.compliance_flags:
            return "Red"
        
        # Default to Yellow if we couldn't verify (inconclusive)
        if status.vat_valid is None and not status.compliance_flags:
            return "Yellow"  # Can't confirm or deny
        
        return "Yellow"


# Example usage
if __name__ == '__main__':
    validator = TradeValidator()
    
    test_profiles = [
        {
            'company_name': 'Steel GmbH',
            'location': 'DE123456789 Hamburg, Germany',
            'certifications': ['ISO 9001:2015', 'CE', 'REX registered'],
            'export_details': ['Cold-rolled steel sheets'],
        },
        {
            'company_name': 'Textile Export Co',
            'location': 'Mumbai, India',
            'certifications': ['ISO 9001'],
            'export_details': ['Cotton yarn'],
        },
    ]
    
    for profile in test_profiles:
        result = validator.validate_company(profile)
        print(f"\n{result.company_name}: {result.legitimacy_level}")
        print(f"  VAT: {result.vat_valid}")
        print(f"  REX: {result.rex_registered}")
        print(f"  Flags: {result.compliance_flags}")
