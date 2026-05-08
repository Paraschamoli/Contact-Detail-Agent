import os
import re
from typing import List, Optional
import requests
from dotenv import load_dotenv

load_dotenv()


class TradeSearchToolkit:
    """Search toolkit for finding exporters and manufacturers.
    
    Integrates with search APIs (Tavily or Serper) to find business directories
    and corporate websites. Filters out social media links to focus on relevant
    business sources.
    """
    
    # Social media domains to filter out
    SOCIAL_MEDIA_DOMAINS = {
        'facebook.com', 'fb.com',
        'instagram.com', 'instagr.am',
        'twitter.com', 'x.com',
        'linkedin.com', 'tiktok.com',
        'youtube.com', 'pinterest.com',
        'snapchat.com', 'reddit.com'
    }
    
    # Patterns to identify personal/inappropriate LinkedIn profiles
    LINKEDIN_PERSONAL_PATTERN = re.compile(r'linkedin\.com/in/[^/]+/?$')
    
    def __init__(self, api_provider: str = 'tavily'):
        """Initialize the search toolkit.
        
        Args:
            api_provider: Either 'tavily' or 'serper'. Defaults to 'tavily'.
        """
        self.api_provider = api_provider.lower()
        
        if self.api_provider == 'tavily':
            self.api_key = os.getenv('TAVILY_API_KEY')
            self.api_url = 'https://api.tavily.com/search'
        elif self.api_provider == 'serper':
            self.api_key = os.getenv('SERPER_API_KEY')
            self.api_url = 'https://google.serper.dev/search'
        else:
            raise ValueError(f"Unsupported API provider: {api_provider}")
        
        if not self.api_key:
            raise ValueError(f"{api_provider.upper()}_API_KEY not found in environment variables")
    
    def _is_social_media_link(self, url: str) -> bool:
        """Check if URL is from a social media platform.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL is from social media, False otherwise
        """
        # Extract domain
        domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url.lower())
        if not domain_match:
            return False
        
        domain = domain_match.group(1)
        
        # Check against social media domains
        if any(social in domain for social in self.SOCIAL_MEDIA_DOMAINS):
            # Allow LinkedIn company pages but filter personal profiles
            if 'linkedin.com' in domain:
                if self.LINKEDIN_PERSONAL_PATTERN.search(url):
                    return True
                return False
            return True
        
        return False
    
    def _filter_urls(self, urls: List[str]) -> List[str]:
        """Filter out social media and irrelevant URLs.
        
        Args:
            urls: List of URLs to filter
            
        Returns:
            Filtered list of URLs
        """
        filtered = []
        for url in urls:
            if not self._is_social_media_link(url):
                filtered.append(url)
        return filtered
    
    def search_for_exporters(self, query: str, max_results: int = 10) -> List[str]:
        """Search for exporters and manufacturers.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            
        Returns:
            List of filtered URLs from search results
            
        Raises:
            ValueError: If API key is missing
            requests.exceptions.RequestException: If API request fails
            RuntimeError: If API limit is reached
        """
        try:
            if self.api_provider == 'tavily':
                return self._search_tavily(query, max_results)
            else:
                return self._search_serper(query, max_results)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                raise RuntimeError(f"API rate limit exceeded for {self.api_provider}") from e
            elif e.response.status_code == 401:
                raise RuntimeError(f"Invalid API key for {self.api_provider}") from e
            elif e.response.status_code == 402:
                raise RuntimeError(f"API quota exceeded for {self.api_provider}") from e
            else:
                raise
    
    def _search_tavily(self, query: str, max_results: int) -> List[str]:
        """Execute search using Tavily API.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            List of filtered URLs
        """
        headers = {
            'Content-Type': 'application/json',
        }
        
        payload = {
            'api_key': self.api_key,
            'query': query,
            'search_depth': 'basic',
            'max_results': max_results * 2,  # Get more results to account for filtering
            'include_answer': False,
            'include_raw_content': False,
        }
        
        response = requests.post(self.api_url, json=payload, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        urls = [result.get('url', '') for result in data.get('results', [])]
        
        return self._filter_urls(urls)[:max_results]
    
    def _search_serper(self, query: str, max_results: int) -> List[str]:
        """Execute search using Serper API.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            List of filtered URLs
        """
        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json',
        }
        
        payload = {
            'q': query,
            'num': max_results * 2,  # Get more results to account for filtering
        }
        
        response = requests.post(self.api_url, json=payload, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        urls = [result.get('link', '') for result in data.get('organic', [])]
        
        return self._filter_urls(urls)[:max_results]
    
    def get_tool_description(self) -> dict:
        """Get tool description for Agno agent integration.
        
        Returns:
            Dictionary with tool metadata
        """
        return {
            'name': 'search_for_exporters',
            'description': 'Search for exporters and manufacturers using web search API. '
                          'Filters out social media links to focus on corporate and directory websites.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'Search query for finding exporters/manufacturers'
                    },
                    'max_results': {
                        'type': 'integer',
                        'description': 'Maximum number of results to return (default: 10)',
                        'default': 10
                    }
                },
                'required': ['query']
            }
        }


# Example usage and testing
if __name__ == '__main__':
    try:
        toolkit = TradeSearchToolkit(api_provider='tavily')
        results = toolkit.search_for_exporters("textile exporters in India directory", max_results=5)
        print(f"Found {len(results)} relevant URLs:")
        for i, url in enumerate(results, 1):
            print(f"{i}. {url}")
    except Exception as e:
        print(f"Error: {e}")