"""
src/extract/download_bts.py

Downloads On-Time Performance data from the BTS (Bureau of Transportation
Statistics). BTS provides pre-built CSV files — no scraping required.

Download URL pattern:
  https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YEAR}_{MONTH}.zip

Usage:
    python src/extract/download_bts.py --year 2023 --month 1
    python src/extract/download_bts.py --year 2023 --months 1-12
    python src/extract/download_bts.py --year 2023 --all-months
"""

import click
import requests
import zipfile
import time
import hashlib
from pathlib import Path
from loguru import logger
from tqdm import tqdm

from config.settings import PathConfig, PipelineConfig

# BTS direct download URL — no authentication needed
BTS_BASE_URL = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)

# If BTS zip is unavailable, use this mirror (Kaggle also hosts this dataset)
# https://www.kaggle.com/datasets/yuanyuwendymu/airline-delay-and-cancellation-data-2009-2018


def get_download_url(year: int, month: int) -> str:
    return BTS_BASE_URL.format(year=year, month=month)


def download_file(url: str, dest_path: Path, chunk_size: int = 8192) -> bool:
    """
    Stream-download a file with a progress bar.
    Returns True on success, False on failure.
    """
    try:
        logger.info(f"Downloading: {url}")
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))

        with open(dest_path, "wb") as f, tqdm(
            desc=dest_path.name,
            total=total_size,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for chunk in response.iter_content(chunk_size=chunk_size):
                size = f.write(chunk)
                bar.update(size)

        logger.success(f"Downloaded: {dest_path} ({dest_path.stat().st_size / 1e6:.1f} MB)")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Download failed for {url}: {e}")
        if dest_path.exists():
            dest_path.unlink()  # Remove partial download
        return False


def extract_zip(zip_path: Path, extract_to: Path) -> list[Path]:
    """
    Extract zip and return list of CSV file paths.
    BTS zips contain exactly one CSV file each.
    """
    extract_to.mkdir(parents=True, exist_ok=True)
    csv_files = []

    with zipfile.ZipFile(zip_path, "r") as z:
        for name in z.namelist():
            if name.endswith(".csv"):
                z.extract(name, extract_to)
                csv_path = extract_to / name
                csv_files.append(csv_path)
                logger.info(f"Extracted: {csv_path.name}")

    return csv_files


def compute_checksum(file_path: Path) -> str:
    """MD5 checksum for file integrity verification."""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def download_month(year: int, month: int, force: bool = False) -> Path | None:
    """
    Download and extract BTS data for a single year/month.
    Returns path to the extracted CSV, or None on failure.
    """
    PathConfig.ensure_dirs()
    raw_dir = PathConfig.RAW_DATA_DIR / str(year)
    raw_dir.mkdir(parents=True, exist_ok=True)

    csv_filename = f"flights_{year}_{month:02d}.csv"
    csv_path = raw_dir / csv_filename

    # Skip if already downloaded
    if csv_path.exists() and not force:
        logger.info(f"Already exists, skipping: {csv_path}")
        return csv_path

    zip_filename = f"bts_{year}_{month:02d}.zip"
    zip_path = raw_dir / zip_filename
    url = get_download_url(year, month)

    # Download zip
    success = download_file(url, zip_path)
    if not success:
        return None

    # Extract CSV from zip
    csv_files = extract_zip(zip_path, raw_dir)
    if not csv_files:
        logger.error(f"No CSV files found in zip: {zip_path}")
        return None

    # Rename to consistent filename (replace() works on Windows even if dest exists)
    extracted_csv = csv_files[0]
    extracted_csv.replace(csv_path)

    # Clean up zip file
    zip_path.unlink()

    checksum = compute_checksum(csv_path)
    logger.info(f"File checksum (MD5): {checksum}")

    return csv_path


# ─────────────────────────────────────────
# CLI Interface
# ─────────────────────────────────────────

@click.command()
@click.option("--year",  required=True,  type=int, help="Year to download (e.g. 2023)")
@click.option("--month", default=None,   type=int, help="Single month (1-12)")
@click.option("--months", default=None,  type=str, help="Month range, e.g. '1-12' or '1,3,6'")
@click.option("--all-months", is_flag=True, help="Download all 12 months")
@click.option("--force", is_flag=True,   help="Re-download even if file exists")
def main(year, month, months, all_months, force):
    """Download BTS On-Time Performance data."""

    logger.add(
        PathConfig.LOG_DIR / "download_{time}.log",
        rotation="50 MB",
        level=PipelineConfig.LOG_LEVEL,
    )

    # Determine which months to download
    if all_months:
        month_list = list(range(1, 13))
    elif months:
        if "-" in months:
            start, end = months.split("-")
            month_list = list(range(int(start), int(end) + 1))
        else:
            month_list = [int(m) for m in months.split(",")]
    elif month:
        month_list = [month]
    else:
        raise click.UsageError("Specify --month, --months, or --all-months")

    logger.info(f"Downloading {len(month_list)} month(s) for year {year}")
    results = {"success": [], "failed": []}

    for m in month_list:
        csv_path = download_month(year, m, force=force)
        if csv_path:
            results["success"].append(f"{year}-{m:02d}")
        else:
            results["failed"].append(f"{year}-{m:02d}")

        # Be polite to BTS servers — don't hammer them
        if len(month_list) > 1:
            time.sleep(2)

    logger.info(f"Done. Success: {results['success']}, Failed: {results['failed']}")
    if results["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
