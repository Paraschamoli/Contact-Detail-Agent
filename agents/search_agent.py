import os
import yaml
from typing import List, Optional
from pydantic import BaseModel, Field
from openai import OpenAI
import sys
import json

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.search_toolkit import TradeSearchToolkit


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
    
    def __init__(self, model: str = "anthropic/claude-3.5-sonnet"):
        """Initialize the search agent.
        
        Args:
            model: Model identifier for OpenRouter. Defaults to Claude 3.5 Sonnet.
                   Options: "anthropic/claude-3.5-sonnet", "openai/gpt-4o", etc.
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
        num_queries: int = 8
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

Your task is to generate {num_queries} specific, high-quality search queries to find exporters and manufacturers.

INPUT:
- Commodity: {commodity}
- Country: {country}
- Industry: {industry or 'Not specified'}

BASE PATTERNS (from configuration):
{chr(10).join(f'- {pattern}' for pattern in base_patterns)}

REQUIREMENTS:
1. Generate {num_queries} unique search queries
2. Use the base patterns as inspiration, but make them more specific and varied
3. Substitute {{commodity}}, {{country}}, and {{industry}} placeholders with the actual values
4. Include different search strategies: directory searches, manufacturer lists, verified exporters, etc.
5. Make queries specific enough to return relevant business directories and corporate websites
6. Avoid overly generic queries that would return social media or irrelevant results

Return ONLY a JSON array of query strings, with no additional text or explanation.
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a search query generation specialist. Always return valid JSON arrays of strings."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            queries_data = json.loads(content)
            
            # Handle different response formats
            if isinstance(queries_data, list):
                queries = queries_data
            elif isinstance(queries_data, dict) and 'queries' in queries_data:
                queries = queries_data['queries']
            else:
                queries = list(queries_data.values()) if queries_data else []
            
            # Ensure we have the right number of queries
            queries = queries[:num_queries]
            
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
        queries_per_pattern: int = 5
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
        
        # Generate search queries
        queries = self.generate_search_queries(commodity, country, industry)
        
        if not queries:
            print("No queries generated. Using fallback.")
            queries = self._fallback_query_generation(commodity, country, industry, 5)
        
        all_urls = []
        seen_urls = set()
        
        # Execute searches for each query
        for i, query in enumerate(queries, 1):
            print(f"\n[{i}/{len(queries)}] Searching: {query}")
            
            try:
                urls = self.search_toolkit.search_for_exporters(
                    query, 
                    max_results=queries_per_pattern
                )
                
                for url in urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        # Extract company name from URL for the seed
                        company_name = self._extract_company_name_from_url(url)
                        all_urls.append(CompanySeed(company_name=company_name, url=url))
                
                print(f"  Found {len(urls)} URLs ({len([u for u in urls if u not in seen_urls])} new)")
                
            except Exception as e:
                print(f"  Error: {e}")
                continue
        
        print(f"\n=== Seed List Complete: {len(all_urls)} unique companies ===")
        return all_urls
    
    def _extract_company_name_from_url(self, url: str) -> str:
        """Extract a tentative company name from URL.
        
        Args:
            url: Company URL
            
        Returns:
            Extracted company name or placeholder
        """
        try:
            # Remove protocol and www
            clean_url = url.replace('https://', '').replace('http://', '').replace('www.', '')
            
            # Get domain (first part before slash)
            domain = clean_url.split('/')[0]
            
            # Remove TLD and common suffixes
            parts = domain.split('.')
            if len(parts) >= 2:
                name = parts[-2]  # Second-to-last part (e.g., "company" in company.com)
                # Capitalize and clean
                name = name.replace('-', ' ').replace('_', ' ')
                return name.title()
            
            return domain
            
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
        agent = SearchAgent(model="anthropic/claude-3.5-sonnet")
        
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