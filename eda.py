import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def parse_price_numeric(value):
    if pd.isna(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("₹", "").replace("\\u20b9", "").replace("Rs.", "").replace("Rs", "")
    m = re.search(r"(\d[\d,]*\.?\d*)", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "").strip())
    except ValueError:
        return None


def city_from_location(value):
    if pd.isna(value):
        return ""
    s = str(value).strip()
    if not s:
        return ""
    first = re.split(r"[,\s]+", s, maxsplit=1)[0]
    return first.strip()


def tokenize_title(value):
    if pd.isna(value):
        return []
    return re.findall(r"[a-zA-Z0-9]{3,}", str(value).lower())


def missing_mask(series):
    if series.dtype == "O":
        return series.isna() | (series.astype(str).str.strip() == "")
    return series.isna()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="EDA for IndiaMART scraped listings.")
    parser.add_argument("--input", default="output/listings.csv", help="Input CSV path.")
    parser.add_argument("--outdir", default="output/eda", help="Directory to save plots.")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}. Run scraper.py first.")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_path)
    print("rows", len(df))
    print("columns", list(df.columns))
    if "category" in df.columns:
        print("by_category", df["category"].value_counts().to_dict())

    df["price_numeric"] = df["price"].apply(parse_price_numeric) if "price" in df.columns else None
    price_valid = df["price_numeric"].dropna() if "price_numeric" in df.columns else pd.Series([], dtype=float)

    print("\n=== Missingness (NaN + empty strings) ===")
    missing = {col: int(missing_mask(df[col]).sum()) for col in df.columns}
    missing_pct = {col: round(100 * missing[col] / len(df), 1) for col in df.columns}
    missing_df = pd.DataFrame({"missing": missing, "pct": missing_pct}).sort_values("missing", ascending=False)
    print(missing_df.to_string())

    if "category" in df.columns:
        print("\n=== Missingness by category (NaN + empty strings) ===")
        for col in [c for c in ["price", "supplier", "location"] if c in df.columns]:
            by_cat = df.groupby("category").apply(lambda g: int(missing_mask(g[col]).sum()))
            print(col, by_cat.to_dict())

    sns.set_theme(style="whitegrid")

    if "category" in df.columns:
        plt.figure(figsize=(7, 4))
        df["category"].value_counts().plot(kind="bar", color="steelblue")
        plt.title("Listings by Category")
        plt.ylabel("Count")
        plt.tight_layout()
        plt.savefig(outdir / "listings_by_category.png", dpi=200)
        plt.close()

    if len(price_valid) > 0:
        capped = price_valid.clip(upper=price_valid.quantile(0.95))
        plt.figure(figsize=(7, 4))
        capped.hist(bins=30, color="steelblue", edgecolor="white")
        plt.title("Price Distribution (capped at 95th percentile)")
        plt.xlabel("Price (INR)")
        plt.tight_layout()
        plt.savefig(outdir / "price_distribution.png", dpi=200)
        plt.close()

        q1, q3 = price_valid.quantile(0.25), price_valid.quantile(0.75)
        iqr = q3 - q1
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = price_valid[(price_valid < low) | (price_valid > high)]
        print("\n=== Price outliers (IQR) ===")
        print(f"bounds [{low:.0f}, {high:.0f}] outlier_count {len(outliers)}")
        if len(outliers) > 0:
            print("sample_outlier_prices", outliers.head(5).tolist())

    if "location" in df.columns:
        df["city"] = df["location"].apply(city_from_location)
        city_counts = df[df["city"] != ""]["city"].value_counts().head(15)
        if len(city_counts) > 0:
            plt.figure(figsize=(8, 5))
            city_counts.sort_values().plot(kind="barh", color="teal", alpha=0.85)
            plt.title("Top cities by listing count")
            plt.xlabel("Count")
            plt.tight_layout()
            plt.savefig(outdir / "top_cities.png", dpi=200)
            plt.close()

    if "title" in df.columns:
        stop = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "machine",
            "machinery",
            "electronic",
            "electronics",
            "gadget",
            "gadgets",
        }
        words = []
        for title in df["title"]:
            words.extend(w for w in tokenize_title(title) if w not in stop)
        top_keywords = Counter(words).most_common(15)
        if top_keywords:
            kw_df = pd.DataFrame(top_keywords, columns=["keyword", "count"])
            plt.figure(figsize=(8, 5))
            kw_df.sort_values("count").set_index("keyword")["count"].plot(kind="barh", color="steelblue", alpha=0.85)
            plt.title("Frequent keywords in product titles (top 15)")
            plt.xlabel("Count")
            plt.tight_layout()
            plt.savefig(outdir / "top_keywords.png", dpi=200)
            plt.close()
            print("\n=== Top keywords ===")
            print([w for w, _ in top_keywords[:10]])

    if "supplier" in df.columns:
        supplier_counts = df[df["supplier"].notna() & (df["supplier"].astype(str).str.strip() != "")]["supplier"].value_counts()
        if len(supplier_counts) > 0:
            top10 = supplier_counts.head(10)
            plt.figure(figsize=(8, 4))
            top10.sort_values().plot(kind="barh", color="teal", alpha=0.85)
            plt.title("Top 10 suppliers by listing count")
            plt.xlabel("Count")
            plt.tight_layout()
            plt.savefig(outdir / "top_suppliers.png", dpi=200)
            plt.close()

            top5 = supplier_counts.head(5).sum()
            total = supplier_counts.sum()
            pct_top5 = 100 * top5 / total if total else 0
            print("\n=== Supplier concentration ===")
            print(f"top5_pct {pct_top5:.1f}")

    print(f"\nSaved plots to {outdir}")


if __name__ == "__main__":
    main()

