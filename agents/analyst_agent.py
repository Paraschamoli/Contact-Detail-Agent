"""
Analyst Agent - Senior Trade Consultant
Reviews CompanyProfile and scores leads based on product match,
EU compliance, and manufacturer vs. middleman assessment.
"""

import os
import json
from typing import Optional, List
from pydantic import BaseModel, Field
from openai import OpenAI
import sys

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LeadScore(BaseModel):
    """Result of lead scoring analysis"""
    company_name: Optional[str] = Field(default="Unknown", description="Name of the company")
    score: int = Field(description="Overall lead score from 0-100")
    product_match: Optional[str] = Field(default=None, description="Product match assessment")
    eu_compliance: Optional[str] = Field(default=None, description="EU compliance assessment")
    company_type: Optional[str] = Field(default=None, description="Company type (manufacturer/middleman)")
    reasoning: str = Field(description="Detailed reasoning for the score")


class AnalystAgent:
    """Senior Trade Consultant agent that reviews and scores company leads.
    
    Evaluates three key dimensions:
    1. Product Match: Does the company produce exactly what the user wants?
    2. EU Compliance: Are they compliant with EU standards (CE/CBAM/REX)?
    3. Company Type: Manufacturer or middleman based on website text?
    
    Outputs a LeadScore (0-100) with reasoning for each company.
    """
    
    def __init__(self, model: str = "openai/gpt-oss-120b:nitro"):
        """Initialize the analyst agent.
        
        Args:
            model: Model identifier for OpenRouter. Defaults to Claude 3.5 Sonnet.
        """
        self.model = model
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
        
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )
    
    def score_lead(
        self,
        profile_dict: dict,
        commodity: str,
        country: str,
        legitimacy_level: Optional[str] = None,
    ) -> LeadScore:
        """Score a single company lead.
        
        Args:
            profile_dict: Company profile dictionary (from CompanyProfile.model_dump())
            commodity: The commodity the user is searching for
            country: The country the user is searching in
            legitimacy_level: Trade legitimacy level (Green/Yellow/Red) from TradeValidator
            
        Returns:
            LeadScore with score, reasoning, and assessment details
        """
        company_name = profile_dict.get('company_name', 'Unknown')
        
        prompt = self._build_scoring_prompt(profile_dict, commodity, country, legitimacy_level)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2048,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            # Ensure score is within bounds
            score = max(0, min(100, int(data.get('score', 0))))
            
            return LeadScore(
                company_name=company_name,
                score=score,
                product_match=data.get('product_match'),
                eu_compliance=data.get('eu_compliance'),
                company_type=data.get('company_type'),
                reasoning=data.get('reasoning', '')
            )
            
        except Exception as e:
            print(f"  [analyst] Error scoring {company_name}: {e}")
            return LeadScore(
                company_name=company_name or 'Unknown',
                score=0,
                reasoning=f"Scoring failed: {e}"
            )
    
    def score_all_leads(
        self,
        profiles: List[dict],
        commodity: str,
        country: str,
        legitimacy_levels: Optional[dict] = None,
    ) -> List[LeadScore]:
        """Score all company leads.
        
        Args:
            profiles: List of company profile dictionaries
            commodity: The commodity the user is searching for
            country: The country the user is searching in
            legitimacy_levels: Dict mapping company_name -> legitimacy_level
            
        Returns:
            List of LeadScore objects, sorted by score descending
        """
        legitimacy_levels = legitimacy_levels or {}
        
        print(f"\n{'='*60}")
        print(f"ANALYST AGENT - Scoring {len(profiles)} leads")
        print(f"Commodity: {commodity} | Country: {country}")
        print(f"{'='*60}")
        
        scores = []
        
        for i, profile in enumerate(profiles, 1):
            company_name = profile.get('company_name', 'Unknown')
            legit = legitimacy_levels.get(company_name)
            
            print(f"\n  [{i}/{len(profiles)}] Scoring: {company_name}")
            
            lead_score = self.score_lead(profile, commodity, country, legit)
            scores.append(lead_score)
            
            print(f"  [analyst] Score: {lead_score.score}/100")
            print(f"  [analyst] Product match: {lead_score.product_match}")
            print(f"  [analyst] EU compliance: {lead_score.eu_compliance}")
            print(f"  [analyst] Company type: {lead_score.company_type}")
        
        # Sort by score descending
        scores.sort(key=lambda s: s.score, reverse=True)
        
        # Summary
        high = sum(1 for s in scores if s.score >= 80)
        medium = sum(1 for s in scores if 50 <= s.score < 80)
        low = sum(1 for s in scores if s.score < 50)
        
        print(f"\n{'='*60}")
        print(f"SCORING COMPLETE")
        print(f"{'='*60}")
        print(f"  High (80+):  {high} leads")
        print(f"  Medium (50-79): {medium} leads")
        print(f"  Low (<50):   {low} leads")
        
        return scores
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the analyst agent."""
        return """You are a Senior Trade Consultant specializing in international B2B sourcing. Your task is to evaluate company leads and score them on a 0-100 scale.

You must assess THREE dimensions for each company:

1. PRODUCT MATCH (weight: 40%)
   - Does the company produce EXACTLY what the buyer is looking for?
   - "Steel" is vague → "Cold-rolled steel sheets" is specific
   - A company that makes "steel pipes" is NOT a match for "steel sheets"
   - Score: "Exact match", "Partial match", "Unlikely match", "No match"

2. EU COMPLIANCE (weight: 35%)
   - Does the company have certifications required for EU market access?
   - REX registration = critical for GSP preferential tariffs
   - CE marking = required for many products sold in EU
   - CBAM = critical for steel, aluminum, cement, fertilizers, electricity, hydrogen
   - ISO certifications = good signal but not sufficient alone
   - Score: "Fully compliant", "Partially compliant", "Non-compliant", "Unknown"

3. COMPANY TYPE (weight: 25%)
   - Based on their website text, is this a MANUFACTURER or a MIDDLEMAN/TRADER?
   - Manufacturers: mention factory, production capacity, machinery, R&D, raw materials
   - Traders: mention "sourcing", "supply chain", "network of suppliers", "wide range"
   - Manufacturers are far more valuable leads than traders
   - Score: "Manufacturer", "Likely manufacturer", "Trader/Middleman", "Unclear"

SCORING GUIDELINES:
- 90-100: Exact product match + EU compliant + confirmed manufacturer
- 80-89: Good product match + some compliance + likely manufacturer
- 60-79: Partial product match OR missing compliance + manufacturer
- 40-59: Vague product match + no compliance info + unclear company type
- 20-39: Unlikely product match + non-compliant + appears to be trader
- 0-19: No match or red flags

Return ONLY a JSON object with these fields:
{
  "score": <integer 0-100>,
  "product_match": "<Exact match|Partial match|Unlikely match|No match>",
  "eu_compliance": "<Fully compliant|Partially compliant|Non-compliant|Unknown>",
  "company_type": "<Manufacturer|Likely manufacturer|Trader/Middleman|Unclear>",
  "reasoning": "<2-3 sentence paragraph explaining the score>"
}"""
    
    def _build_scoring_prompt(
        self,
        profile: dict,
        commodity: str,
        country: str,
        legitimacy: Optional[str],
    ) -> str:
        """Build the scoring prompt.
        
        Args:
            profile: Company profile dictionary
            commodity: Target commodity
            country: Target country
            legitimacy: Trade legitimacy level
            
        Returns:
            Formatted prompt string
        """
        # Format profile data for the prompt
        company_name = profile.get('company_name') or 'Unknown'
        direct_emails = profile.get('direct_emails') or []
        phone_numbers = profile.get('phone_numbers') or []
        export_details = profile.get('export_details') or []
        certifications = profile.get('certifications') or []
        export_region = profile.get('export_region') or 'Unknown'
        location = profile.get('location') or 'Unknown'
        website = profile.get('website') or 'Unknown'
        
        prompt = f"""Evaluate this company as a potential lead for sourcing {commodity} from {country}.

BUYER'S REQUIREMENTS:
- Commodity: {commodity}
- Country: {country}

COMPANY PROFILE:
- Name: {company_name}
- Website: {website}
- Location: {location}
- Export Region: {export_region}
- Export Products: {', '.join(export_details) if export_details else 'Not specified'}
- Certifications: {', '.join(certifications) if certifications else 'None found'}
- Emails: {', '.join(direct_emails) if direct_emails else 'None found'}
- Phones: {', '.join(phone_numbers) if phone_numbers else 'None found'}
"""
        
        if legitimacy:
            prompt += f"\nTRADE LEGITIMACY: {legitimacy}\n"
        
        prompt += """
Score this lead on a 0-100 scale based on:
1. Product Match (40%): Do they produce exactly what the buyer needs?
2. EU Compliance (35%): Can they legally export to the EU?
3. Company Type (25%): Are they a manufacturer or middleman?

Return ONLY a JSON object with: score, product_match, eu_compliance, company_type, reasoning"""
        
        return prompt
    
    def get_agent_description(self) -> dict:
        """Get agent description for framework integration."""
        return {
            'name': 'AnalystAgent',
            'description': 'Senior Trade Consultant that reviews and scores company leads '
                          'based on product match, EU compliance, and manufacturer assessment.',
            'model': self.model,
            'output_schema': 'LeadScore'
        }


# Example usage
if __name__ == '__main__':
    agent = AnalystAgent()
    
    test_profile = {
        'company_name': 'SteelCorp GmbH',
        'website': 'https://steelcorp.de',
        'location': 'Hamburg, Germany',
        'export_details': ['Cold-rolled steel sheets', 'Hot-dip galvanized coils'],
        'certifications': ['ISO 9001:2015', 'CE', 'REX registered'],
        'direct_emails': ['exports@steelcorp.de'],
        'export_region': 'EU, Middle East, Asia',
    }
    
    score = agent.score_lead(test_profile, 'steel sheets', 'Germany', 'Green')
    print(f"\n{score.company_name}: {score.score}/100")
    print(f"Reasoning: {score.reasoning}")
