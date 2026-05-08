"""
Mailer toolkit for drafting personalized B2B outreach emails.
Uses LLM to craft industry-specific, professional inquiry emails.
"""

import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class EmailDraft(BaseModel):
    """Drafted outreach email"""
    company_name: str = Field(description="Target company name")
    recipient_email: Optional[str] = Field(default=None, description="Recipient email address")
    subject: str = Field(default="", description="Email subject line")
    body: str = Field(default="", description="Email body text")
    lead_score: int = Field(default=0, description="Lead score that triggered this draft")


class MailerToolkit:
    """Drafts personalized B2B outreach emails using LLM.
    
    Creates industry-specific, professional inquiry emails that reference
    relevant compliance standards (CBAM for steel, GPSR for toys, etc.).
    Emails sound like a professional buyer, not a bot.
    
    Can save drafts to CSV or send via SMTP.
    """
    
    # Industry-specific compliance references for email personalization
    INDUSTRY_COMPLIANCE = {
        'steel': {
            'standards': 'CBAM (Carbon Border Adjustment Mechanism)',
            'keywords': ['steel', 'iron', 'metal', 'alloy', 'flat-rolled', 'cold-rolled', 'hot-rolled', 'galvanized', 'stainless'],
            'context': 'EU CBAM compliance is mandatory for steel imports starting 2026. Importers must report embedded emissions.',
        },
        'aluminum': {
            'standards': 'CBAM (Carbon Border Adjustment Mechanism)',
            'keywords': ['aluminum', 'aluminium', 'alloy'],
            'context': 'EU CBAM compliance applies to aluminum imports. Emission reporting required.',
        },
        'cement': {
            'standards': 'CBAM (Carbon Border Adjustment Mechanism)',
            'keywords': ['cement', 'clinker', 'concrete'],
            'context': 'EU CBAM covers cement and clinker imports.',
        },
        'fertilizer': {
            'standards': 'CBAM (Carbon Border Adjustment Mechanism) + REACH',
            'keywords': ['fertilizer', 'fertiliser', 'nitrogen', 'ammonia', 'NPK'],
            'context': 'EU CBAM and REACH registration apply to fertilizer imports.',
        },
        'textile': {
            'standards': 'REX (Registered Exporter System) + EU GSP',
            'keywords': ['textile', 'fabric', 'cotton', 'yarn', 'garment', 'apparel', 'silk', 'wool'],
            'context': 'REX registration enables preferential tariff rates under EU GSP for textile exports.',
        },
        'toy': {
            'standards': 'GPSR (General Product Safety Regulation) + CE marking',
            'keywords': ['toy', 'game', 'plush', 'doll', 'puzzle', 'plaything'],
            'context': 'EU GPSR and CE marking are mandatory for toy imports into the EU market.',
        },
        'electronics': {
            'standards': 'CE marking + RoHS + WEEE',
            'keywords': ['electronics', 'semiconductor', 'circuit', 'PCB', 'LED', 'sensor', 'IoT'],
            'context': 'CE marking, RoHS compliance, and WEEE registration required for EU electronics market.',
        },
        'food': {
            'standards': 'EU Food Safety + REX/GSP',
            'keywords': ['food', 'spice', 'tea', 'coffee', 'rice', 'grain', 'organic', 'processed'],
            'context': 'EU food safety regulations and REX registration for preferential tariffs apply.',
        },
        'chemical': {
            'standards': 'REACH (Registration, Evaluation, Authorisation and Restriction of Chemicals)',
            'keywords': ['chemical', 'pharmaceutical', 'intermediate', 'solvent', 'polymer', 'dye'],
            'context': 'EU REACH registration is mandatory for chemical substances imported into the EU.',
        },
        'wood': {
            'standards': 'EUTR (EU Timber Regulation) + FSC',
            'keywords': ['wood', 'timber', 'plywood', 'furniture', 'lumber', 'hardwood', 'softwood'],
            'context': 'EUTR compliance and FSC certification are key for EU wood product imports.',
        },
    }
    
    def __init__(self, model: str = "anthropic/claude-3.5-sonnet"):
        """Initialize the mailer toolkit.
        
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
    
    def _detect_industry(self, profile_dict: Dict) -> Optional[str]:
        """Detect the industry category from company profile data.
        
        Args:
            profile_dict: Company profile dictionary
            
        Returns:
            Industry key or None
        """
        # Combine all text fields for industry detection
        all_text = ' '.join([
            str(profile_dict.get('company_name', '')),
            str(profile_dict.get('export_region', '')),
            ' '.join(str(d) for d in (profile_dict.get('export_details') or [])),
            ' '.join(str(c) for c in (profile_dict.get('certifications') or [])),
        ]).lower()
        
        for industry, config in self.INDUSTRY_COMPLIANCE.items():
            for keyword in config['keywords']:
                if keyword in all_text:
                    return industry
        
        return None
    
    def draft_email(
        self,
        profile_dict: Dict,
        lead_score: int,
        reasoning: str = "",
        commodity: str = "",
        country: str = "",
        buyer_company: str = "Our Company",
        buyer_name: str = "Trade Sourcing Team",
    ) -> EmailDraft:
        """Draft a personalized first inquiry email for a company lead.
        
        Args:
            profile_dict: Company profile dictionary
            lead_score: Lead score from AnalystAgent
            reasoning: Reasoning from AnalystAgent
            commodity: The commodity being sourced
            country: The country being sourced from
            buyer_company: Name of the buyer's company (for signature)
            buyer_name: Name of the buyer contact (for signature)
            
        Returns:
            EmailDraft with subject, body, and recipient
        """
        company_name = profile_dict.get('company_name', 'Unknown')
        direct_emails = profile_dict.get('direct_emails') or []
        export_details = profile_dict.get('export_details') or []
        certifications = profile_dict.get('certifications') or []
        export_region = profile_dict.get('export_region') or ''
        location = profile_dict.get('location') or ''
        
        # Pick best email (prefer exports@ or sales@)
        recipient_email = None
        for prefix in ['exports', 'export', 'sales', 'marketing', 'info', 'contact']:
            for email in direct_emails:
                if email.lower().startswith(prefix):
                    recipient_email = email
                    break
            if recipient_email:
                break
        if not recipient_email and direct_emails:
            recipient_email = direct_emails[0]
        
        # Detect industry for compliance references
        industry = self._detect_industry(profile_dict)
        industry_config = self.INDUSTRY_COMPLIANCE.get(industry, {}) if industry else {}
        compliance_standards = industry_config.get('standards', 'EU import regulations')
        compliance_context = industry_config.get('context', '')
        
        prompt = f"""Draft a professional B2B first inquiry email for sourcing {commodity} from {country}.

TARGET COMPANY:
- Name: {company_name}
- Location: {location}
- Export Products: {', '.join(export_details) if export_details else 'Not specified'}
- Certifications: {', '.join(certifications) if certifications else 'None listed'}
- Export Markets: {export_region}
- Lead Score: {lead_score}/100
- Reasoning: {reasoning}

INDUSTRY CONTEXT:
- Relevant Standards: {compliance_standards}
- {compliance_context}

BUYER INFO:
- Company: {buyer_company}
- Contact: {buyer_name}

REQUIREMENTS:
1. Sound like a professional buyer, NOT a bot or mass email
2. Reference specific products they make (use their export_details)
3. Mention relevant compliance standards ({compliance_standards}) naturally - don't lecture
4. Ask about their manufacturing capabilities and export experience
5. Keep it concise (150-250 words)
6. Include a clear call-to-action (request a catalog, quote, or call)
7. Use a professional but warm tone
8. Subject line should be specific and compelling

Return ONLY a JSON object:
{{
  "subject": "<email subject>",
  "body": "<email body text>"
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a professional B2B trade correspondence writer. Draft concise, personalized inquiry emails that sound human and reference specific compliance standards naturally."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1024,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            return EmailDraft(
                company_name=company_name,
                recipient_email=recipient_email,
                subject=data.get('subject', f"Inquiry: {commodity} sourcing from {country}"),
                body=data.get('body', ''),
                lead_score=lead_score
            )
            
        except Exception as e:
            print(f"  [mailer] Error drafting email for {company_name}: {e}")
            return EmailDraft(
                company_name=company_name,
                recipient_email=recipient_email,
                subject=f"Inquiry: {commodity} sourcing from {country}",
                body=f"Draft generation failed: {e}",
                lead_score=lead_score
            )
    
    def draft_emails_for_leads(
        self,
        profiles: List[Dict],
        lead_scores: List[Dict],
        commodity: str,
        country: str,
        min_score: int = 80,
        buyer_company: str = "Our Company",
        buyer_name: str = "Trade Sourcing Team",
    ) -> List[EmailDraft]:
        """Draft emails for all leads above a minimum score.
        
        Args:
            profiles: List of company profile dictionaries
            lead_scores: List of lead score dictionaries (from LeadScore.model_dump())
            commodity: The commodity being sourced
            country: The country being sourced from
            min_score: Minimum lead score to draft email (default: 80)
            buyer_company: Name of the buyer's company
            buyer_name: Name of the buyer contact
            
        Returns:
            List of EmailDraft objects
        """
        # Build score lookup by company name
        score_lookup = {}
        for s in lead_scores:
            score_lookup[s.get('company_name', '')] = s
        
        drafts = []
        
        for profile in profiles:
            company_name = profile.get('company_name', '')
            score_data = score_lookup.get(company_name, {})
            score = score_data.get('score', 0)
            reasoning = score_data.get('reasoning', '')
            
            if score < min_score:
                continue
            
            print(f"  [mailer] Drafting email for {company_name} (score: {score})")
            
            draft = self.draft_email(
                profile_dict=profile,
                lead_score=score,
                reasoning=reasoning,
                commodity=commodity,
                country=country,
                buyer_company=buyer_company,
                buyer_name=buyer_name
            )
            drafts.append(draft)
        
        print(f"\n  [mailer] Drafted {len(drafts)} emails (min score: {min_score})")
        return drafts
    
    def send_email_smtp(
        self,
        draft: EmailDraft,
        smtp_host: str = None,
        smtp_port: int = 587,
        smtp_user: str = None,
        smtp_password: str = None,
        from_email: str = None,
    ) -> bool:
        """Send an email draft via SMTP.
        
        Args:
            draft: EmailDraft to send
            smtp_host: SMTP server hostname (falls back to SMTP_HOST env var)
            smtp_port: SMTP port (default: 587)
            smtp_user: SMTP username (falls back to SMTP_USER env var)
            smtp_password: SMTP password (falls back to SMTP_PASSWORD env var)
            from_email: Sender email (falls back to SMTP_FROM_EMAIL env var)
            
        Returns:
            True if sent successfully, False otherwise
        """
        smtp_host = smtp_host or os.getenv('SMTP_HOST')
        smtp_user = smtp_user or os.getenv('SMTP_USER')
        smtp_password = smtp_password or os.getenv('SMTP_PASSWORD')
        from_email = from_email or os.getenv('SMTP_FROM_EMAIL')
        
        if not all([smtp_host, smtp_user, smtp_password, from_email, draft.recipient_email]):
            print(f"  [mailer] Missing SMTP config or recipient for {draft.company_name}")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = from_email
            msg['To'] = draft.recipient_email
            msg['Subject'] = draft.subject
            msg.attach(MIMEText(draft.body, 'plain'))
            
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
            
            print(f"  [mailer] ✓ Sent email to {draft.recipient_email}")
            return True
            
        except Exception as e:
            print(f"  [mailer] ✗ Failed to send to {draft.recipient_email}: {e}")
            return False


# Example usage
if __name__ == '__main__':
    toolkit = MailerToolkit()
    
    test_profile = {
        'company_name': 'SteelCorp GmbH',
        'direct_emails': ['exports@steelcorp.de', 'info@steelcorp.de'],
        'export_details': ['Cold-rolled steel sheets', 'Hot-dip galvanized coils'],
        'certifications': ['ISO 9001:2015', 'CE', 'REX registered'],
        'export_region': 'EU, Middle East',
        'location': 'Hamburg, Germany',
    }
    
    draft = toolkit.draft_email(
        profile_dict=test_profile,
        lead_score=92,
        reasoning="Exact product match for cold-rolled steel. Fully EU compliant with CE and REX. Confirmed manufacturer.",
        commodity="cold-rolled steel sheets",
        country="Germany"
    )
    
    print(f"\nTo: {draft.recipient_email}")
    print(f"Subject: {draft.subject}")
    print(f"\n{draft.body}")
