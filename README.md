# Contact Detail Agent

An automated lead generation system that finds and extracts company contact information for exporters and manufacturers exporting to the European Union (EU). The system searches for companies by commodity, country, and industry, then scrapes their websites to extract structured contact data.

## Features

- **EU-Focused Search**: Targeted queries to find companies exporting to EU markets
- **Intelligent Query Generation**: Uses LLM to generate 40+ diverse search queries with site: operators
- **Concurrent Crawling**: Processes up to 5 websites in parallel for faster results
- **Anti-Detection Crawling**: User agent rotation, custom headers, browser fingerprinting
- **Smart Page Discovery**: Automatically finds Contact and About pages
- **Obfuscation Handling**: Decodes emails like "info [at] company . com"
- **No Hallucination**: Returns null for missing data instead of guessing
- **Social Media Filtering**: Focuses on business directories and corporate sites
- **Deduplication**: Removes duplicate companies by normalized name and merges contact details
- **Retry Logic**: Exponential backoff for API failures and rate limits
- **Comprehensive Extraction**: 16 data fields including EU destinations, LinkedIn, social links
- **Progress Tracking**: Rich console with progress bars and structured logging

## Architecture

The system follows a 3-stage pipeline:

1. **Discovery (Search Agent)** - Generates 40+ EU-focused search queries and gathers company URLs
2. **Intelligence (Scraper Agent + Crawler Toolkit)** - Concurrently crawls websites with anti-detection features
3. **Action (Analyst Agent + Output Writer)** - Validates trade status, scores leads, deduplicates, and saves results

## Installation

### Prerequisites

- Python 3.10 or higher
- API keys for OpenRouter and a search provider (Tavily or Serper)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/Paraschamoli/Contact-Detail-Agent.git
cd Contact-Detail-Agent
```

2. Install dependencies:
```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

**Important:** Always use `uv run` to execute the script to ensure the correct Python environment is used:
```bash
uv run python index.py --commodity textiles --country India
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys
```

### Required API Keys

- **OpenRouter**: Get your key at https://openrouter.ai/keys
- **Tavily** (recommended): Get your key at https://app.tavily.com/
- **Serper** (alternative): Get your key at https://serper.dev/

## Usage

### Basic Usage

```bash
uv run python index.py --commodity textiles --country India --industry textiles
```

### Advanced Usage

```bash
uv run python index.py \
  --commodity electronics \
  --country Germany \
  --industry manufacturing \
  --queries-per-pattern 10 \
  --model "anthropic/claude-3.5-sonnet" \
  --output-dir results
```

### With Email Outreach

```bash
uv run python index.py \
  --commodity textiles \
  --country India \
  --outreach
```

This generates personalized B2B email drafts for leads with score >= 80.

### Using the CLI Entry Point

```bash
uv run contact-agent --commodity textiles --country India
```

## Parameters

- `--commodity, -c`: Product/commodity to search for (required)
- `--country, -C`: Country to search in (required)
- `--industry, -i`: Optional industry category
- `--queries-per-pattern, -q`: Number of results per search query (default: 10)
- `--model, -m`: LLM model to use (default: openai/gpt-oss-120b:nitro)
- `--output-dir, -o`: Output directory for results (default: output)
- `--outreach`: Generate personalized email drafts for leads with score >= 80

## Output

The system generates a timestamped CSV file with the following columns:

**Core Information:**
- `tier`: Lead quality tier (Tier 1 = best, Tier 3 = lowest)
- `lead_score`: AI-generated lead score (0-100)
- `legitimacy_level`: Trade legitimacy assessment (Green/Yellow/Red)
- `company_name`: Official company name
- `website`: Company website URL
- `location`: Company address or location
- `country`: Country where company is located
- `contact_person`: Specific contact person if available
- `product_category`: Product category (e.g., textiles, electronics)
- `business_description`: Brief company business description

**Contact Information:**
- `direct_emails`: All department emails (sales@, exports@, info@, etc.)
- `email_confidence_avg`: Average email confidence score
- `has_verified_email`: Whether email was verified
- `phone_numbers`: All phone numbers in international format
- `linkedin_profile`: LinkedIn company page URL
- `social_links`: Other social media profile URLs

**Export Information:**
- `export_details`: Specific products the company exports
- `export_region`: Export markets or regions served
- `eu_destinations`: Specific EU countries they export to
- `certifications`: Certifications (ISO, CE, REX, etc.)
- `key_executives`: Key executives with names and titles

**Analysis & Metadata:**
- `product_match`: Product match assessment
- `eu_compliance`: EU compliance status
- `company_type`: Manufacturer vs. Trader/Middleman
- `reasoning`: AI reasoning for the score
- `email_draft_subject/recipient/body`: Outreach email drafts (if --outreach used)
- `backup_url`: Backup URL if primary crawl failed
- `crawl_failure`: Failure reason if crawl failed

Example output file: `output/textiles_India_detailed_20240108_143022.csv`

## Configuration

### Search Patterns

Edit `config/settings.yaml` to customize search query patterns. The default patterns are EU-focused to target exporters:

```yaml
global_search_queries:
  - "{commodity} exporters in {country} to EU directory"
  - "list of {commodity} manufacturers in {country} exporting to Europe"
  - "site:europages.com {commodity} {country}"
  - "site:kompass.com {commodity} exporters {country} EU"
  - "REX registered {commodity} exporters {country}"
```

The system automatically generates 40+ diverse queries using:
- Site-specific searches (europages.com, kompass.com, alibaba.com, indiamart.com)
- EU compliance searches (REX registered, CE certified)
- Specific EU country targets (Germany, France, Netherlands)
- Government/export promotion sites
- Industry association directories

## Development

### Development Setup

```bash
# Install development dependencies
uv sync --dev

# Or with pip
pip install -e ".[dev]"
```

### Code Quality

```bash
# Format code
black .

# Lint code
ruff check .

# Type checking
mypy .
```

### Testing

```bash
pytest
```

## Project Structure

```
contact-detail-agent/
├── agents/
│   ├── search_agent.py      # LLM-powered EU-focused search query generation
│   ├── scraper_agent.py     # Concurrent crawling with backup URL support
│   └── analyst_agent.py     # Lead scoring and EU compliance assessment
├── tools/
│   ├── search_toolkit.py    # Search API integration (Tavily/Serper) with retry logic
│   ├── crawler_toolkit.py   # Playwright-based web crawling with anti-detection
│   ├── trade_validator.py   # EU trade legitimacy validation (VIES, REX)
│   ├── mailer_toolkit.py    # Personalized B2B email drafting
│   └── verification_toolkit.py # Email verification (syntax, domain, mailbox)
├── utils/
│   ├── llm_extractor.py     # Structured contact information extraction (16 fields)
│   └── output_writer.py     # CSV/Excel output with deduplication
├── config/
│   ├── settings.yaml        # EU-focused search patterns
│   └── industry_params.json # Industry-specific parameters
├── output/                  # Generated results (CSV files)
├── storage/                 # Crawlee runtime storage (auto-generated, can be deleted)
├── index.py                 # Main CLI entry point
├── pyproject.toml          # Project configuration
├── .env.example             # Environment variables template
└── .gitignore              # Git ignore rules
```

## API Integration

### Search Providers

- **Tavily**: Better search results, supports advanced filtering
- **Serper**: Google Search API integration

### LLM Models

Supports models available via OpenRouter:
- Claude 3.5 Sonnet (recommended)
- GPT-4o
- Other OpenRouter models

## Security & Privacy

- API keys stored in environment variables (never committed)
- Social media links filtered out for privacy
- No personal data stored or cached
- Anti-detection features for ethical crawling

## Troubleshooting

### Common Issues

1. **ModuleNotFoundError**: Always use `uv run` to execute scripts - it ensures the correct Python environment
   ```bash
   uv run python index.py --commodity textiles --country India
   ```

2. **API Key Errors**: Ensure all required API keys are set in `.env`
   - `OPENROUTER_API_KEY` is required
   - `TAVILY_API_KEY` or `SERPER_API_KEY` is required

3. **Rate Limits**: Reduce `--queries-per-pattern` if hitting API limits
   ```bash
   uv run python index.py --commodity textiles --country India --queries-per-pattern 5
   ```

4. **Crawling Failures**: Some sites may block crawlers; results vary. The system automatically tries backup URLs.

5. **Empty Results**: Try different search terms or increase query count. The system uses 40+ queries by default.

6. **Low Quality Results**: Search APIs may return directory pages instead of actual company sites. This is a limitation of the search provider.

### Logging

Detailed logs are written to `agent.log` in the project directory. Check this file for debugging issues with search, crawling, or extraction.

### Storage Directory

The `storage/` directory contains temporary Crawlee runtime data. It can be safely deleted:
```bash
rm -rf storage/
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Support

For issues and questions:
- Open an issue on GitHub
- Check the troubleshooting section
- Review the configuration documentation
