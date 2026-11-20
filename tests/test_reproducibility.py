"""The generator must be deterministic and must not depend on the machine it runs on."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

import generate_data
from config import SEED

TEXT_SUFFIXES = {".py", ".md", ".sql", ".txt", ".json", ".yml", ".yaml", ".cfg", ".ini", ".gitignore"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "data", "database", "outputs"}

# Absolute Windows/Unix user paths that must never be committed in source or docs.
MACHINE_PATH = re.compile(r"[A-Za-z]:\\Users\\|/home/[a-z]|/Users/[A-Za-z]")
SECRET = re.compile(
    r"(?i)(api[_-]?key|secret[_-]?key|password|passwd|access[_-]?token|private[_-]?key)\s*[=:]\s*"
    r"['\"][^'\"]{8,}['\"]")


def _project_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name in SKIP_DIRS or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def test_generation_is_deterministic():
    """Two in-memory generations from the same seed must be identical."""
    first = generate_data.generate_all(write=False)
    second = generate_data.generate_all(write=False)
    names = ["customers", "transactions", "campaigns", "assignments", "redemptions", "rfm"]
    for name, a, b in zip(names, first, second):
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True),
                                      obj=f"{name} differs between identical runs")


def test_regeneration_matches_committed_outputs(customers, transactions, metadata):
    """A fresh generation must reproduce the artefacts the documentation was built from."""
    gen_customers, gen_tx, *_ = generate_data.generate_all(write=False)
    assert len(gen_customers) == len(customers)
    assert len(gen_tx) == len(transactions) == metadata["transactions"]
    assert gen_tx.transaction_status.eq("Success").sum() == metadata["successful_transactions"]
    assert metadata["seed"] == SEED


def test_no_machine_specific_paths(project_root):
    offenders = []
    for path in _project_text_files(project_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if MACHINE_PATH.search(line):
                offenders.append(f"{path.relative_to(project_root)}:{line_no}")
    assert not offenders, f"machine-specific paths committed: {offenders}"


def test_no_hardcoded_secrets(project_root):
    offenders = []
    for path in _project_text_files(project_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if SECRET.search(line):
                offenders.append(f"{path.relative_to(project_root)}:{line_no}")
    assert not offenders, f"possible secrets committed: {offenders}"


# Files that search for these markers necessarily contain them, so they are exempt from
# the scans below. Everything else in the repository is checked.
SCANNER_FILES = {"test_reproducibility.py", "verify_workbook.py"}

# Built from escapes so the literals never appear in this file and trip its own scan.
MOJIBAKE = [b.decode("utf-8") for b in (
    b"\xc3\xa2\xe2\x82\xac",          # latin-1 round trip of an en dash / smart quote lead-in
    b"\xc3\x83\xe2\x80\x94",          # latin-1 round trip of a multiplication sign
    b"\xc3\xa2\xe2\x80\x9a\xc2\xac",  # latin-1 round trip of a currency symbol
    b"\xef\xbb\xbf",                  # UTF-8 BOM appearing mid-document
)]
REPLACEMENT_CHAR = b"\xef\xbf\xbd".decode("utf-8")


def test_no_mojibake_in_text_files(project_root):
    """Catch UTF-8 that was written through a latin-1 round trip."""
    offenders = []
    for path in _project_text_files(project_root):
        if path.name in SCANNER_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for seq in MOJIBAKE:
            if seq in text:
                offenders.append(f"{path.relative_to(project_root)} contains mojibake {seq!r}")
        if REPLACEMENT_CHAR in text:
            offenders.append(f"{path.relative_to(project_root)} contains a replacement character")
    assert not offenders, offenders


def test_rupee_symbol_survives_a_round_trip(project_root):
    """Documents quote rupee amounts; the symbol must be readable as UTF-8."""
    checked = 0
    for name in ["docs/stakeholder_brief.md", "outputs/executive_summary.md"]:
        text = (project_root / name).read_text(encoding="utf-8")
        assert "₹" in text, f"{name} lost its rupee symbols"
        assert REPLACEMENT_CHAR not in text
        checked += 1
    assert checked == 2


def test_no_todo_placeholders(project_root):
    offenders = []
    for path in _project_text_files(project_root):
        if path.name in SCANNER_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if re.search(r"\b(TODO|FIXME|XXX|PLACEHOLDER|TBD)\b", line):
                offenders.append(f"{path.relative_to(project_root)}:{line_no}")
    assert not offenders, f"placeholder markers left in the repository: {offenders}"


@pytest.mark.parametrize("module", ["config", "generate_data", "validate_data", "build_segments",
                                    "analyze_experiment", "build_cohorts", "build_forecast",
                                    "write_docs", "build_workbook", "verify_workbook",
                                    "run_pipeline"])
def test_source_modules_import_cleanly(module):
    """A fresh clone must be able to import every module without side effects."""
    __import__(module)
