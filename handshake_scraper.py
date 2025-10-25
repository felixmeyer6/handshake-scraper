"""
Handshake Scraper
--------------------------------------------------------------
Usage:
  python3 handshake_scraper.py -u "<SEARCH_URL_WITH_page=1>" [-p MAX_PAGES|-1] [-t THROTTLE]

Args:
  -u / --url       (required) Full search URL that includes page=1 (we'll override per page).
  -p / --pages     (optional) Max pages to scrape, starting at 1. Default -1 (unlimited).
  -t / --throttle  (optional) 0..100 slowness knob (0=no delay, 100≈10s avg). Default 10.

Output:
  handshake_jobs.csv in the current directory.
"""

import argparse
import atexit
import calendar
import os
import random
import re
import shutil
import signal
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# =======================
# Constants / Selectors
# =======================

JOB_LINK_SELECTOR = 'main#skip-to-content a[href^="/job-search/"]:not([href*="#"])'
PROFILE_DIR = str(Path.home() / ".handshake_chrome_profile")

TITLE_XPATH = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/div[2]/div[1]/div[1]/div[1]/div[1]/a[1]/h1[1]"
COMPANY_NAME_XPATH = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/a[1]/div[1]"
COMPANY_SECTOR_XPATH = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/a[2]/div[1]"
LOCATION_XPATH = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/div[2]/div[1]/div[1]/div[1]/div[4]/div[3]/div[1]/div[1]"
DURATION_XPATH = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/div[2]/div[1]/div[1]/div[1]/div[4]/div[4]/div[1]/div[2]"
DESCRIPTION_XPATH = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/div[2]/div[1]/div[1]/div[1]/div[5]/div[1]/div[1]/div[1]"
MORE_BUTTON_XPATH = "//button[contains(., 'More') or contains(., 'Voir plus')]"
POSTED_AT_XPATH = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/div[2]/div[1]/div[1]/div[1]/div[1]/div[2]"
COMPANY_HEADCOUNT_XPATH = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/div[2]/div[1]/div[1]/div[1]/div[*]/div[3]/span[1]"
ERROR_BANNER_XPATH = (
    '//*[contains(normalize-space(.), "Something went wrong. Please try again.")]'
)

# =======================
# Data Model
# =======================


@dataclass
class JobRowInternal:
    url: str
    title: str
    company_name: str
    company_sector: str
    company_headcount: str
    location: str
    duration_months: str
    posted_at: str
    description: str
    start: str  # MM/YYYY


# =======================
# Globals
# =======================

DRIVER = None
THROTTLE = 10.0
RNG = random.Random()

# =======================
# CLI / URL Helpers
# =======================


def parse_args():
    p = argparse.ArgumentParser(description="Handshake scraper (one-line [DATA] logs).")
    p.add_argument(
        "-u",
        "--url",
        required=True,
        help="Handshake search URL (should include page=1; we'll override per page).",
    )
    p.add_argument(
        "-p",
        "--pages",
        type=int,
        default=-1,
        help="Max pages to scrape starting from 1. Default -1 (unlimited).",
    )
    p.add_argument(
        "-t",
        "--throttle",
        type=float,
        default=10.0,
        help="Slowness 0..100. 0=no delay, 100≈10s average between loads. Default 10.",
    )
    return p.parse_args()


def strip_url_params(u: str) -> str:
    p = urlparse(u)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def ensure_page_param(u: str) -> str:
    pr = urlparse(u)
    q = parse_qs(pr.query, keep_blank_values=True)
    if "page" not in q:
        q["page"] = ["1"]
    new_q = urlencode(q, doseq=True)
    return urlunparse(pr._replace(query=new_q))


def build_page_url(base_url: str, page_num: int) -> str:
    pr = urlparse(base_url)
    q = parse_qs(pr.query, keep_blank_values=True)
    q["page"] = [str(page_num)]
    new_q = urlencode(q, doseq=True)
    return urlunparse(pr._replace(query=new_q))


def origin_of(u: str) -> str:
    pr = urlparse(u)
    return f"{pr.scheme}://{pr.netloc}"


# =======================
# Driver / Wait / Cleanup
# =======================


def setup_driver(headless=False) -> webdriver.Chrome:
    global DRIVER
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--lang=fr-FR,fr;q=0.9,en;q=0.8")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    service = ChromeService(ChromeDriverManager().install())
    DRIVER = webdriver.Chrome(service=service, options=opts)
    DRIVER.set_page_load_timeout(60)
    return DRIVER


def wait(drv, secs=20):
    return WebDriverWait(drv, secs)


def _cleanup():
    global DRIVER
    if DRIVER is None:
        return
    try:
        for h in DRIVER.window_handles[:]:
            try:
                DRIVER.switch_to.window(h)
                DRIVER.close()
            except Exception:
                pass
        DRIVER.quit()
    except Exception:
        pass
    finally:
        DRIVER = None


atexit.register(_cleanup)
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda s, f: (_cleanup(), sys.exit(1)))

# =======================
# Timing / Throttle
# =======================


def delay(reason=""):
    if THROTTLE <= 0:
        return
    base = (THROTTLE / 100.0) * 10.0
    jitter = RNG.uniform(0.5, 1.5)
    wait_s = base * jitter
    print(f"    [SLEEP] {wait_s:.2f}s {('(' + reason + ')') if reason else ''}")
    time.sleep(wait_s)


# =======================
# Helpers
# =======================

_DATA_INDENT = "      "


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def print_data(label: str, value: str):
    """Print a single-line, width-trimmed [DATA] entry with 6-space indent."""
    cols = 120
    try:
        cols = shutil.get_terminal_size(fallback=(120, 24)).columns
    except Exception:
        pass
    v = _collapse_ws(value)
    line = f"{_DATA_INDENT}[DATA] {label}: {v}"
    if len(line) > cols:
        if cols > 1:
            line = line[: cols - 2] + "…"
        else:
            line = "…"
    print(line)


def ensure_logged_in(driver: webdriver.Chrome, first_page_url: str):
    driver.get(first_page_url)
    delay("after open page 1 (SSO)")
    try:
        wait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "main#skip-to-content"))
        )
        print("[SSO] Already logged in.")
    except Exception:
        print("[SSO] Please log in.")
        while True:
            try:
                wait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "main#skip-to-content")
                    )
                )
                print("[SSO] Login detected. Continuing.")
                break
            except Exception:
                time.sleep(1)


def page_has_error_banner(driver: webdriver.Chrome) -> bool:
    try:
        elems = driver.find_elements(By.XPATH, ERROR_BANNER_XPATH)
        return any(e.is_displayed() for e in elems)
    except Exception:
        return False


def collect_job_links(
    driver: webdriver.Chrome, search_url: str, max_pages: int
) -> list[str]:
    links, seen = [], set()
    page = 1
    while True:
        if max_pages != -1 and page > max_pages:
            break
        url = build_page_url(search_url, page)
        print(f"[PAGE] {page} -> {url}")
        driver.get(url)
        delay("after list page load")

        if page_has_error_banner(driver):
            print(f"[PAGE] Error banner found on page {page}. Stopping pagination.")
            break
        try:
            wait(driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "main#skip-to-content")
                )
            )
        except Exception:
            print("  [WARN] main content not detected quickly; continuing")

        anchors = driver.find_elements(By.CSS_SELECTOR, JOB_LINK_SELECTOR)
        added = 0
        for a in anchors:
            href = a.get_attribute("href")
            if not href:
                continue
            abs_url = strip_url_params(urljoin(origin_of(search_url), href))
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)
                added += 1
        print(f"  [PAGE {page}] added {added}, total unique {len(links)}")
        if added == 0:
            print(f"[PAGE] No new links on page {page}. Stopping.")
            break
        page += 1
    return links


def first_text(driver: webdriver.Chrome, xpath: str) -> str:
    try:
        el = driver.find_element(By.XPATH, xpath)
        return (el.get_attribute("textContent") or el.text or "").strip()
    except Exception:
        return ""


# =======================
# Parsing
# =======================


def months_between_inclusive_full_months(d1: datetime, d2: datetime) -> int:
    base = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        base -= 1
    last_day = calendar.monthrange(d2.year, d2.month)[1]
    if d1.day == 1 and d2.day == last_day:
        base += 1
    return max(base, 0)


def parse_duration(raw: str):
    if not raw:
        return 0, None, None
    if "∙" in raw:
        raw = raw.split("∙", 1)[1]
    raw = raw.strip()
    if raw.lower().startswith("from "):
        raw = raw[5:].strip()
    if " to " not in raw:
        return 0, None, None
    left, right = raw.split(" to ", 1)
    fmt = "%d %B, %Y"
    try:
        d1 = datetime.strptime(left.strip(), fmt)
        d2 = datetime.strptime(right.strip(), fmt)
        months = months_between_inclusive_full_months(d1, d2)
        return months, d1, d2
    except Exception:
        return 0, None, None


# =======================
# Field Extractors
# =======================


def get_title(driver: webdriver.Chrome) -> str:
    return first_text(driver, TITLE_XPATH)


def get_company_from_job_page(driver: webdriver.Chrome):
    name_raw = first_text(driver, COMPANY_NAME_XPATH)
    sector_raw = first_text(driver, COMPANY_SECTOR_XPATH)
    sector = sector_raw if sector_raw and sector_raw.lower() != name_raw.lower() else ""
    return name_raw, sector


def get_location(driver: webdriver.Chrome) -> str:
    loc = first_text(driver, LOCATION_XPATH)
    if loc.startswith("Onsite, based in "):
        loc = loc.replace("Onsite, based in ", "", 1).strip()
    if loc.strip() == "Remote":
        loc = ""
    return loc


def get_duration_and_start(driver: webdriver.Chrome):
    txt = first_text(driver, DURATION_XPATH)
    months, d1, _ = parse_duration(txt)
    months_str = "" if months == 0 else str(months)
    start_str = d1.strftime("%m/%Y") if d1 else ""
    return months_str, start_str


def get_posted_at(driver: webdriver.Chrome) -> str:
    txt = first_text(driver, POSTED_AT_XPATH)
    if "∙" in txt:
        txt = txt.split("∙", 1)[0]
    txt = txt.strip()
    if txt.startswith("Posted"):
        txt = txt[len("Posted") :].lstrip(" :").strip()
    return txt


_HEADCOUNT_RANGE_RE = re.compile(
    r"(?P<lo>\d{1,3}(?:,\d{3})?)\s*-\s*(?P<hi>\d{1,3}(?:,\d{3})?)", re.I
)
_HEADCOUNT_SINGLE_RE = re.compile(r"(?P<num>\d{1,3}(?:,\d{3})?)\s*\+?", re.I)


def normalize_headcount_to_mean(txt: str) -> str:
    if not txt:
        return ""
    m = _HEADCOUNT_RANGE_RE.search(txt)
    if m:
        lo = int(m.group("lo").replace(",", ""))
        hi = int(m.group("hi").replace(",", ""))
        return str((lo + hi) // 2)
    m2 = _HEADCOUNT_SINGLE_RE.search(txt)
    if m2:
        num = int(m2.group("num").replace(",", ""))
        return str(num)
    return ""


def get_company_headcount(driver: webdriver.Chrome) -> str:
    try:
        nodes = driver.find_elements(By.XPATH, COMPANY_HEADCOUNT_XPATH)
        for el in nodes:
            raw = (el.get_attribute("textContent") or el.text or "").strip()
            if not raw:
                continue
            normalized = normalize_headcount_to_mean(raw)
            if normalized:
                return normalized
    except Exception:
        pass
    return ""


def click_more_and_get_description(driver: webdriver.Chrome) -> str:
    try:
        btn = driver.find_element(By.XPATH, MORE_BUTTON_XPATH)
        if btn.is_displayed():
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(1)
    except Exception:
        pass
    return first_text(driver, DESCRIPTION_XPATH)


# =======================
# Main
# =======================


def main():
    global THROTTLE
    args = parse_args()
    THROTTLE = max(0.0, min(100.0, float(args.throttle)))

    search_url = ensure_page_param(args.url)
    base_origin = origin_of(search_url)
    print(f"[CFG] origin: {base_origin}")
    print(f"[CFG] search_url: {search_url}")
    print(f"[CFG] pages: {args.pages} (-1 means unlimited)")
    print(f"[CFG] throttle: {THROTTLE}")

    driver = setup_driver(headless=False)

    try:
        ensure_logged_in(driver, build_page_url(search_url, 1))
        job_links = collect_job_links(
            driver, search_url=search_url, max_pages=args.pages
        )
        print(f"[INFO] Total jobs: {len(job_links)}")

        internal_rows = []
        for i, job_url in enumerate(job_links, 1):
            stripped_url = strip_url_params(job_url)
            print(f"[JOB {i}/{len(job_links)}] {stripped_url}")
            driver.get(job_url)
            delay("after job page load")

            try:
                wait(driver, 25).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "main#skip-to-content")
                    )
                )
            except Exception:
                print("   [WARN] main content not detected quickly")

            title = get_title(driver)
            company_name, company_sector = get_company_from_job_page(driver)
            company_headcount = get_company_headcount(driver)
            location = get_location(driver)
            duration_months, start_str = get_duration_and_start(driver)
            posted_at = get_posted_at(driver)
            description = click_more_and_get_description(driver)

            print_data("Company Name", company_name)
            print_data("Company Sector", company_sector)
            print_data("Company Headcount", company_headcount)
            print_data("Job Title", title)
            print_data("Job PostedAt", posted_at)
            print_data("Job Duration", duration_months)
            print_data("Job Start", start_str)
            print_data("Job Location", location)
            print_data("Job Description", description)
            print_data("Job Link", stripped_url)

            internal_rows.append(
                JobRowInternal(
                    url=stripped_url,
                    title=title,
                    company_name=company_name,
                    company_sector=company_sector,
                    company_headcount=company_headcount,
                    location=location,
                    duration_months=duration_months,
                    posted_at=posted_at,
                    description=description,
                    start=start_str,
                )
            )
            delay("between jobs")

        df = pd.DataFrame([asdict(r) for r in internal_rows])
        if df.empty:
            print("[WARN] No rows scraped. CSV will not be written.")
            return

        df_out = pd.DataFrame(
            {
                "Company Name": df.get("company_name", ""),
                "Company Sector": df.get("company_sector", ""),
                "Company Headcount": df.get("company_headcount", ""),
                "Job Title": df.get("title", ""),
                "Job PostedAt": df.get("posted_at", ""),
                "Job Duration": df.get("duration_months", ""),
                "Job Start": df.get("start", ""),
                "Job Location": df.get("location", ""),
                "Job Description": df.get("description", ""),
                "Job Link": df.get("url", ""),
            }
        )

        out_csv = Path("handshake_jobs.csv")
        df_out.to_csv(out_csv, index=False, encoding="utf-8")
        print(f"[OK] Wrote {out_csv.resolve()}")

    finally:
        _cleanup()


if __name__ == "__main__":
    main()
