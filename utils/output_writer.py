"""
CSV/Excel formatting logic with timestamp support
"""

import csv
import json
from typing import List, Dict, Union
from datetime import datetime
from pathlib import Path
import pandas as pd
from pydantic import BaseModel


class OutputWriter:
    """Handles writing contact data to various formats (CSV, Excel) with timestamps"""
    
    def __init__(self, output_dir: str = "output"):
        """Initialize the output writer.
        
        Args:
            output_dir: Directory to save output files. Defaults to "output".
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
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
            else:
                items.append((new_key, v))
        return dict(items)
