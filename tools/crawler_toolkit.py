import asyncio
import random
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.storages import Dataset


class CrawlerToolkit:
    """Web crawler toolkit using Crawlee's PlaywrightCrawler.
    
    Navigates to company websites, waits for network idle, and extracts
    raw HTML content from Contact and About Us pages with anti-detection features.
    """
    
    # Common user agents for rotation
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
    ]
    
    # Common contact page patterns
    CONTACT_PATTERNS = [
        'contact',
        'contact-us',
        'contactus',
        'contacts',
        'get-in-touch',
        'reach-us',
    ]
    
    # Common about page patterns
    ABOUT_PATTERNS = [
        'about',
        'about-us',
        'aboutus',
        'about-us/',
        'company',
        'our-story',
        'who-we-are',
    ]
    
    def __init__(self, headless: bool = True):
        """Initialize the crawler toolkit.
        
        Args:
            headless: Whether to run browser in headless mode. Defaults to True.
        """
        self.headless = headless
        self.crawler = None
        self.results: Dict[str, Dict[str, str]] = {}
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent from the list.
        
        Returns:
            Random user agent string
        """
        return random.choice(self.USER_AGENTS)
    
    def _get_common_headers(self) -> Dict[str, str]:
        """Get common HTTP headers for anti-detection.
        
        Returns:
            Dictionary of HTTP headers
        """
        return {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }
    
    def _find_contact_url(self, base_url: str, page_links: List[str]) -> Optional[str]:
        """Find contact page URL from list of links.
        
        Args:
            base_url: Base URL of the website
            page_links: List of absolute URLs found on the page
            
        Returns:
            Contact page URL or None
        """
        base_domain = urlparse(base_url).netloc.lower()
        
        for link in page_links:
            parsed = urlparse(link)
            if parsed.netloc.lower() == base_domain:
                path = parsed.path.lower()
                for pattern in self.CONTACT_PATTERNS:
                    if f'/{pattern}' in path or path.endswith(pattern):
                        return link
        
        return None
    
    def _find_about_url(self, base_url: str, page_links: List[str]) -> Optional[str]:
        """Find about page URL from list of links.
        
        Args:
            base_url: Base URL of the website
            page_links: List of absolute URLs found on the page
            
        Returns:
            About page URL or None
        """
        base_domain = urlparse(base_url).netloc.lower()
        
        for link in page_links:
            parsed = urlparse(link)
            if parsed.netloc.lower() == base_domain:
                path = parsed.path.lower()
                for pattern in self.ABOUT_PATTERNS:
                    if f'/{pattern}' in path or path.endswith(pattern):
                        return link
        
        return None
    
    async def crawl_urls(self, urls: List[str]) -> Dict[str, Dict[str, str]]:
        """Crawl multiple URLs and extract Contact and About Us page content.
        
        Args:
            urls: List of website URLs to crawl
            
        Returns:
            Dictionary indexed by URL with keys:
            - 'main': Main page content
            - 'contact': Contact page content (if found)
            - 'about': About page content (if found)
        """
        self.results = {}
        
        # Initialize PlaywrightCrawler
        self.crawler = PlaywrightCrawler(
            headless=self.headless,
            max_requests_per_crawl=len(urls) * 3,  # Account for sub-pages
            browser_pool_options={
                'use_fingerprints': True,  # Anti-detection
            }
        )
        
        # Define the request handler
        @self.crawler.router.default_handler
        async def request_handler(context: PlaywrightCrawlingContext) -> None:
            url = str(context.request.url)
            context.log.info(f'Processing {url} ...')
            
            # Set random user agent and headers
            user_agent = self._get_random_user_agent()
            headers = self._get_common_headers()
            
            await context.page.set_extra_http_headers(headers)
            await context.page.set_user_agent(user_agent)
            
            # Wait for network idle to handle JS-heavy sites
            try:
                await context.page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                # If network idle times out, continue anyway
                pass
            
            # Extract page content
            content = await context.page.content()
            
            # Determine page type based on URL
            parsed_url = urlparse(url)
            path_lower = parsed_url.path.lower()
            
            # Find base URL for this site
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            # Initialize result for base URL if not exists
            if base_url not in self.results:
                self.results[base_url] = {}
            
            # Categorize page
            is_contact = any(f'/{pattern}' in path_lower for pattern in self.CONTACT_PATTERNS)
            is_about = any(f'/{pattern}' in path_lower for pattern in self.ABOUT_PATTERNS)
            
            if is_contact:
                self.results[base_url]['contact'] = content
                context.log.info(f'  -> Extracted Contact page')
            elif is_about:
                self.results[base_url]['about'] = content
                context.log.info(f'  -> Extracted About page')
            else:
                # Assume it's the main page
                self.results[base_url]['main'] = content
                context.log.info(f'  -> Extracted Main page')
                
                # Extract links and enqueue Contact/About pages
                links = await context.enqueue_links()
                
                # Find and manually enqueue Contact and About pages if not found
                all_links = []
                for link in await links:
                    all_links.append(str(link))
                
                contact_url = self._find_contact_url(base_url, all_links)
                about_url = self._find_about_url(base_url, all_links)
                
                if contact_url and contact_url != url:
                    await context.add_requests([contact_url])
                    context.log.info(f'  -> Enqueued Contact page: {contact_url}')
                
                if about_url and about_url != url:
                    await context.add_requests([about_url])
                    context.log.info(f'  -> Enqueued About page: {about_url}')
        
        # Run the crawler
        await self.crawler.run(urls)
        
        return self.results
    
    async def crawl_single_url(self, url: str) -> Dict[str, str]:
        """Crawl a single URL and extract Contact and About Us page content.
        
        Args:
            url: Website URL to crawl
            
        Returns:
            Dictionary with keys:
            - 'main': Main page content
            - 'contact': Contact page content (if found)
            - 'about': About page content (if found)
        """
        results = await self.crawl_urls([url])
        return results.get(url, {})


# Example usage and testing
if __name__ == '__main__':
    async def main():
        toolkit = CrawlerToolkit(headless=True)
        
        # Example URLs
        urls = [
            'https://example.com',
        ]
        
        try:
            results = await toolkit.crawl_urls(urls)
            
            print(f"\n{'='*60}")
            print(f"CRAWLER RESULTS ({len(results)} sites)")
            print(f"{'='*60}")
            
            for base_url, content_dict in results.items():
                print(f"\nSite: {base_url}")
                print(f"  Main page: {'✓' if 'main' in content_dict else '✗'}")
                print(f"  Contact page: {'✓' if 'contact' in content_dict else '✗'}")
                print(f"  About page: {'✓' if 'about' in content_dict else '✗'}")
                
                if 'contact' in content_dict:
                    print(f"  Contact content length: {len(content_dict['contact'])} chars")
                if 'about' in content_dict:
                    print(f"  About content length: {len(content_dict['about'])} chars")
        
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(main())