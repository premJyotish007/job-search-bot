# LinkedIn Job Search & Matching Discord Bot

A Python-based LinkedIn job scraper, Gemini match analyzer, and interactive Discord bot pipeline designed to search for and filter relevant job postings matching specific resume criteria in real-time.

## Features
- **Browser Automation (`linkedin_scraping.py`)**: Uses Playwright to authenticate with LinkedIn and scrape job descriptions across paginated pages (from `start=1` to `start=76` to fetch the top 100 listings).
- **Gemini Match Evaluator (`analyze.py`)**: Harnesses `gemini-3.1-flash-lite` to evaluate candidate alignment based on experience thresholds, company size, and skill fit.
- **Discord Bot Control (`bot.py`)**: Runs two separated real-time streaming commands:
  - `!find [limit]`: Scrapes listings and streams results as they are parsed, skipping already scraped job IDs.
  - `!analyze [limit]`: Evaluates unapplied jobs, showing green embeds for matches and compact single-line messages for skips.
- **Interactive Checkboxes**: Toggles the `"applied": "true"` state in `extracted_jobs.json` dynamically when a user clicks the **Applied ✅** button on any Discord message (persists across bot restarts).

---

## macOS Discord API Connection SSL Certificate Fix

If you run the bot on macOS, Python's default SSL validation might fail with the following error:
```
[SSLCertVerificationError: (1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1000)')]
```

### Resolution Steps
To resolve this globally on macOS:
1. Locate the Python installation directory on your system (e.g. `/Applications/Python 3.12/`).
2. Run the certificate installation script included with Python. In a terminal:
   ```bash
   open "/Applications/Python 3.12/Install Certificates.command"
   ```
   *(Adjust `3.12` to match your active Python version).*
3. Alternatively, the bot incorporates a fallback bypass:
   ```python
   import ssl
   ssl._create_default_https_context = ssl._create_unverified_context
   ```

---

## Setup Instructions

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install
   ```

2. **Configure Environment Variables**
   Create a `.env` file in the project root:
   ```env
   LINKEDIN_EMAIL=your_email@gmail.com
   LINKEDIN_PASSWORD=your_password
   TARGET_URL=https://www.linkedin.com/login
   JOBS_URL=https://www.linkedin.com/jobs/search-results/?...
   GEMINI_API_KEY=your_gemini_api_key
   DISCORD_BOT_TOKEN=your_discord_bot_token
   ```

3. **Start the Bot**
   ```bash
   python bot.py
   ```
