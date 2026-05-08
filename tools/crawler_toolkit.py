import asyncio
import random
import re
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.storages import Dataset
from playwright.async_api import async_playwright, Page, BrowserContext


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
    
    # Keywords for deep crawl link discovery (with relevance weights)
    DEEP_CRAWL_KEYWORDS = {
        'contact': 10,
        'contact-us': 10,
        'about': 8,
        'about-us': 8,
        'team': 7,
        'our-team': 7,
        'management': 6,
        'leadership': 6,
        'global-presence': 9,
        'global': 9,
        'presence': 5,
        'offices': 6,
        'locations': 5,
        'reach-us': 8,
        'get-in-touch': 7,
        'company': 5,
        'our-story': 6,
        'who-we-are': 6,
        'exports': 4,
        'markets': 4,
        'international': 4,
        'worldwide': 4,
    }
    
    # CSS selectors to wait for on different page types
    WAIT_SELECTORS = [
        'a[href*="contact"]',
        'a[href*="about"]',
        '.contact-form',
        '#contact-form',
        '.contact-details',
        '.email',
        'a[href^="mailto:"]',
        '.address',
        '.phone',
        '.team-member',
        '.staff',
        '.office-location',
        'table',
        '.content',
        'main',
        'article',
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
            browser_type_args={
                'user_agent': self._get_random_user_agent()
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
            # Note: User agent is set at browser context level in newer Playwright versions
            
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
                
                # Extract links from page using evaluate (enqueue_links returns RequestQueue, not list)
                all_links = await context.page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]')).map(a => a.href);
                }""")
                all_links = [str(link) for link in all_links]
                
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
    
    def _score_link_relevance(self, url: str, link_text: str) -> int:
        """Score a link's relevance based on URL path and link text.
        
        Args:
            url: The link URL
            link_text: The visible text of the link
            
        Returns:
            Relevance score (higher = more relevant)
        """
        score = 0
        url_lower = url.lower()
        text_lower = link_text.lower().strip()
        
        # Score based on URL path keywords
        for keyword, weight in self.DEEP_CRAWL_KEYWORDS.items():
            if keyword in url_lower:
                score += weight
            if keyword in text_lower:
                score += weight // 2
        
        # Bonus for exact keyword match in link text
        for keyword in ['contact', 'about', 'team', 'global presence']:
            if text_lower == keyword:
                score += 5
        
        return score
    
    def _extract_text_from_html(self, html: str) -> str:
        """Extract readable text content from HTML, stripping tags and scripts.
        
        Args:
            html: Raw HTML content
            
        Returns:
            Cleaned text content
        """
        # Remove script and style tags with content
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML comments
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        # Remove all HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Decode common HTML entities
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&nbsp;', ' ').replace('&#64;', '@').replace('&#46;', '.')
        
        return text
    
    async def _wait_for_content(self, page: Page) -> None:
        """Wait for dynamically loaded content to appear on the page.
        
        Uses a 'Wait for Selector' strategy - tries multiple selectors and waits
        for the first one to appear, ensuring dynamic content (contact forms,
        email popups, etc.) is fully rendered.
        
        Args:
            page: Playwright page object
        """
        # First wait for network idle
        try:
            await page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            pass
        
        # Then wait for any of the content selectors to appear
        for selector in self.WAIT_SELECTORS:
            try:
                await page.wait_for_selector(selector, timeout=3000)
                break  # Found a selector, content is loaded
            except Exception:
                continue
        
        # Extra wait for any JS-rendered content to settle
        await asyncio.sleep(0.5)
    
    
    async def _collect_links_from_page(self, page: Page, base_url: str) -> List[Tuple[str, str, int]]:
        """Collect and score all links on a page for relevance.
        
        Args:
            page: Playwright page object
            base_url: Base URL to filter same-domain links
            
        Returns:
            List of (url, link_text, relevance_score) tuples, sorted by score descending
        """
        base_domain = urlparse(base_url).netloc.lower()
        scored_links = []
        seen_urls = set()
        
        # Extract all anchor elements with href
        links = await page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a[href]'));
            return links.map(link => ({
                href: link.href,
                text: link.textContent || link.innerText || ''
            }));
        }""")
        
        for link in links:
            href = link.get('href', '')
            text = link.get('text', '')
            
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            
            # Only follow same-domain links
            parsed = urlparse(href)
            if parsed.netloc.lower() != base_domain:
                continue
            
            # Skip the base URL itself
            if href.rstrip('/') == base_url.rstrip('/'):
                continue
            
            # Skip PDFs, images, and other non-HTML resources
            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in ['.pdf', '.jpg', '.png', '.gif', '.svg', '.zip', '.doc', '.xls']):
                continue
            
            if href not in seen_urls:
                seen_urls.add(href)
                score = self._score_link_relevance(href, text)
                if score > 0:
                    scored_links.append((href, text, score))
        
        # Sort by relevance score descending
        scored_links.sort(key=lambda x: x[2], reverse=True)
        return scored_links
    
    async def deep_crawl_company(self, base_url: str, max_sub_pages: int = 3) -> str:
        """Deep crawl a company website with intelligent link discovery.
        
        Visits the base_url, automatically finds and clicks links containing
        keywords like 'Contact', 'About', 'Team', 'Global Presence'. Uses a
        'Wait for Selector' strategy to ensure dynamically loaded content is
        fully rendered. Returns a combined text blob of the homepage and the
        top most relevant sub-pages.
        
        Args:
            base_url: The company website URL to crawl
            max_sub_pages: Maximum number of sub-pages to visit (default: 3)
            
        Returns:
            Combined text blob of homepage + top sub-pages for LLM analysis
        """
        combined_text_parts = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=['--disable-blink-features=AutomationControlled']
            )
            
            # Create context with anti-detection settings
            context = await browser.new_context(
                user_agent=self._get_random_user_agent(),
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
                extra_http_headers=self._get_common_headers(),
            )
            
            # Override webdriver detection
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            """)
            
            try:
                page = await context.new_page()
                
                # ── Step 1: Visit homepage ──
                print(f"  [deep_crawl] Visiting homepage: {base_url}")
                await page.goto(base_url, wait_until='domcontentloaded', timeout=15000)
                await self._wait_for_content(page)
                
                homepage_html = await page.content()
                homepage_text = self._extract_text_from_html(homepage_html)
                combined_text_parts.append(f"--- HOMEPAGE ({base_url}) ---\n{homepage_text}")
                print(f"  [deep_crawl] Homepage extracted ({len(homepage_text)} chars)")
                
                # ── Step 2: Find relevant links on homepage ──
                scored_links = await self._collect_links_from_page(page, base_url)
                print(f"  [deep_crawl] Found {len(scored_links)} relevant links")
                
                # ── Step 3: Visit top sub-pages ──
                visited_count = 0
                for link_url, link_text, score in scored_links:
                    if visited_count >= max_sub_pages:
                        break
                    
                    try:
                        print(f"  [deep_crawl] Visiting sub-page ({score} pts): {link_url} ({link_text.strip()[:40]})")
                        
                        sub_page = await context.new_page()
                        await sub_page.goto(link_url, wait_until='domcontentloaded', timeout=15000)
                        await self._wait_for_content(sub_page)
                        
                        sub_html = await sub_page.content()
                        sub_text = self._extract_text_from_html(sub_html)
                        combined_text_parts.append(f"--- SUB-PAGE: {link_text.strip()} ({link_url}) ---\n{sub_text}")
                        print(f"  [deep_crawl] Sub-page extracted ({len(sub_text)} chars)")
                        
                        await sub_page.close()
                        visited_count += 1
                        
                        # Small delay between page visits
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        
                    except Exception as e:
                        print(f"  [deep_crawl] Failed to visit {link_url}: {e}")
                        continue
                
            finally:
                await context.close()
                await browser.close()
        
        combined_text = "\n\n".join(combined_text_parts)
        print(f"  [deep_crawl] Complete: {len(combined_text)} total chars from {1 + visited_count} pages")
        return combined_text


# Example usage and testing
if __name__ == '__main__':
    async def main():
        toolkit = CrawlerToolkit(headless=True)
        
        try:
            # Deep crawl a single company
            result = await toolkit.deep_crawl_company('https://example.com', max_sub_pages=3)
            
            print(f"\n{'='*60}")
            print(f"DEEP CRAWL RESULT ({len(result)} chars)")
            print(f"{'='*60}")
            print(result[:500] + "..." if len(result) > 500 else result)
        
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(main())