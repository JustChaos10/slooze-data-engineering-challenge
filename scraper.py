"""
IndiaMART scraper – Industrial Machinery & Electronics.
Uses Playwright + BeautifulSoup. Saves listings to output/listings.csv.
Supports --max-listings, --max-pages, retries with backoff, and clearer error reporting.
"""
import argparse
import csv
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Category URLs (Industrial Machinery, Electronics)
BASE_URL = "https://dir.indiamart.com"
CATEGORY_URLS = [
    ("Industrial Machinery", f"{BASE_URL}/impcat/industrial-machinery.html"),
    ("Electronics", f"{BASE_URL}/impcat/electronic-gadgets.html"),
]
DELAY_SECONDS = 2.5
MAX_RETRIES = 4
RETRY_BACKOFF_BASE = 2
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_CSV = OUTPUT_DIR / "listings.csv"


def normalize_any_url(href, base_url):
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    return urljoin(base_url, href)


def normalize_indiamart_url(href, page_url=None):
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//") or href.startswith("http"):
        return normalize_any_url(href, "https://www.indiamart.com/")

    # IndiaMART has two common surfaces:
    # - Category pages: https://dir.indiamart.com/impcat/...
    # - Product/supplier pages: https://www.indiamart.com/proddetail/... and https://www.indiamart.com/company/...
    if href.startswith("/impcat/") or href.startswith("impcat/"):
        return normalize_any_url(href, "https://dir.indiamart.com/")
    if href.startswith("/proddetail/") or href.startswith("proddetail/"):
        return normalize_any_url(href, "https://www.indiamart.com/")
    if href.startswith("/company/") or href.startswith("company/"):
        return normalize_any_url(href, "https://www.indiamart.com/")

    if href.startswith("/"):
        return normalize_any_url(href, "https://www.indiamart.com/")

    if page_url:
        return normalize_any_url(href, page_url)

    return normalize_any_url(href, "https://www.indiamart.com/")


def looks_like_supplier_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    host = (parsed.netloc or "").lower()
    if not host.endswith("indiamart.com"):
        return False

    path = (parsed.path or "").strip("/").lower()
    if not path:
        return False

    first = path.split("/", 1)[0]
    if first in {"proddetail", "impcat", "search"}:
        return False

    if first == "company":
        return True

    return len(path.split("/")) == 1


def extract_price(text):
    """Extract price string (e.g. '₹ 60,000') from block of text."""
    if not text:
        return ""
    match = re.search(r"₹\s*[\d,]+(?:\s*/\s*\w+)?|Rs\.?\s*[\d,]+", text, re.IGNORECASE)
    if not match:
        return ""
    s = match.group(0).strip()
    return s.split("\n")[0].strip() if s else ""


def extract_location(text):
    """Heuristic: first line after 'Contact Supplier' often has city + address."""
    if not text or "Contact Supplier" not in text:
        return ""
    parts = text.split("Contact Supplier", 1)
    if len(parts) < 2:
        return ""
    after = parts[1].strip()
    lines = [l.strip() for l in after.split("\n") if l.strip()]
    return lines[0] if lines else ""


def goto_with_retries(page, url):
    for attempt in range(MAX_RETRIES):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)  # allow JS to render listings
            return
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"  Retry in {wait}s after: {type(e).__name__}: {e}")
                time.sleep(wait)
            else:
                raise


def find_next_page_url(soup, current_url):
    next_link = soup.find("a", attrs={"rel": lambda v: v and ("next" in v if isinstance(v, list) else "next" in str(v).lower())})
    if next_link and next_link.get("href"):
        nxt = next_link.get("href")
        if isinstance(nxt, str) and nxt.strip():
            return normalize_any_url(nxt, current_url)

    for a in soup.find_all("a", href=True):
        text = (a.get_text(" ", strip=True) or "").strip().lower()
        if text in {"next", "next >", "next »", "›", "»", ">"} or text.startswith("next"):
            candidate = normalize_any_url(a.get("href", ""), current_url)
            if candidate and candidate != current_url:
                return candidate

    return None


def scrape_category(page, category_name, url, max_listings=None, max_pages=1):
    """Scrape up to max_pages of a category; return list of dicts (title, price, supplier, location, category, url)."""
    rows = []
    proddetail_re = re.compile(r"indiamart\.com/proddetail/")
    seen_pages = set()
    current_url = url

    for _page_idx in range(max_pages):
        if not current_url or current_url in seen_pages:
            break
        seen_pages.add(current_url)

        goto_with_retries(page, current_url)
        soup = BeautifulSoup(page.content(), "html.parser")

        for a in soup.find_all("a", href=proddetail_re):
            href = normalize_indiamart_url(a.get("href", ""), page_url=current_url)
            title = (a.get_text(strip=True) or "").strip()
            if not title or len(title) < 3:
                continue

            # Find the smallest parent that contains only this product link (one listing card)
            card = None
            parent = a.parent
            for _ in range(15):
                if parent is None or parent.name == "body":
                    break
                proddetail_links = parent.find_all("a", href=proddetail_re)
                if len(proddetail_links) == 1 and proddetail_links[0] is a:
                    card = parent
                parent = parent.parent

            # If no single-link card, use first parent that has price (fallback)
            if card is None:
                parent = a.parent
                for _ in range(15):
                    if parent is None or parent.name == "body":
                        break
                    block_text = parent.get_text(separator="\n", strip=True)
                    if "₹" in block_text or "Rs" in block_text:
                        card = parent
                        break
                    parent = parent.parent

            price = ""
            location = ""
            supplier = ""
            if card is not None:
                block_text = card.get_text(separator="\n", strip=True)
                price = extract_price(block_text)
                location = extract_location(block_text)
                for supplier_link in card.find_all("a", href=True):
                    supplier_href = normalize_indiamart_url(supplier_link.get("href", ""), page_url=current_url)
                    if not supplier_href or supplier_href == href:
                        continue
                    if "/proddetail/" in supplier_href:
                        continue
                    if not looks_like_supplier_url(supplier_href):
                        continue
                    supplier_text = (supplier_link.get_text(strip=True) or "").strip()
                    if not supplier_text or supplier_text == title:
                        continue
                    supplier = supplier_text[:200]
                    break

            rows.append({
                "title": title[:500],
                "price": price,
                "supplier": supplier,
                "location": location[:300] if location else "",
                "category": category_name,
                "url": href,
            })
            if max_listings is not None and len(rows) >= max_listings:
                return rows

        current_url = find_next_page_url(soup, current_url)

    return rows


def main():
    parser = argparse.ArgumentParser(description="Scrape IndiaMART category listings to CSV.")
    parser.add_argument(
        "--max-listings",
        type=int,
        default=None,
        help="Stop after collecting this many listings (across all categories).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Max category pages to scrape per category (best-effort via a Next link).",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = []
    scraped_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    remaining = args.max_listings

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for category_name, url in CATEGORY_URLS:
            if remaining is not None and remaining <= 0:
                break
            print(f"Scraping: {category_name} — {url}")
            try:
                cap = remaining if remaining is not None else None
                rows = scrape_category(page, category_name, url, max_listings=cap, max_pages=args.max_pages)
                for r in rows:
                    r["scraped_at"] = scraped_at
                    all_rows.append(r)
                if remaining is not None:
                    remaining -= len(rows)
                print(f"  -> {len(rows)} listings")
            except Exception as e:
                print(f"  -> Error: {type(e).__name__}: {e}")
                traceback.print_exc()
                sys.exit(1)
            time.sleep(DELAY_SECONDS)

        browser.close()

    # Deduplicate by url (same product may appear in multiple blocks)
    seen = set()
    unique = []
    for r in all_rows:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    fieldnames = ["title", "price", "supplier", "location", "category", "url", "scraped_at"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(unique)

    print(f"Saved {len(unique)} listings to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
