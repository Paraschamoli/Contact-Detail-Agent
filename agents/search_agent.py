"""
Search Agent - Generates search queries and gathers company seed lists using Agno.
"""

import os
import json
import re
import time
import logging
import yaml
from typing import List, Optional
from pydantic import BaseModel, Field
from openai import OpenAI
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.search_toolkit import TradeSearchToolkit

logger = logging.getLogger(__name__)


class CompanySeed(BaseModel):
    """Pydantic model for company seed data"""
    company_name: str = Field(description="Name of the company")
    url: str = Field(description="URL of the company website or directory listing")


class SearchAgent:
    """Agent for generating search queries and gathering company seed lists.
    
    Uses high-reasoning models (GPT-4o or Claude 3.5) via OpenRouter to generate
    specific search queries based on patterns in config/settings.yaml, then uses
    TradeSearchToolkit to gather a seed list of potential company URLs.
    """
    
    def __init__(self, model: str = "openai/gpt-oss-120b:nitro"):
        """Initialize the search agent.
        
        Args:
            model: Model identifier for OpenRouter. Defaults to Claude 3.5 Sonnet.
                   Options: "openai/gpt-oss-120b:nitro", "openai/gpt-4o", etc.
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
        
        # Load settings configuration
        self.settings = self._load_settings()
        
        # Initialize search toolkit
        self.search_toolkit = TradeSearchToolkit(api_provider='tavily')
    
    def _load_settings(self) -> dict:
        """Load settings from config/settings.yaml
        
        Returns:
            Dictionary with settings configuration
        """
        settings_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config',
            'settings.yaml'
        )
        
        with open(settings_path, 'r') as f:
            return yaml.safe_load(f)
    
    def generate_search_queries(
        self, 
        commodity: str, 
        country: str, 
        industry: Optional[str] = None,
        num_queries: int = 25
    ) -> List[str]:
        """Generate specific search queries based on commodity and country.
        
        Uses the LLM to generate 5-10 specific search queries based on the patterns
        in config/settings.yaml, substituting the placeholders with actual values.
        
        Args:
            commodity: The commodity/product to search for (e.g., "textiles", "electronics")
            country: The country to search in (e.g., "India", "Germany")
            industry: Optional industry category (e.g., "textiles", "manufacturing")
            num_queries: Number of queries to generate (default: 8)
            
        Returns:
            List of generated search query strings
        """
        # Get base patterns from settings
        base_patterns = self.settings.get('global_search_queries', [])
        
        # Build the prompt for the LLM
        prompt = f"""You are a search query generation specialist for international trade research.

Your task is to generate {num_queries} DIVERSE search queries to find companies in {country} that export {commodity} to the European Union (EU).

INPUT:
- Commodity: {commodity}
- Country: {country}
- Industry: {industry or 'Not specified'}

BASE PATTERNS (from configuration):
{chr(10).join(f'- {pattern}' for pattern in base_patterns)}

CRITICAL REQUIREMENTS:
1. Generate exactly {num_queries} unique search queries
2. Use MULTIPLE search strategies to maximize coverage:
   a) EU-specific B2B directories: site:europages.com, site:kompass.com, site:alibaba.com, site:indiamart.com
   b) Government/export promotion sites: export promotion council, trade development authority
   c) Industry association directories: {industry} association {country} members
   d) EU compliance searches: REX registered, CE certified, EU GSP
   e) Specific EU country targets: "exports to Germany", "exports to France", "exports to Netherlands"
   f) Company listing pages: "top {commodity} exporters in {country}", "{commodity} manufacturers list"
   g) Trade show exhibitor lists: "{commodity} trade fair {country} exhibitors"
3. At least 40% of queries should mention "EU", "Europe", or specific EU countries
4. Use site: operator for at least 5 queries to target specific directories
5. Vary query structure - don't just repeat the same pattern
6. Avoid queries that return news articles, blogs, or government policy pages

Return ONLY a numbered list of search queries, one per line, with no additional text or explanation.
Example format:
1. site:europages.com textile exporters India
2. textile manufacturers India exporting to Germany France
3. REX registered textile exporters India list
4. site:indiamart.com textile exporters India EU
5. top 50 textile exporting companies India
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a search query generation specialist. Return search queries as a numbered list, one per line."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7
            )
            
            content = response.choices[0].message.content
            
            # Parse numbered list format
            queries = []
            for line in content.strip().split('\n'):
                line = line.strip()
                # Remove numbers/bullets at start
                if line and (line[0].isdigit() or line.startswith('-') or line.startswith('*')):
                    # Remove prefix
                    line = line.split('.', 1)[-1].split('-', 1)[-1].split('*', 1)[-1].strip()
                if line and len(line) > 5:  # Ignore very short lines
                    queries.append(line)
            
            # Ensure we have the right number of queries
            queries = queries[:num_queries]
            
            if queries:
                print(f"Generated {len(queries)} search queries")
                return queries
            
        except Exception as e:
            print(f"Error generating queries with LLM: {e}")
            # Fallback to basic pattern substitution
            return self._fallback_query_generation(commodity, country, industry, num_queries)
    
    def _fallback_query_generation(
        self, 
        commodity: str, 
        country: str, 
        industry: Optional[str],
        num_queries: int
    ) -> List[str]:
        """Fallback method: simple pattern substitution without LLM.
        
        Args:
            commodity: The commodity/product to search for
            country: The country to search in
            industry: Optional industry category
            num_queries: Number of queries to generate
            
        Returns:
            List of generated search query strings
        """
        base_patterns = self.settings.get('global_search_queries', [])
        queries = []
        
        for pattern in base_patterns:
            query = pattern.replace('{commodity}', commodity)
            query = query.replace('{country}', country)
            if industry:
                query = query.replace('{industry}', industry)
            queries.append(query)
            
            if len(queries) >= num_queries:
                break
        
        return queries[:num_queries]
    
    def gather_seed_list(
        self, 
        commodity: str,
        country: str,
        industry: Optional[str] = None,
        queries_per_pattern: int = 10
    ) -> List[CompanySeed]:
        """Gather a seed list of potential company URLs.
        
        Generates search queries and uses TradeSearchToolkit to find company URLs.
        
        Args:
            commodity: The commodity/product to search for
            country: The country to search in
            industry: Optional industry category
            queries_per_pattern: Number of results to fetch per query
            
        Returns:
            List of CompanySeed objects with company names and URLs
        """
        print(f"\n=== Gathering Seed List for {commodity} in {country} ===")
        
        # Generate LLM queries + fallback pattern queries for maximum coverage
        queries = self.generate_search_queries(commodity, country, industry, num_queries=25)
        
        # Always add fallback pattern queries too (they target specific directories)
        fallback_queries = self._fallback_query_generation(commodity, country, industry, 15)
        for fq in fallback_queries:
            if fq not in queries:
                queries.append(fq)
        
        if not queries:
            print("No queries generated at all!")
            return []
        
        all_urls = []
        seen_urls = set()
        seen_names = set()  # Dedup by normalized company name
        
        for i, query in enumerate(queries, 1):
            logger.info(f"[{i}/{len(queries)}] Searching: {query}")
            print(f"\n[{i}/{len(queries)}] Searching: {query}")
            
            try:
                urls = self.search_toolkit.search_for_exporters(
                    query, 
                    max_results=queries_per_pattern
                )
                
                new_count = 0
                for url in urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        company_name = self._extract_company_name_from_url(url)
                        # Normalize name for dedup
                        norm_name = re.sub(r'[^a-z0-9]', '', company_name.lower())
                        if norm_name and norm_name not in seen_names:
                            seen_names.add(norm_name)
                            all_urls.append(CompanySeed(company_name=company_name, url=url))
                            new_count += 1
                
                print(f"  Found {len(urls)} URLs ({new_count} new unique companies)")
                
                # Rate limit between queries
                if i < len(queries):
                    time.sleep(0.5)
                    
            except Exception as e:
                logger.error(f"Search error for query '{query}': {e}")
                print(f"  Error: {e}")
                continue
        
        print(f"\n=== Seed List Complete: {len(all_urls)} unique companies ===")
        return all_urls
    
    def _extract_company_name_from_url(self, url: str) -> str:
        """Extract a tentative company name from URL.
        
        Handles multi-part TLDs like .co.uk, .com.br correctly.
        """
        try:
            clean_url = url.replace('https://', '').replace('http://', '').replace('www.', '')
            domain = clean_url.split('/')[0]
            parts = domain.split('.')
            # Skip common multi-part TLDs
            multi_tlds = {'co.uk', 'com.br', 'com.au', 'co.in', 'com.sg', 'co.jp', 'com.mx', 'co.nz'}
            domain_suffix = '.'.join(parts[-2:])
            if domain_suffix in multi_tlds and len(parts) >= 3:
                name = parts[-3]
            elif len(parts) >= 2:
                name = parts[-2]
            else:
                return domain
            name = name.replace('-', ' ').replace('_', ' ')
            # Filter out generic names
            generic = {'index', 'home', 'main', 'default', 'www', 'site', 'web', 'page'}
            if name.lower() in generic:
                return domain.title()
            return name.title()
        except Exception:
            return "Unknown Company"
    
    def get_agent_description(self) -> dict:
        """Get agent description for framework integration.
        
        Returns:
            Dictionary with agent metadata
        """
        return {
            'name': 'SearchAgent',
            'description': 'Agent for generating search queries and gathering company seed lists. '
                          'Uses high-reasoning models to generate specific search queries based on '
                          'commodity and country, then uses search APIs to gather potential company URLs.',
            'model': self.model,
            'tools': ['TradeSearchToolkit'],
            'output_schema': 'CompanySeed'
        }


# Example usage and testing
if __name__ == '__main__':
    try:
        # Initialize agent with Claude 3.5 Sonnet
        agent = SearchAgent(model="openai/gpt-oss-120b:nitro")
        
        # Gather seed list for textile exporters in India
        seed_list = agent.gather_seed_list(
            commodity="textiles",
            country="India",
            industry="textiles",
            queries_per_pattern=3
        )
        
        print(f"\n{'='*60}")
        print(f"SEED LIST RESULTS ({len(seed_list)} companies)")
        print(f"{'='*60}")
        
        for i, seed in enumerate(seed_list, 1):
            print(f"\n{i}. {seed.company_name}")
            print(f"   URL: {seed.url}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()