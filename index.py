"""
Main entry point for the contact detail agent CLI.
Orchestrates the full 3-stage pipeline:
  Discovery: Find URLs (Search Agent)
  Intelligence: Extract contacts and product details (Scraper Agent + Crawler)
  Action: Validate trade status, score leads, and draft outreach (Analyst + Mailer)
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from typing import List, Dict

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agents.search_agent import SearchAgent, CompanySeed
from agents.scraper_agent import ScraperAgent, ScrapedCompany, CrawlStatus
from agents.analyst_agent import AnalystAgent, LeadScore
from tools.crawler_toolkit import CrawlerToolkit
from tools.trade_validator import TradeValidator
from tools.mailer_toolkit import MailerToolkit
from utils.llm_extractor import LLMExtractor, CompanyProfile
from utils.output_writer import OutputWriter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('agent.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="Contact Detail Agent - Find, validate, and outreach to trade leads")
console = Console()


async def run_pipeline(
    commodity: str,
    country: str,
    industry: str,
    queries_per_pattern: int,
    model: str,
    output_dir: str,
    outreach: bool,
):
    """Run the complete 3-stage pipeline asynchronously."""
    console.print(f"\n[bold blue]═══ Contact Detail Agent ═══[/bold blue]")
    console.print(f"Commodity: [cyan]{commodity}[/cyan] | Country: [cyan]{country}[/cyan]")
    if industry:
        console.print(f"Industry: [cyan]{industry}[/cyan]")
    if outreach:
        console.print(f"Outreach: [green]ENABLED[/green] (email drafts for scores >= 80)")
    console.print()
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            
            # ═══════════════════════════════════════════════════
            # STAGE 1: DISCOVERY - Find URLs
            # ═══════════════════════════════════════════════════
            task1 = progress.add_task("[bold cyan]Stage 1: DISCOVERY - Finding company URLs...", total=100)
            
            search_agent = SearchAgent(model=model)
            progress.update(task1, advance=10)
            
            seed_list = search_agent.gather_seed_list(
                commodity=commodity,
                country=country,
                industry=industry,
                queries_per_pattern=queries_per_pattern
            )
            progress.update(task1, advance=90)
            
            if not seed_list:
                console.print("[red]No companies found. Exiting.[/red]")
                return
            
            console.print(f"[green]✓[/green] Found {len(seed_list)} company URLs")
            progress.update(task1, completed=100)
            
            # ═══════════════════════════════════════════════════
            # STAGE 2: INTELLIGENCE - Extract contacts & details
            # ═══════════════════════════════════════════════════
            task2 = progress.add_task("[bold cyan]Stage 2: INTELLIGENCE - Crawling & extracting...", total=100)
            
            # 2a: Deep crawl each company
            scraper_agent = ScraperAgent(model=model)
            progress.update(task2, advance=5)
            
            scraped_results = await scraper_agent.investigate_all(seed_list)
            progress.update(task2, advance=40)
            
            # 2b: Extract deep profiles from crawled text
            extractor = LLMExtractor(model=model)
            # verification = VerificationToolkit()  # Disabled - no email service purchased
            progress.update(task2, advance=45)
            
            profiles: List[Dict] = []
            for i, scraped in enumerate(scraped_results, 1):
                progress.update(task2, description=f"[bold cyan]Stage 2: INTELLIGENCE - Extracting profiles ({i}/{len(scraped_results)})...")
                
                if scraped.status != CrawlStatus.FAILED and scraped.crawled_text:
                    # Extract deep profile
                    profile = extractor.extract_deep_from_crawled_text(
                        crawled_text=scraped.crawled_text,
                        url=scraped.backup_url or scraped.original_url
                    )
                    profile_dict = profile.model_dump()
                    
                    # Set website from original URL if not extracted
                    if not profile_dict.get('website'):
                        profile_dict['website'] = scraped.original_url
                    
                    # Inject commodity/country if not extracted by LLM
                    if not profile_dict.get('country'):
                        profile_dict['country'] = country
                    if not profile_dict.get('product_category'):
                        profile_dict['product_category'] = commodity
                    
                    # Verify emails - disabled (no email service purchased)
                    profile_dict['email_verifications'] = []
                    profile_dict['email_confidence_avg'] = 0.0
                    profile_dict['has_verified_email'] = False
                    
                else:
                    # Failed crawl - create minimal profile
                    profile_dict = CompanyProfile(
                        company_name=scraped.company_name,
                        website=scraped.original_url,
                        country=country,
                        product_category=commodity,
                    ).model_dump()
                    profile_dict['email_verifications'] = []
                    profile_dict['email_confidence_avg'] = 0.0
                    profile_dict['has_verified_email'] = False
                    if scraped.failure_reason:
                        profile_dict['_crawl_failure'] = scraped.failure_reason
                
                # Add backup URL info if applicable
                if scraped.backup_url:
                    profile_dict['_backup_url'] = scraped.backup_url
                    profile_dict['_crawl_status'] = scraped.status.value
                
                profiles.append(profile_dict)
                progress.update(task2, advance=(45 / len(scraped_results)))
            
            progress.update(task2, description="[bold cyan]Stage 2: INTELLIGENCE - Crawling & extracting...")
            progress.update(task2, completed=100)
            
            console.print(f"[green]✓[/green] Extracted {len(profiles)} company profiles")
            
            # ═══════════════════════════════════════════════════
            # STAGE 3: ACTION - Validate, Score, Outreach
            # ═══════════════════════════════════════════════════
            task3 = progress.add_task("[bold cyan]Stage 3: ACTION - Validating & scoring leads...", total=100)
            
            # 3a: Trade validation
            trade_validator = TradeValidator()
            progress.update(task3, advance=5)
            
            legitimacy_levels = {}
            for i, profile in enumerate(profiles, 1):
                progress.update(task3, description=f"[bold cyan]Stage 3: ACTION - Trade validation ({i}/{len(profiles)})...")
                legitimacy = trade_validator.validate_company(profile)
                legitimacy_levels[profile.get('company_name', '')] = legitimacy.legitimacy_level
                profile['_legitimacy_level'] = legitimacy.legitimacy_level
                profile['_legitimacy_details'] = legitimacy.model_dump()
                progress.update(task3, advance=(20 / len(profiles)))
            
            # 3b: Score leads
            analyst = AnalystAgent(model=model)
            progress.update(task3, advance=25)
            
            lead_scores = analyst.score_all_leads(
                profiles=profiles,
                commodity=commodity,
                country=country,
                legitimacy_levels=legitimacy_levels
            )
            progress.update(task3, advance=50)
            
            # Merge scores into profiles
            score_lookup = {s.company_name: s for s in lead_scores}
            for profile in profiles:
                name = profile.get('company_name', '')
                if name in score_lookup:
                    score = score_lookup[name]
                    profile['_lead_score'] = score.score
                    profile['_product_match'] = score.product_match
                    profile['_eu_compliance'] = score.eu_compliance
                    profile['_company_type'] = score.company_type
                    profile['_reasoning'] = score.reasoning
            
            # 3c: Draft outreach emails (if --outreach enabled)
            email_drafts = []
            if outreach:
                progress.update(task3, description="[bold cyan]Stage 3: ACTION - Drafting outreach emails...")
                mailer = MailerToolkit(model=model)
                
                score_dicts = [s.model_dump() for s in lead_scores]
                email_drafts = mailer.draft_emails_for_leads(
                    profiles=profiles,
                    lead_scores=score_dicts,
                    commodity=commodity,
                    country=country,
                    min_score=80
                )
                
                # Merge drafts into profiles
                draft_lookup = {d.company_name: d for d in email_drafts}
                for profile in profiles:
                    name = profile.get('company_name', '')
                    if name in draft_lookup:
                        draft = draft_lookup[name]
                        profile['_email_draft_subject'] = draft.subject
                        profile['_email_draft_body'] = draft.body
                        profile['_email_draft_recipient'] = draft.recipient_email or ''
            
            progress.update(task3, completed=100)
            
            # ═══════════════════════════════════════════════════
            # DEDUPLICATE & SAVE OUTPUT
            # ═══════════════════════════════════════════════════
            task4 = progress.add_task("[bold cyan]Deduplicating & saving results...", total=100)
            
            output_writer = OutputWriter(output_dir=output_dir)
            progress.update(task4, advance=10)
            
            # Deduplicate profiles by company name
            pre_dedup = len(profiles)
            profiles = output_writer.deduplicate_profiles(profiles)
            deduped = pre_dedup - len(profiles)
            console.print(f"[green]✓[/green] Deduplicated: removed {deduped} duplicates ({len(profiles)} unique companies)")
            progress.update(task4, advance=30)
            
            filepath = output_writer.write_detailed_csv(
                profiles=profiles,
                commodity=commodity,
                country=country
            )
            progress.update(task4, completed=100)
        
        # ═══════════════════════════════════════════════════
        # FINAL SUMMARY
        # ═══════════════════════════════════════════════════
        console.print()
        console.print(f"[bold green]═══ Pipeline Complete ═══[/bold green]")
        console.print(f"Output: {filepath}")
        
        # Lead score table
        table = Table(title="Lead Scores", show_lines=True)
        table.add_column("Company", style="cyan")
        table.add_column("Score", justify="center")
        table.add_column("Product Match", style="green")
        table.add_column("EU Compliance", style="yellow")
        table.add_column("Type", style="magenta")
        table.add_column("Legitimacy", justify="center")
        
        for score in lead_scores[:15]:  # Show top 15
            legit = legitimacy_levels.get(score.company_name, "Unknown")
            legit_style = {"Green": "green", "Yellow": "yellow", "Red": "red"}.get(legit, "white")
            table.add_row(
                score.company_name,
                str(score.score),
                score.product_match or "-",
                score.eu_compliance or "-",
                score.company_type or "-",
                f"[{legit_style}]{legit}[/{legit_style}]"
            )
        
        console.print(table)
        
        # Statistics
        high = sum(1 for s in lead_scores if s.score >= 80)
        medium = sum(1 for s in lead_scores if 50 <= s.score < 80)
        low = sum(1 for s in lead_scores if s.score < 50)
        green = sum(1 for v in legitimacy_levels.values() if v == "Green")
        
        console.print(f"\n[bold]Statistics:[/bold]")
        console.print(f"  Total leads: {len(profiles)}")
        console.print(f"  High score (80+): {high}")
        console.print(f"  Medium score (50-79): {medium}")
        console.print(f"  Low score (<50): {low}")
        console.print(f"  Green legitimacy: {green}")
        
        if outreach and email_drafts:
            console.print(f"  Email drafts generated: {len(email_drafts)}")
        
        # Show reasoning for top leads
        if lead_scores:
            console.print(f"\n[bold]Top Lead Reasoning:[/bold]")
            for score in lead_scores[:3]:
                console.print(f"  [cyan]{score.company_name}[/cyan] ({score.score}/100)")
                console.print(f"    {score.reasoning[:200]}")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        raise typer.Exit(code=1)


@app.command()
def main(
    commodity: str = typer.Option(..., "--commodity", "-c", help="Commodity to search for (e.g., 'steel sheets', 'textiles')"),
    country: str = typer.Option(..., "--country", "-C", help="Country to search in (e.g., 'India', 'Germany')"),
    industry: str = typer.Option(None, "--industry", "-i", help="Optional industry category"),
    queries_per_pattern: int = typer.Option(3, "--queries-per-pattern", "-q", help="Number of results per search query"),
    model: str = typer.Option("openai/gpt-oss-120b:nitro", "--model", "-m", help="LLM model to use"),
    output_dir: str = typer.Option("output", "--output-dir", "-o", help="Output directory for results"),
    outreach: bool = typer.Option(False, "--outreach", help="Generate personalized email drafts for leads with score >= 80"),
):
    """
    Run the contact detail agent through the full 3-stage pipeline.
    
    Stage 1 - Discovery: Find company URLs using search APIs
    Stage 2 - Intelligence: Deep crawl & extract contact/product details
    Stage 3 - Action: Validate trade status, score leads, draft outreach
    
    Use --outreach to also generate personalized B2B email drafts.
    
    Example:
        python index.py --commodity "steel sheets" --country India --outreach
        python index.py -c textiles -C India -i textiles -m "openai/gpt-4o"
    """
    asyncio.run(run_pipeline(
        commodity=commodity,
        country=country,
        industry=industry,
        queries_per_pattern=queries_per_pattern,
        model=model,
        output_dir=output_dir,
        outreach=outreach
    ))


if __name__ == "__main__":
    app()