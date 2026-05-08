"""
Email verification toolkit with syntax, domain, and mailbox checks.
Provides confidence scores to prevent high bounce rates.
"""

import os
import re
import socket
import dns.resolver
import requests
from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class EmailVerification(BaseModel):
    """Result of verifying a single email address"""
    email: str = Field(description="The email address verified")
    syntax_valid: bool = Field(description="Whether the email syntax is valid")
    domain_valid: bool = Field(default=False, description="Whether the domain has valid MX records")
    mailbox_valid: Optional[bool] = Field(default=None, description="Whether the mailbox exists (None if unchecked)")
    confidence_score: float = Field(default=0.0, description="Confidence score 0.0-1.0 that the email is deliverable")
    verification_method: str = Field(default="syntax", description="Method used: syntax, domain, smtp, hunter")
    notes: Optional[str] = Field(default=None, description="Additional notes about the verification")


class VerificationToolkit:
    """Email verification toolkit with syntax, domain, and mailbox checks.
    
    Performs three levels of verification:
    1. Syntax check: Validates email format
    2. Domain check: Verifies MX records exist for the domain
    3. Mailbox check: Verifies the mailbox exists (via Hunter.io API or SMTP)
    
    Returns a confidence score for each email to help prevent high bounce rates.
    """
    
    # Email syntax regex (RFC 5322 simplified)
    EMAIL_REGEX = re.compile(
        r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
        r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
    )
    
    # Common disposable email domains to flag
    DISPOSABLE_DOMAINS = {
        'mailinator.com', 'guerrillamail.com', 'sharklasers.com',
        'guerrillamailblock.com', 'grr.la', 'dispostable.com',
        'throwaway.email', 'tempmail.com', 'yopmail.com',
    }
    
    # Common typo domains to catch
    TYPO_DOMAINS = {
        'gmial.com': 'gmail.com',
        'gamil.com': 'gmail.com',
        'gmai.com': 'gmail.com',
        'gmail.co': 'gmail.com',
        'yahooo.com': 'yahoo.com',
        'yaho.com': 'yahoo.com',
        'hotmal.com': 'hotmail.com',
        'hotmai.com': 'hotmail.com',
        'outlok.com': 'outlook.com',
    }
    
    def __init__(self, hunter_api_key: Optional[str] = None):
        """Initialize the verification toolkit.
        
        Args:
            hunter_api_key: Optional Hunter.io API key for mailbox verification.
                           Falls back to HUNTER_API_KEY env variable.
        """
        self.hunter_api_key = hunter_api_key or os.getenv('HUNTER_API_KEY')
    
    def _check_syntax(self, email: str) -> Tuple[bool, Optional[str]]:
        """Check email syntax validity.
        
        Args:
            email: Email address to check
            
        Returns:
            Tuple of (is_valid, note)
        """
        if not email or not isinstance(email, str):
            return False, "Empty or invalid input"
        
        email = email.strip().lower()
        
        if not self.EMAIL_REGEX.match(email):
            return False, "Invalid email syntax"
        
        # Check for common typos
        domain = email.split('@')[1]
        if domain in self.TYPO_DOMAINS:
            return True, f"Possible typo: did you mean {self.TYPO_DOMAINS[domain]}?"
        
        # Check for disposable domains
        if domain in self.DISPOSABLE_DOMAINS:
            return True, "Disposable email domain detected"
        
        return True, None
    
    def _check_domain(self, email: str) -> Tuple[bool, Optional[str]]:
        """Check if the email domain has valid MX records.
        
        Args:
            email: Email address to check
            
        Returns:
            Tuple of (has_mx, note)
        """
        try:
            domain = email.split('@')[1]
            
            # Try MX records first
            try:
                mx_records = dns.resolver.resolve(domain, 'MX')
                if mx_records:
                    return True, f"{len(mx_records)} MX records found"
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                pass
            
            # Fallback to A record (some domains accept mail without MX)
            try:
                a_records = dns.resolver.resolve(domain, 'A')
                if a_records:
                    return True, "No MX records but A record exists"
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                pass
            
            return False, "No MX or A records found for domain"
            
        except Exception as e:
            return False, f"DNS lookup failed: {e}"
    
    def _check_mailbox_smtp(self, email: str) -> Tuple[Optional[bool], Optional[str]]:
        """Basic SMTP verification to check if mailbox exists.
        
        Connects to the MX server and issues RCPT TO without sending mail.
        Note: Many servers accept all RCPT TO commands (catch-all), so this
        is not 100% reliable.
        
        Args:
            email: Email address to check
            
        Returns:
            Tuple of (mailbox_exists, note). None if check could not be performed.
        """
        try:
            import smtplib
            
            domain = email.split('@')[1]
            
            # Get MX records
            try:
                mx_records = dns.resolver.resolve(domain, 'MX')
            except Exception:
                return None, "Could not resolve MX records for SMTP check"
            
            if not mx_records:
                return None, "No MX records found"
            
            # Try the highest priority MX server
            mx_server = str(mx_records[0].exchange).rstrip('.')
            
            # Connect and perform RCPT TO check
            with smtplib.SMTP(timeout=10) as smtp:
                smtp.connect(mx_server, 25)
                smtp.helo('verify.localhost')
                smtp.mail('verify@localhost')
                code, message = smtp.rcpt(email)
                
                if code == 250:
                    return True, "SMTP RCPT TO accepted"
                elif code == 550 or code == 551 or code == 553:
                    return False, f"Mailbox does not exist (SMTP {code})"
                else:
                    return None, f"SMTP returned code {code} (inconclusive)"
        
        except Exception as e:
            return None, f"SMTP check failed: {e}"
    
    def _check_mailbox_hunter(self, email: str) -> Tuple[Optional[bool], Optional[str]]:
        """Verify mailbox using Hunter.io API.
        
        Args:
            email: Email address to verify
            
        Returns:
            Tuple of (mailbox_exists, note). None if check could not be performed.
        """
        if not self.hunter_api_key:
            return None, "No Hunter.io API key configured"
        
        try:
            response = requests.get(
                'https://api.hunter.io/v2/email-verifier',
                params={
                    'email': email,
                    'api_key': self.hunter_api_key,
                },
                timeout=10
            )
            
            if response.status_code == 401:
                return None, "Hunter.io API key invalid"
            elif response.status_code == 429:
                return None, "Hunter.io rate limit exceeded"
            elif response.status_code != 200:
                return None, f"Hunter.io returned status {response.status_code}"
            
            data = response.json().get('data', {})
            result = data.get('result')
            
            # Hunter.io result values: deliverable, undeliverable, risky, unknown
            if result == 'deliverable':
                return True, "Hunter.io: deliverable"
            elif result == 'undeliverable':
                return False, "Hunter.io: undeliverable"
            elif result == 'risky':
                return None, "Hunter.io: risky (may bounce)"
            else:
                return None, f"Hunter.io: {result or 'unknown'}"
            
        except Exception as e:
            return None, f"Hunter.io check failed: {e}"
    
    def verify_email(self, email: str, check_level: str = 'domain') -> EmailVerification:
        """Verify a single email address.
        
        Args:
            email: Email address to verify
            check_level: Level of verification to perform:
                - 'syntax': Only check email format
                - 'domain': Check syntax + MX records (default)
                - 'smtp': Check syntax + MX + SMTP RCPT TO
                - 'hunter': Check syntax + MX + Hunter.io API
                
        Returns:
            EmailVerification object with results and confidence score
        """
        result = EmailVerification(
            email=email.strip().lower(),
            syntax_valid=False,
            domain_valid=False,
            confidence_score=0.0,
            verification_method=check_level
        )
        
        # Step 1: Syntax check
        syntax_ok, syntax_note = self._check_syntax(email)
        result.syntax_valid = syntax_ok
        result.notes = syntax_note
        
        if not syntax_ok:
            result.confidence_score = 0.0
            return result
        
        # Step 2: Domain check
        if check_level in ('domain', 'smtp', 'hunter'):
            domain_ok, domain_note = self._check_domain(email)
            result.domain_valid = domain_ok
            if domain_note:
                result.notes = f"{result.notes}; {domain_note}" if result.notes else domain_note
            
            if not domain_ok:
                result.confidence_score = 0.1  # Syntax valid but domain invalid
                return result
        
        # Step 3: Mailbox check
        if check_level == 'smtp':
            mailbox_ok, smtp_note = self._check_mailbox_smtp(email)
            result.mailbox_valid = mailbox_ok
            if smtp_note:
                result.notes = f"{result.notes}; {smtp_note}" if result.notes else smtp_note
            result.verification_method = 'smtp'
            
        elif check_level == 'hunter':
            mailbox_ok, hunter_note = self._check_mailbox_hunter(email)
            result.mailbox_valid = mailbox_ok
            if hunter_note:
                result.notes = f"{result.notes}; {hunter_note}" if result.notes else hunter_note
            result.verification_method = 'hunter'
        
        # Calculate confidence score
        result.confidence_score = self._calculate_confidence(result)
        
        return result
    
    def _calculate_confidence(self, verification: EmailVerification) -> float:
        """Calculate confidence score based on verification results.
        
        Scoring logic:
        - Syntax valid: +0.2
        - Domain has MX records: +0.3
        - Mailbox verified (SMTP or Hunter): +0.4
        - Disposable domain: -0.2
        - Typo detected: -0.1
        
        Args:
            verification: EmailVerification object with check results
            
        Returns:
            Confidence score between 0.0 and 1.0
        """
        score = 0.0
        
        if verification.syntax_valid:
            score += 0.2
        
        if verification.domain_valid:
            score += 0.3
        
        if verification.mailbox_valid is True:
            score += 0.4
        elif verification.mailbox_valid is None:
            # Inconclusive mailbox check
            score += 0.1
        
        # Penalties
        if verification.notes:
            notes_lower = verification.notes.lower()
            if 'disposable' in notes_lower:
                score -= 0.2
            if 'typo' in notes_lower:
                score -= 0.1
            if 'risky' in notes_lower:
                score -= 0.15
        
        return max(0.0, min(1.0, round(score, 2)))
    
    def verify_emails(
        self, 
        emails: List[str], 
        check_level: str = 'domain'
    ) -> List[EmailVerification]:
        """Verify a list of email addresses.
        
        Args:
            emails: List of email addresses to verify
            check_level: Verification level ('syntax', 'domain', 'smtp', 'hunter')
            
        Returns:
            List of EmailVerification objects
        """
        results = []
        
        for i, email in enumerate(emails, 1):
            print(f"  [verify] {i}/{len(emails)}: {email}")
            result = self.verify_email(email, check_level)
            results.append(result)
            print(f"  [verify]   Score: {result.confidence_score} ({result.verification_method})")
        
        # Summary
        avg_confidence = sum(r.confidence_score for r in results) / len(results) if results else 0
        high_confidence = sum(1 for r in results if r.confidence_score >= 0.7)
        
        print(f"\n  [verify] Summary: {len(results)} emails checked")
        print(f"  [verify] Average confidence: {avg_confidence:.2f}")
        print(f"  [verify] High confidence (>=0.7): {high_confidence}/{len(results)}")
        
        return results
    
    def verify_company_profile(self, profile_dict: Dict) -> Dict:
        """Verify emails from a company profile dictionary.
        
        Takes a CompanyProfile.model_dump() dict, verifies the direct_emails,
        and adds verification results and an overall confidence score.
        
        Args:
            profile_dict: Company profile as a dictionary (from CompanyProfile.model_dump())
            
        Returns:
            Updated dictionary with verification results added
        """
        emails = profile_dict.get('direct_emails') or []
        
        if not emails:
            profile_dict['email_verifications'] = []
            profile_dict['email_confidence_avg'] = 0.0
            profile_dict['has_verified_email'] = False
            return profile_dict
        
        verifications = self.verify_emails(emails, check_level='domain')
        
        # Add verification results
        profile_dict['email_verifications'] = [
            {
                'email': v.email,
                'confidence_score': v.confidence_score,
                'syntax_valid': v.syntax_valid,
                'domain_valid': v.domain_valid,
                'mailbox_valid': v.mailbox_valid,
                'method': v.verification_method,
                'notes': v.notes,
            }
            for v in verifications
        ]
        
        # Calculate average confidence
        avg_confidence = sum(v.confidence_score for v in verifications) / len(verifications)
        profile_dict['email_confidence_avg'] = round(avg_confidence, 2)
        
        # Flag if any email has high confidence
        profile_dict['has_verified_email'] = any(
            v.confidence_score >= 0.7 for v in verifications
        )
        
        return profile_dict


# Example usage and testing
if __name__ == '__main__':
    toolkit = VerificationToolkit()
    
    test_emails = [
        'sales@arvindlimited.com',
        'exports@google.com',
        'invalid-email',
        'test@nonexistentdomain12345.com',
        'info@gmail.com',
    ]
    
    results = toolkit.verify_emails(test_emails, check_level='domain')
    
    print(f"\n{'='*60}")
    print(f"VERIFICATION RESULTS")
    print(f"{'='*60}")
    
    for r in results:
        print(f"\n{r.email}:")
        print(f"  Syntax: {r.syntax_valid}")
        print(f"  Domain: {r.domain_valid}")
        print(f"  Mailbox: {r.mailbox_valid}")
        print(f"  Confidence: {r.confidence_score}")
        print(f"  Method: {r.verification_method}")
        if r.notes:
            print(f"  Notes: {r.notes}")
