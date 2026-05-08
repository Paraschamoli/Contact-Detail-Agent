"""
CSV/Excel formatting logic with timestamp support and tiered lead categorization
"""

import csv
import json
from typing import List, Dict, Union
from datetime import datetime
from pathlib import Path
import pandas as pd
from pydantic import BaseModel


class OutputWriter:
    """Handles writing contact data to various formats (CSV, Excel) with timestamps and tiering"""
    
    def __init__(self, output_dir: str = "output"):
        """Initialize the output writer.
        
        Args:
            output_dir: Directory to save output files. Defaults to "output".
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def _categorize_tier(self, profile: Dict) -> str:
        """Categorize a company lead into a readiness tier.
        
        Tier 1: Verified email + specific export details (hot lead)
        Tier 2: Has email or phone + some export info (warm lead)
        Tier 3: Only website/name found (cold lead)
        
        Args:
            profile: Company profile dictionary (from CompanyProfile.model_dump())
            
        Returns:
            Tier string: "Tier 1", "Tier 2", or "Tier 3"
        """
        has_verified_email = profile.get('has_verified_email', False)
        direct_emails = profile.get('direct_emails') or []
        phone_numbers = profile.get('phone_numbers') or []
        export_details = profile.get('export_details') or []
        website = profile.get('website')
        company_name = profile.get('company_name')
        email_confidence = profile.get('email_confidence_avg', 0.0)
        
        has_email = bool(direct_emails)
        has_phone = bool(phone_numbers)
        has_export = bool(export_details)
        has_website = bool(website)
        has_name = bool(company_name)
        
        # Tier 1: Verified email + specific export details
        if has_verified_email and has_export:
            return "Tier 1"
        
        # Also Tier 1 if high confidence email + export details
        if has_email and email_confidence >= 0.7 and has_export:
            return "Tier 1"
        
        # Tier 2: Has contact info (email or phone) + some export info
        if (has_email or has_phone) and has_export:
            return "Tier 2"
        
        # Tier 2: Has verified email even without export details
        if has_verified_email or (has_email and email_confidence >= 0.5):
            return "Tier 2"
        
        # Tier 2: Has phone + email (even without export details)
        if has_email and has_phone:
            return "Tier 2"
        
        # Tier 3: Only website or name
        if has_website or has_name:
            return "Tier 3"
        
        return "Tier 3"
    
    def _prepare_tiered_row(self, profile: Dict) -> Dict:
        """Prepare a flat dictionary row from a company profile with tier info.
        
        Args:
            profile: Company profile dictionary with verification data
            
        Returns:
            Flat dictionary suitable for CSV writing
        """
        row = {}
        
        # Core fields
        row['tier'] = self._categorize_tier(profile)
        row['company_name'] = profile.get('company_name', '')
        row['website'] = profile.get('website', '')
        row['location'] = profile.get('location', '')
        row['export_region'] = profile.get('export_region', '')
        
        # Emails - join lists into semicolon-separated strings
        direct_emails = profile.get('direct_emails') or []
        row['direct_emails'] = '; '.join(direct_emails) if direct_emails else ''
        row['email_confidence_avg'] = profile.get('email_confidence_avg', '')
        row['has_verified_email'] = profile.get('has_verified_email', False)
        
        # Phone numbers
        phone_numbers = profile.get('phone_numbers') or []
        row['phone_numbers'] = '; '.join(phone_numbers) if phone_numbers else ''
        
        # Export details
        export_details = profile.get('export_details') or []
        row['export_details'] = '; '.join(export_details) if export_details else ''
        
        # Certifications
        certifications = profile.get('certifications') or []
        row['certifications'] = '; '.join(certifications) if certifications else ''
        
        # Key executives - flatten into string
        executives = profile.get('key_executives') or []
        exec_strings = []
        for exec_data in executives:
            if isinstance(exec_data, dict):
                name = exec_data.get('name', '')
                title = exec_data.get('title', '')
                if name and title:
                    exec_strings.append(f"{name} ({title})")
                elif name:
                    exec_strings.append(name)
            elif isinstance(exec_data, str):
                exec_strings.append(exec_data)
        row['key_executives'] = '; '.join(exec_strings) if exec_strings else ''
        
        # Email verification details (compact)
        verifications = profile.get('email_verifications') or []
        verify_strings = []
        for v in verifications:
            if isinstance(v, dict):
                email = v.get('email', '')
                score = v.get('confidence_score', 0)
                verify_strings.append(f"{email}:{score}")
        row['email_verification_details'] = '; '.join(verify_strings) if verify_strings else ''
        
        # Lead score & analyst fields
        row['lead_score'] = profile.get('_lead_score', '')
        row['product_match'] = profile.get('_product_match', '')
        row['eu_compliance'] = profile.get('_eu_compliance', '')
        row['company_type'] = profile.get('_company_type', '')
        row['reasoning'] = profile.get('_reasoning', '')
        
        # Trade legitimacy
        row['legitimacy_level'] = profile.get('_legitimacy_level', '')
        
        # Email draft (if outreach enabled)
        row['email_draft_subject'] = profile.get('_email_draft_subject', '')
        row['email_draft_body'] = profile.get('_email_draft_body', '').replace('\n', ' ')
        row['email_draft_recipient'] = profile.get('_email_draft_recipient', '')
        
        # Crawl metadata
        if profile.get('_backup_url'):
            row['backup_url'] = profile['_backup_url']
        if profile.get('_crawl_failure'):
            row['crawl_failure'] = profile['_crawl_failure']
        
        return row
    
    def write_detailed_csv(
        self,
        profiles: List[Dict],
        commodity: str = "",
        country: str = ""
    ) -> str:
        """Write tiered, categorized company profiles to a detailed CSV.
        
        Categorizes leads by readiness tier:
        - Tier 1: Verified email + specific export details (hot leads)
        - Tier 2: Has contact info + some export info (warm leads)
        - Tier 3: Only website/name (cold leads)
        
        Output filename format: {commodity}_{country}_detailed_{date}.csv
        
        Args:
            profiles: List of company profile dictionaries (with verification data)
            commodity: Commodity name for filename
            country: Country name for filename
            
        Returns:
            Full path to the saved file
        """
        if not profiles:
            print("No profiles to write")
            return ""
        
        # Prepare tiered rows
        rows = [self._prepare_tiered_row(p) for p in profiles]
        
        # Sort by tier (Tier 1 first)
        tier_order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2}
        rows.sort(key=lambda r: tier_order.get(r.get('tier', 'Tier 3'), 2))
        
        # Generate filename
        date_str = datetime.now().strftime("%Y%m%d")
        parts = []
        if commodity:
            parts.append(commodity.lower().replace(' ', '_'))
        if country:
            parts.append(country.lower().replace(' ', '_'))
        parts.append('detailed')
        parts.append(date_str)
        filename = '_'.join(parts) + '.csv'
        filepath = self.output_dir / filename
        
        # Define column order
        columns = [
            'tier', 'lead_score', 'legitimacy_level',
            'company_name', 'website', 'location',
            'direct_emails', 'email_confidence_avg', 'has_verified_email',
            'phone_numbers', 'export_details', 'export_region',
            'certifications', 'key_executives',
            'product_match', 'eu_compliance', 'company_type', 'reasoning',
            'email_draft_recipient', 'email_draft_subject', 'email_draft_body',
            'email_verification_details',
            'backup_url', 'crawl_failure',
        ]
        
        # Write CSV
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        
        # Print tier summary
        tier_counts = {}
        for row in rows:
            tier = row.get('tier', 'Tier 3')
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        
        print(f"Written {len(profiles)} leads to {filepath}")
        print(f"  Tier 1 (Hot):   {tier_counts.get('Tier 1', 0)} leads")
        print(f"  Tier 2 (Warm):  {tier_counts.get('Tier 2', 0)} leads")
        print(f"  Tier 3 (Cold):  {tier_counts.get('Tier 3', 0)} leads")
        
        return str(filepath)
    
    def write_pydantic_to_csv(
        self, 
        objects: List[BaseModel], 
        filename_prefix: str = "leads"
    ) -> str:
        """Write Pydantic objects to CSV with timestamp.
        
        Args:
            objects: List of Pydantic model instances
            filename_prefix: Prefix for the filename
            
        Returns:
            Full path to the saved file
        """
        if not objects:
            print("No objects to write")
            return ""
        
        # Convert Pydantic objects to dictionaries
        dicts = [obj.model_dump() for obj in objects]
        
        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{timestamp}.csv"
        filepath = self.output_dir / filename
        
        # Write to CSV
        self.write_to_csv(dicts, str(filepath))
        
        return str(filepath)
    
    def write_to_csv(self, contacts: List[Dict], filepath: str) -> None:
        """
        Write contact data to CSV file
        
        Args:
            contacts: List of contact dictionaries
            filepath: Output file path
        """
        if not contacts:
            print("No contacts to write")
            return
        
        # Flatten nested dictionaries if any
        flattened_contacts = [self._flatten_dict(contact) for contact in contacts]
        
        # Get all possible keys from all contacts
        fieldnames = set()
        for contact in flattened_contacts:
            fieldnames.update(contact.keys())
        
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=sorted(fieldnames))
            writer.writeheader()
            writer.writerows(flattened_contacts)
        
        print(f"Written {len(contacts)} contacts to {filepath}")
    
    def write_to_excel(self, contacts: List[Dict], filepath: str) -> None:
        """
        Write contact data to Excel file
        
        Args:
            contacts: List of contact dictionaries
            filepath: Output file path
        """
        if not contacts:
            print("No contacts to write")
            return
        
        # Flatten nested dictionaries
        flattened_contacts = [self._flatten_dict(contact) for contact in contacts]
        
        # Create DataFrame and write to Excel
        df = pd.DataFrame(flattened_contacts)
        df.to_excel(filepath, index=False, engine='openpyxl')
        
        print(f"Written {len(contacts)} contacts to {filepath}")
    
    def write_to_json(self, contacts: List[Dict], filepath: str) -> None:
        """
        Write contact data to JSON file
        
        Args:
            contacts: List of contact dictionaries
            filepath: Output file path
        """
        with open(filepath, 'w', encoding='utf-8') as jsonfile:
            json.dump(contacts, jsonfile, indent=2, ensure_ascii=False)
        
        print(f"Written {len(contacts)} contacts to {filepath}")
    
    def _flatten_dict(self, d: Dict, parent_key: str = '', sep: str = '_') -> Dict:
        """
        Flatten nested dictionary
        
        Args:
            d: Dictionary to flatten
            parent_key: Parent key for nested items
            sep: Separator for nested keys
            
        Returns:
            Flattened dictionary
        """
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                # Convert lists to semicolon-separated strings
                str_items = []
                for item in v:
                    if isinstance(item, dict):
                        str_items.append(json.dumps(item, ensure_ascii=False))
                    else:
                        str_items.append(str(item))
                items.append((new_key, '; '.join(str_items) if str_items else ''))
            else:
                items.append((new_key, v))
        return dict(items)
