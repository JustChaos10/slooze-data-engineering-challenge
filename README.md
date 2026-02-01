# Slooze Data Engineering Challenge – IndiaMART

Part A: Scraper for IndiaMART (Industrial Machinery + Electronics).  
Part B: EDA on scraped listings (pandas + seaborn).

## Setup (Python 3)

```bash
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
python -m playwright install
```

If `python -m playwright install` is slow, you can install only Chromium:

```bash
python -m playwright install chromium
```

**If venv fails under OneDrive** (e.g. "Unable to copy venvlauncher.exe"): create the venv outside the synced folder, then run commands from the project folder:

```bash
# Example: venv in a local folder
python -m venv %USERPROFILE%\venvs\slooze-project
%USERPROFILE%\venvs\slooze-project\Scripts\activate
cd C:\Users\siraj\OneDrive\Desktop\Project
pip install -r requirements.txt
python -m playwright install
python scraper.py
```

## Run

**Important:** Run the scraper in a **normal PowerShell or Command Prompt** (not only inside the IDE). Playwright launches a browser; some environments block this and show "Access is denied"—use a regular terminal.

1. **Scrape** (saves `output/listings.csv`):

```bash
python scraper.py
```

Optional: cap total listings or pages (e.g. for testing):

```bash
python scraper.py --max-listings 20
python scraper.py --max-pages 1
```

2. **EDA** (Jupyter):

```bash
jupyter notebook eda.ipynb
```

Recommended: run EDA as a script (saves charts to `output/eda/`):

```bash
python eda.py
```

The notebook (`eda.ipynb`) is optional for interactive exploration; it loads `output/listings.csv`, shows summary stats, plots, and an insights section.

## Project layout

- `scraper.py` – Playwright + BeautifulSoup; scrapes IndiaMART category pages.
- `eda.py` – Reproducible EDA script (stats + charts saved to `output/eda/`).
- `eda.ipynb` – Optional notebook version for exploration.
- `output/listings.csv` – Scraped data (created by `scraper.py`).
- `requirements.txt` – Python dependencies.

## Notes

- Scraper uses a 2.5s delay between categories to avoid rate limits.
- Listings are deduplicated by product URL before saving.

## Submission notes

- `.gitignore` excludes `venv/` so you don’t accidentally commit it.
