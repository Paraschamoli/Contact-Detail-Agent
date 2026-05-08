"""
Scraper Agent - Site Investigator
Takes CompanySeed objects and performs deep crawls.
Falls back to backup URLs (LinkedIn, trade directories) if primary site fails.
"""

import os
import asyncio
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field
from openai import OpenAI
import sys

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.search_agent import CompanySeed
from tools.crawler_toolkit import CrawlerToolkit
from tools.search_toolkit import TradeSearchToolkit


class CrawlStatus(str, Enum):
    """Status of a company crawl attempt"""
    SUCCESS = "success"
    BACKUP_SUCCESS = "backup_success"
    FAILED = "failed"


class ScrapedCompany(BaseModel):
    """Result of scraping a single company"""
    company_name: str = Field(description="Name of the company")
    original_url: str = Field(description="Original URL from seed list")
    backup_url: Optional[str] = Field(default=None, description="Backup URL used if primary failed (LinkedIn, directory, etc.)")
    status: CrawlStatus = Field(description="Crawl status: success, backup_success, or failed")
    failure_reason: Optional[str] = Field(default=None, description="Reason for failure if status is 'failed'")
    crawled_text: Optional[str] = Field(default=None, description="Combined text blob from crawled pages for LLM analysis")


class ScraperAgent:
    """Site Investigator agent that deep-crawls company websites.
    
    Takes CompanySeed objects from the Search Agent and uses CrawlerToolkit
    to perform deep dives. If a website is down or blocks the crawler, it
    attempts to find a backup URL (LinkedIn page, trade directory profile)
    using TradeSearchToolkit. Ensures every company gets either a detailed
    crawl or a specific failure reason.
    """
    
    # Failure reason categories
    FAILURE_SITE_DOWN = "site_down"
    FAILURE_BLOCKED = "blocked_by_site"
    FAILURE_TIMEOUT = "timeout"
    FAILURE_NO_CONTENT = "no_meaningful_content"
    FAILURE_BACKUP_FAILED = "backup_url_not_found"
    FAILURE_UNKNOWN = "unknown_error"
    
    def __init__(self, model: str = "anthropic/claude-3.5-sonnet-20241022"):
        """Initialize the scraper agent.
        
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
        
        # Initialize toolkits
        self.crawler = CrawlerToolkit(headless=True)
        self.search_toolkit = TradeSearchToolkit(api_provider='tavily')
    
    def _classify_error(self, error: Exception) -> str:
        """Classify an error into a failure reason category.
        
        Args:
            error: The exception that occurred
            
        Returns:
            Failure reason string
        """
        error_msg = str(error).lower()
        
        if 'timeout' in error_msg or 'timed out' in error_msg:
            return self.FAILURE_TIMEOUT
        elif 'net::err_connection_refused' in error_msg or 'err_name_not_resolved' in error_msg:
            return self.FAILURE_SITE_DOWN
        elif '403' in error_msg or 'blocked' in error_msg or 'captcha' in error_msg or 'access denied' in error_msg:
            return self.FAILURE_BLOCKED
        elif 'navigation' in error_msg and 'error' in error_msg:
            return self.FAILURE_SITE_DOWN
        else:
            return self.FAILURE_UNKNOWN
    
    def _find_backup_url(self, company_name: str, original_url: str) -> Optional[str]:
        """Find a backup URL for a company using search.
        
        Searches for LinkedIn company page or trade directory profile
        when the primary website is inaccessible.
        
        Args:
            company_name: Name of the company
            original_url: Original URL that failed
            
        Returns:
            Backup URL or None if not found
        """
        backup_queries = [
            f'{company_name} LinkedIn company page',
            f'{company_name} trade directory profile',
            f'{company_name} exporter directory listing',
            f'site:linkedin.com/company "{company_name}"',
        ]
        
        for query in backup_queries:
            try:
                urls = self.search_toolkit.search_for_exporters(query, max_results=3)
                
                for url in urls:
                    # Prefer LinkedIn company pages
                    if 'linkedin.com/company' in url.lower():
                        return url
                    # Accept trade directory listings
                    if any(domain in url.lower() for domain in [
                        'indiamart.com', 'tradeindia.com', 'exportersindia.com',
                        'alibaba.com', 'kompass.com', 'europages.com',
                        'thomasnet.com', 'houzz.com', 'g2.com', 'crunchbase.com'
                    ]):
                        return url
                
                # If no preferred backup found, return first result that isn't the original
                for url in urls:
                    if url != original_url:
                        return url
                        
            except Exception as e:
                print(f"  [backup] Search failed for query '{query}': {e}")
                continue
        
        return None
    
    async def investigate_company(self, seed: CompanySeed) -> ScrapedCompany:
        """Investigate a single company by deep-crawling its website.
        
        If the primary URL fails, attempts to find and crawl a backup URL.
        
        Args:
            seed: CompanySeed object with company name and URL
            
        Returns:
            ScrapedCompany with crawl results or failure details
        """
        print(f"\n  [investigate] Starting: {seed.company_name} ({seed.url})")
        
        # ── Attempt 1: Deep crawl primary URL ──
        try:
            crawled_text = await self.crawler.deep_crawl_company(
                base_url=seed.url,
                max_sub_pages=3
            )
            
            # Check if we got meaningful content
            if crawled_text and len(crawled_text.strip()) > 100:
                print(f"  [investigate] ✓ Primary crawl successful ({len(crawled_text)} chars)")
                return ScrapedCompany(
                    company_name=seed.company_name,
                    original_url=seed.url,
                    status=CrawlStatus.SUCCESS,
                    crawled_text=crawled_text
                )
            else:
                raise ValueError("Crawled content too short or empty")
        
        except Exception as primary_error:
            failure_reason = self._classify_error(primary_error)
            print(f"  [investigate] ✗ Primary crawl failed: {failure_reason} ({primary_error})")
            
            # ── Attempt 2: Find and crawl backup URL ──
            print(f"  [investigate] Searching for backup URL...")
            backup_url = self._find_backup_url(seed.company_name, seed.url)
            
            if not backup_url:
                print(f"  [investigate] ✗ No backup URL found")
                return ScrapedCompany(
                    company_name=seed.company_name,
                    original_url=seed.url,
                    status=CrawlStatus.FAILED,
                    failure_reason=f"{failure_reason}; {self.FAILURE_BACKUP_FAILED}"
                )
            
            print(f"  [investigate] Found backup URL: {backup_url}")
            
            # Try crawling the backup URL
            try:
                # For LinkedIn/directory pages, use fewer sub-pages
                max_sub = 1 if 'linkedin.com' in backup_url.lower() else 2
                backup_text = await self.crawler.deep_crawl_company(
                    base_url=backup_url,
                    max_sub_pages=max_sub
                )
                
                if backup_text and len(backup_text.strip()) > 50:
                    print(f"  [investigate] ✓ Backup crawl successful ({len(backup_text)} chars)")
                    return ScrapedCompany(
                        company_name=seed.company_name,
                        original_url=seed.url,
                        backup_url=backup_url,
                        status=CrawlStatus.BACKUP_SUCCESS,
                        crawled_text=backup_text
                    )
                else:
                    raise ValueError("Backup crawled content too short or empty")
            
            except Exception as backup_error:
                backup_failure = self._classify_error(backup_error)
                print(f"  [investigate] ✗ Backup crawl also failed: {backup_failure}")
                return ScrapedCompany(
                    company_name=seed.company_name,
                    original_url=seed.url,
                    backup_url=backup_url,
                    status=CrawlStatus.FAILED,
                    failure_reason=f"{failure_reason}; backup_at_{backup_url}_also_failed: {backup_failure}"
                )
    
    async def investigate_all(self, seeds: List[CompanySeed]) -> List[ScrapedCompany]:
        """Investigate all companies from the seed list.
        
        Ensures every company from Stage 1 either gets a detailed crawl
        or a specific failure reason.
        
        Args:
            seeds: List of CompanySeed objects from the Search Agent
            
        Returns:
            List of ScrapedCompany objects with crawl results
        """
        print(f"\n{'='*60}")
        print(f"SCRAPER AGENT - Investigating {len(seeds)} companies")
        print(f"{'='*60}")
        
        results = []
        success_count = 0
        backup_count = 0
        failed_count = 0
        
        for i, seed in enumerate(seeds, 1):
            print(f"\n[{i}/{len(seeds)}] Investigating: {seed.company_name}")
            
            result = await self.investigate_company(seed)
            results.append(result)
            
            # Track stats
            if result.status == CrawlStatus.SUCCESS:
                success_count += 1
            elif result.status == CrawlStatus.BACKUP_SUCCESS:
                backup_count += 1
            else:
                failed_count += 1
        
        # Summary
        print(f"\n{'='*60}")
        print(f"INVESTIGATION COMPLETE")
        print(f"{'='*60}")
        print(f"  Primary crawl success: {success_count}")
        print(f"  Backup crawl success:  {backup_count}")
        print(f"  Failed:                {failed_count}")
        print(f"  Total:                 {len(results)}")
        
        # Log failure details
        if failed_count > 0:
            print(f"\nFailure Details:")
            for r in results:
                if r.status == CrawlStatus.FAILED:
                    print(f"  - {r.company_name}: {r.failure_reason}")
        
        return results
    
    def get_agent_description(self) -> dict:
        """Get agent description for framework integration.
        
        Returns:
            Dictionary with agent metadata
        """
        return {
            'name': 'ScraperAgent',
            'description': 'Site Investigator agent that deep-crawls company websites. '
                          'Falls back to backup URLs (LinkedIn, trade directories) when '
                          'primary sites are down or blocked. Ensures every company gets '
                          'either a detailed crawl or a specific failure reason.',
            'model': self.model,
            'tools': ['CrawlerToolkit', 'TradeSearchToolkit'],
            'output_schema': 'ScrapedCompany'
        }


# Example usage and testing
if __name__ == '__main__':
    async def main():
        try:
            agent = ScraperAgent(model="anthropic/claude-3.5-sonnet-20241022")
            
            # Test with sample seeds
            seeds = [
                CompanySeed(company_name="Arvind Limited", url="https://www.arvindlimited.com"),
                CompanySeed(company_name="Welspun Global", url="https://welspinglobal.com"),
            ]
            
            results = await agent.investigate_all(seeds)
            
            print(f"\n{'='*60}")
            print(f"RESULTS ({len(results)} companies)")
            print(f"{'='*60}")
            
            for r in results:
                print(f"\n{r.company_name}:")
                print(f"  Status: {r.status.value}")
                print(f"  Original URL: {r.original_url}")
                if r.backup_url:
                    print(f"  Backup URL: {r.backup_url}")
                if r.failure_reason:
                    print(f"  Failure: {r.failure_reason}")
                if r.crawled_text:
                    print(f"  Content: {len(r.crawled_text)} chars")
        
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(main())