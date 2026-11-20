"""Central, environment-free configuration for the synthetic analytics pipeline.

Every path is derived from this file's location so the repository runs unchanged
from any clone directory (no machine-specific absolute paths anywhere in source).
"""
from pathlib import Path

SEED = 20260813
N_CUSTOMERS = 40_000
START_DATE = "2025-01-01"
END_DATE = "2025-12-31"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "processed"
DB_DIR = PROJECT_ROOT / "database"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DOCS_DIR = PROJECT_ROOT / "docs"

# Assumed synthetic gross contribution earned per rupee of payment value. This is a
# stated planning assumption, not a measured PhonePe figure.
CONTRIBUTION_MARGIN_RATE = 0.08

# Retention measurement windows, in days after campaign start (day 0 inclusive).
D7_WINDOW_DAYS = 7
D30_WINDOW_DAYS = 30

# Days of the daily transaction series held out of forecast training.
FORECAST_HOLDOUT_DAYS = 30

DISCLAIMER = ("Independent portfolio project using synthetic data. "
              "Not affiliated with or based on internal data from PhonePe.")
