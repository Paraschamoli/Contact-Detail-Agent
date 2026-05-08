"""
Main entry point for the contact detail agent CLI.
Orchestrates Search Agent, Crawler Toolkit, LLM Extractor, and Output Writer.
"""

import asyncio
import sys
import os
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agents.search_agent import SearchAgent, CompanySeed
from tools.crawler_toolkit import CrawlerToolkit
from utils.llm_extractor import LLMExtractor, CompanyContact
from utils.output_writer import OutputWriter

app = typer.Typer(help="Contact Detail Agent - Find and extract company contact information")
console = Console()


@app.command()
def main(
    commodity: str = typer.Option(..., "--commodity", "-c", help="Commodity to search for (e.g., 'textiles', 'electronics')"),
    country: str = typer.Option(..., "--country", "-C", help="Country to search in (e.g., 'India', 'Germany')"),
    industry: str = typer.Option(None, "--industry", "-i", help="Optional industry category"),
    queries_per_pattern: int = typer.Option(3, "--queries-per-pattern", "-q", help="Number of results per search query"),
    model: str = typer.Option("anthropic/claude-3.5-sonnet", "--model", "-m", help="LLM model to use"),
    output_dir: str = typer.Option("output", "--output-dir", "-o", help="Output directory for results"),
):
    """
    Run the contact detail agent to find and extract company information.
    
    Example:
        python index.py --commodity textiles --country India --industry textiles
    """
    console.print(f"[bold blue]Starting Contact Detail Agent[/bold blue]")
    console.print(f"Commodity: {commodity}")
    console.print(f"Country: {country}")
    if industry:
        console.print(f"Industry: {industry}")
    console.print()
    
    try:
        # Stage 1: Search Agent - Generate URLs
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            
            task1 = progress.add_task("[cyan]Stage 1: Searching for company URLs...", total=100)
            
            # Initialize Search Agent
            search_agent = SearchAgent(model=model)
            progress.update(task1, advance=20)
            
            # Gather seed list
            seed_list = search_agent.gather_seed_list(
                commodity=commodity,
                country=country,
                industry=industry,
                queries_per_pattern=queries_per_pattern
            )
            progress.update(task1, advance=80)
            
            if not seed_list:
                console.print("[red]No companies found. Exiting.[/red]")
                return
            
            console.print(f"[green]✓[/green] Found {len(seed_list)} company URLs")
            progress.update(task1, completed=100)
            
            # Stage 2: Crawler Toolkit - Scrape websites
            task2 = progress.add_task("[cyan]Stage 2: Crawling websites for contact info...", total=100)
            
            # Initialize Crawler Toolkit
            crawler = CrawlerToolkit(headless=True)
            progress.update(task2, advance=10)
            
            # Extract URLs from seed list
            urls = [seed.url for seed in seed_list]
            progress.update(task2, advance=20)
            
            # Crawl websites
            crawled_data = await crawler.crawl_urls(urls)
            progress.update(task2, advance=80)
            
            console.print(f"[green]✓[/green] Crawled {len(crawled_data)} websites")
            progress.update(task2, completed=100)
            
            # Stage 3: LLM Extractor - Extract contact details
            task3 = progress.add_task("[cyan]Stage 3: Extracting contact information with LLM...", total=100)
            
            # Initialize LLM Extractor
            extractor = LLMExtractor(model=model)
            progress.update(task3, advance=10)
            
            # Extract contacts from crawled data
            extracted_contacts: List[CompanyContact] = []
            
            for i, (base_url, content_dict) in enumerate(crawled_data.items(), 1):
                progress.update(task3, description=f"[cyan]Stage 3: Extracting contact information with LLM... ({i}/{len(crawled_data)})")
                
                try:
                    # Extract from multiple pages (main, contact, about)
                    contact = extractor.extract_from_multiple_pages(content_dict, base_url)
                    extracted_contacts.append(contact)
                    
                    progress.update(task3, advance=(70 / len(crawled_data)))
                    
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to extract from {base_url}: {e}[/yellow]")
                    progress.update(task3, advance=(70 / len(crawled_data)))
            
            progress.update(task3, description="[cyan]Stage 3: Extracting contact information with LLM...")
            progress.update(task3, advance=20)
            
            console.print(f"[green]✓[/green] Extracted contact info from {len(extracted_contacts)} companies")
            progress.update(task3, completed=100)
            
            # Stage 4: Output Writer - Save results
            task4 = progress.add_task("[cyan]Stage 4: Saving results to CSV...", total=100)
            
            # Initialize Output Writer
            output_writer = OutputWriter(output_dir=output_dir)
            progress.update(task4, advance=20)
            
            # Save to CSV
            filepath = output_writer.write_pydantic_to_csv(
                objects=extracted_contacts,
                filename_prefix=f"{commodity}_{country}_leads"
            )
            progress.update(task4, advance=80)
            
            console.print(f"[green]✓[/green] Results saved to {filepath}")
            progress.update(task4, completed=100)
        
        # Final summary
        console.print()
        console.print(f"[bold green]=== Pipeline Complete ===[/bold green]")
        console.print(f"Total companies processed: {len(extracted_contacts)}")
        console.print(f"Output file: {filepath}")
        
        # Show extraction statistics
        with_email = sum(1 for c in extracted_contacts if c.official_email)
        with_phone = sum(1 for c in extracted_contacts if c.phone_number)
        with_region = sum(1 for c in extracted_contacts if c.export_region)
        
        console.print()
        console.print(f"[bold]Extraction Statistics:[/bold]")
        console.print(f"  - Companies with email: {with_email}/{len(extracted_contacts)}")
        console.print(f"  - Companies with phone: {with_phone}/{len(extracted_contacts)}")
        console.print(f"  - Companies with export region: {with_region}/{len(extracted_contacts)}")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()