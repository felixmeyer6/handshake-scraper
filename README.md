# Handshake Scraper

Scrapes job offers from a Handshake search URL into a CSV. If your school/organization uses SSO, you’ll log in once in a normal Chrome window; the script reuses a local Chrome profile for subsequent runs.

## Features

* Paginates through a Handshake search.
* Visits each job page and extracts key fields.
* Writes a tidy CSV (`handshake_jobs.csv`) ready for analysis.

## Extracted columns

* **Company**
    * Name
    * Sector
    * Headcount
* **Job**
    * Title
    * PostedAt
    * Duration
    * Start
    * Location
    * Description
    * Link

## Requirements

* **Python**: 3.9+ recommended
* **Google Chrome** installed
* **Dependencies**: `pandas`, `selenium`, `webdriver-manager`

## Quick Start

1.  Clone / download the repo and open it in a terminal.
2.  (Optional) Create a virtual environment
    ```bash
    # macOS/Linux
    python -m venv .venv
    source .venv/bin/activate
    
    # Windows
    .\.venv\Scripts\activate
    ```
3.  Install dependencies
    ```bash
    pip install pandas selenium webdriver-manager
    ```
4.  Run the scraper with a Handshake search URL that contains `page=1`:
    ```bash
    python3 handshake_scraper.py \
      -u "https://yourorg.joinhandshake.fr/job-search/123456?query=yourdreamjob&per_page=25&page=1" \
      -p 2 \
      -t 10
    ```
    * `-u/--url` (required): Full search URL including `page=1`.
    * `-p/--pages` (optional): Max pages to scrape starting from 1 (default -1 = unlimited).
    * `-t/--throttle` (optional): Slowness 0..100 (default 10). Higher = slower & gentler.

5.  **Output**: `handshake_jobs.csv` in the current folder.

## What you’ll see in the terminal

* `[SSO]` … login hints
* `[PAGE]` … pagination progress
* `[JOB i/N]` … job pages being scraped
* `[SLEEP]` … time throttling
* `[DATA]` … one-line records per field
* `[WARN]` … warnings
* `[OK]` … on success

## Login & Session Notes

The script uses a persistent Chrome profile at:

* **macOS/Linux**: `~/.handshake_chrome_profile`
* **Windows**: `C:\Users\<you>\.handshake_chrome_profile`

First run may prompt you to log in. Subsequent runs reuse the session.

## Tips

* **Headless mode**: By default, Chrome is not headless so you can log in. After you’re logged in once, you can set `headless=True` in `setup_driver()` if you prefer (advanced users).
* **Be gentle**: Increase `-t` if you need more time between requests.
* **Pagination**: The script updates the `page` param internally (must start with `page=1` in your URL).

## Example Usage

```bash
# 1) Activate env (optional)
python -m venv .venv && source .venv/bin/activate

# 2) Install deps
pip install pandas selenium webdriver-manager

# 3) Run
python3 handshake_scraper.py -u "https://yourorg.joinhandshake.fr/job-search/123456?query=yourdreamjob&per_page=25&page=1" -p 10 -t 50

# 4) Open results
open handshake_jobs.csv  # macOS
# or:
start handshake_jobs.csv # Windows
```

## Troubleshooting

* **No CSV written**: If no jobs are found or pages error out, you’ll see [WARN] No rows scraped. Confirm your URL is valid and includes page=1, you’re logged in, and the page has listings.
* **Blocked/Rate-limited**: Increase `-t` or try fewer pages.
* **Layout changes**: The script uses XPath selectors; if Handshake changes markup, some fields may come back empty. Update the XPaths in the constants section.
* **Persisting Chrome session**: If you see `SessionNotCreatedException: ... user data directory is already in use`, it means a previous Chrome session still owns the profile.
1.  Close any leftover Chrome/driver windows or
2.  Delete the profile folder `~/.handshake_chrome_profile` and re-run or
3.  Run one instance at a time.

## Safety & Respect

Use responsibly and follow your organization’s and Handshake’s terms of service. Avoid aggressive scraping (raise `-t`, limit pages) and cache results when possible.
