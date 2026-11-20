"""Shared fixtures. Loads the generated artefacts once per test session.

The suite runs against the artefacts the pipeline actually produced, so it fails if the
committed documentation, workbook and outputs drift away from the data.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))

DATA_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DB_PATH = PROJECT_ROOT / "database" / "cashback_analytics.db"

REQUIRES_PIPELINE = "run `python src/run_pipeline.py` first"


def _csv(name: str, **kwargs) -> pd.DataFrame:
    path = DATA_DIR / f"{name}.csv"
    if not path.exists():
        pytest.skip(f"{path.name} missing - {REQUIRES_PIPELINE}")
    return pd.read_csv(path, **kwargs)


def _out(name: str, **kwargs) -> pd.DataFrame:
    path = OUTPUT_DIR / name
    if not path.exists():
        pytest.skip(f"{path.name} missing - {REQUIRES_PIPELINE}")
    return pd.read_csv(path, **kwargs)


def _json(name: str) -> dict:
    path = OUTPUT_DIR / name
    if not path.exists():
        pytest.skip(f"{path.name} missing - {REQUIRES_PIPELINE}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def customers() -> pd.DataFrame:
    return _csv("customers", parse_dates=["signup_date"])


@pytest.fixture(scope="session")
def transactions() -> pd.DataFrame:
    return _csv("transactions", parse_dates=["transaction_date"])


@pytest.fixture(scope="session")
def campaigns() -> pd.DataFrame:
    return _csv("campaigns", parse_dates=["start_date", "end_date"])


@pytest.fixture(scope="session")
def assignments() -> pd.DataFrame:
    return _csv("campaign_assignments", parse_dates=["assignment_date"])


@pytest.fixture(scope="session")
def redemptions() -> pd.DataFrame:
    return _csv("cashback_redemptions", parse_dates=["redemption_date"])


@pytest.fixture(scope="session")
def rfm() -> pd.DataFrame:
    return _csv("rfm_snapshots", parse_dates=["signup_date", "last_txn"])


@pytest.fixture(scope="session")
def segment_results() -> pd.DataFrame:
    return _out("segment_recommendations.csv")


@pytest.fixture(scope="session")
def campaign_results() -> pd.DataFrame:
    return _out("campaign_performance.csv")


@pytest.fixture(scope="session")
def cohort() -> pd.DataFrame:
    return _out("cohort_retention.csv", parse_dates=["cohort_month"])


@pytest.fixture(scope="session")
def scenarios() -> pd.DataFrame:
    return _out("scenarios.csv")


@pytest.fixture(scope="session")
def metadata() -> dict:
    return _json("generation_metadata.json")


@pytest.fixture(scope="session")
def forecast_summary() -> dict:
    return _json("forecast_summary.json")


@pytest.fixture(scope="session")
def experiment_notes() -> dict:
    return _json("experiment_notes.json")


@pytest.fixture(scope="session")
def quality_report() -> dict:
    return _json("data_quality_report.json")


@pytest.fixture(scope="session")
def db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        pytest.skip(f"{DB_PATH.name} missing - {REQUIRES_PIPELINE}")
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()
