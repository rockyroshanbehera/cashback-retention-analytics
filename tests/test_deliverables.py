"""Required deliverables exist, the workbook is sound, and the documents agree with the data."""
from __future__ import annotations

import re

import pytest
from openpyxl import load_workbook

from config import DISCLAIMER
from verify_workbook import (EXCEL_ERRORS, REQUIRED_SHEETS, WORKBOOK_PATH, audit_static)

REQUIRED_FILES = [
    "README.md", "LICENSE", "requirements.txt", ".gitignore",
    "data/README.md",
    "docs/methodology.md", "docs/experiment_design.md", "docs/data_dictionary.md",
    "docs/stakeholder_brief.md", "docs/interview_talking_points.md",
    "outputs/executive_summary.md", "outputs/cashback_retention_dashboard.xlsx",
    "outputs/dashboard_preview.png", "outputs/segment_recommendations.csv",
    "outputs/campaign_performance.csv", "outputs/scenarios.csv",
    "outputs/cohort_retention_matrix.csv", "outputs/forecast.csv",
    "src/generate_data.py", "src/analyze_experiment.py", "src/build_workbook.py",
    "src/verify_workbook.py", "src/run_pipeline.py",
]

DOCS_WITH_DISCLAIMER = [
    "README.md", "outputs/executive_summary.md", "docs/methodology.md",
    "docs/experiment_design.md", "docs/data_dictionary.md", "docs/stakeholder_brief.md",
    "docs/interview_talking_points.md", "data/README.md",
]


@pytest.mark.parametrize("relative", REQUIRED_FILES)
def test_required_deliverable_exists(project_root, relative):
    path = project_root / relative
    assert path.exists(), f"missing deliverable: {relative}"
    assert path.stat().st_size > 0, f"empty deliverable: {relative}"


@pytest.mark.parametrize("relative", DOCS_WITH_DISCLAIMER)
def test_disclaimer_is_present(project_root, relative):
    text = (project_root / relative).read_text(encoding="utf-8")
    assert DISCLAIMER in text, f"{relative} is missing the synthetic-data disclaimer"


def test_deterministic_samples_are_committed(project_root):
    samples = list((project_root / "data" / "processed").glob("*_sample.csv"))
    assert len(samples) >= 6, "expected a committed sample for every table"
    for path in samples:
        assert path.stat().st_size > 0
        assert len(path.read_text(encoding="utf-8").splitlines()) > 1


def test_large_generated_artefacts_are_git_ignored(project_root):
    ignore = (project_root / ".gitignore").read_text(encoding="utf-8")
    for pattern in ["database/*.db", "data/processed/*.csv", "!data/processed/*_sample.csv"]:
        assert pattern in ignore, f".gitignore is missing {pattern}"


def test_requirements_match_actual_imports(project_root):
    """requirements.txt must not claim dependencies the code never imports."""
    listed = {re.split(r"[<>=!]", line)[0].strip().lower()
              for line in (project_root / "requirements.txt").read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.startswith("#")}
    source = "\n".join(p.read_text(encoding="utf-8")
                       for p in (project_root / "src").glob("*.py"))
    source += "\n".join(p.read_text(encoding="utf-8")
                        for p in (project_root / "tests").glob("*.py"))
    for package, module in [("pandas", "pandas"), ("numpy", "numpy"),
                            ("xlsxwriter", "xlsxwriter"), ("openpyxl", "openpyxl"),
                            ("pillow", "PIL")]:
        assert package in listed, f"{module} is imported but not declared in requirements.txt"
        assert re.search(rf"^\s*(import|from)\s+{module}\b", source, re.M), \
            f"{package} is declared but never imported"
    for absent in ("scipy", "statsmodels", "matplotlib", "seaborn"):
        assert absent not in listed, f"{absent} is declared but the code does not use it"


def test_workbook_static_audit_is_clean():
    report = audit_static(WORKBOOK_PATH)
    assert not report["problems"], report["problems"]


def test_workbook_has_every_required_sheet_in_order():
    wb = load_workbook(WORKBOOK_PATH)
    try:
        assert wb.sheetnames == REQUIRED_SHEETS, f"sheet order is {wb.sheetnames}"
    finally:
        wb.close()


def test_workbook_sheets_are_populated():
    report = audit_static(WORKBOOK_PATH)
    for name, info in report["sheets"].items():
        assert info["non_empty_cells"] > 20, f"{name} has only {info['non_empty_cells']} cells"


def test_workbook_has_no_excel_error_strings():
    report = audit_static(WORKBOOK_PATH)
    for name, info in report["sheets"].items():
        assert not info["excel_errors"], f"{name}: {info['excel_errors']}"


def test_simulator_and_kpi_sheets_are_formula_driven():
    report = audit_static(WORKBOOK_PATH)
    assert report["sheets"]["Offer Simulator"]["formula_cells"] >= 10
    assert report["sheets"]["KPI Calculations"]["formula_cells"] >= 20


def test_presentation_sheets_hide_gridlines_and_freeze_panes():
    report = audit_static(WORKBOOK_PATH)
    for name in ["Executive Dashboard", "Segment Analysis", "Cohort Retention", "Forecast",
                 "Offer Simulator", "KPI Calculations"]:
        assert report["sheets"][name]["gridlines_hidden"], f"{name} still shows gridlines"
        assert report["sheets"][name]["freeze_panes"], f"{name} has no frozen panes"


def test_dashboard_has_charts_and_a_heatmap():
    report = audit_static(WORKBOOK_PATH)
    assert report["sheets"]["Executive Dashboard"]["charts"] >= 3
    assert report["sheets"]["Executive Dashboard"]["conditional_formats"] >= 1
    assert report["sheets"]["Cohort Retention"]["conditional_formats"] >= 1


def test_excel_recalculation_report_is_clean(project_root):
    """The Excel COM pass must have run and found no evaluated errors."""
    import json
    path = project_root / "outputs" / "workbook_verification.json"
    assert path.exists(), "run `python src/verify_workbook.py` to produce the verification report"
    report = json.loads(path.read_text(encoding="utf-8"))
    if not report["excel"]["available"]:
        pytest.skip(report["excel"]["reason"])
    assert report["passed"], report["problems"]
    for sheet in ("Offer Simulator", "KPI Calculations"):
        evaluated = report["excel"]["evaluated"][sheet]
        assert evaluated, f"{sheet} produced no evaluated formulas"
        for addr, info in evaluated.items():
            value = str(info["value"])
            assert value.strip(), f"{sheet}!{addr} evaluated to an empty cell"
            assert not any(e in value for e in EXCEL_ERRORS), f"{sheet}!{addr} -> {value}"


def test_dashboard_preview_is_a_real_image(project_root):
    from PIL import Image
    path = project_root / "outputs" / "dashboard_preview.png"
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.width > 800 and image.height > 600, f"preview is only {image.size}"


def test_executive_summary_numbers_come_from_the_final_run(project_root, segment_results,
                                                           forecast_summary, metadata):
    text = (project_root / "outputs" / "executive_summary.md").read_text(encoding="utf-8")
    assert forecast_summary["selected_model"] in text
    assert f"{metadata['customers']:,}" in text or str(metadata["customers"]) in text
    assert f"{forecast_summary['mae']:.1f}" in text
    scale = segment_results[segment_results.action.eq("Scale")]
    for segment in scale.segment:
        assert segment in text, f"{segment} is a Scale segment but is absent from the summary"


def test_stakeholder_brief_recommendation_table_matches_results(project_root, segment_results):
    text = (project_root / "docs" / "stakeholder_brief.md").read_text(encoding="utf-8")
    for row in segment_results.itertuples(index=False):
        assert row.segment in text, f"{row.segment} missing from the recommendation table"
        assert row.action in text
    # Percentages must be rendered, not raw floats.
    assert not re.search(r"\|\s*\d+\.\d{6,}\s*\|", text), "unformatted float in the table"


def test_readme_covers_the_required_sections(project_root):
    text = (project_root / "README.md").read_text(encoding="utf-8")
    for heading in ["Business problem", "Experiment design", "KPI definitions", "RFM",
                    "Forecast", "Dashboard", "Reproduc", "SQL", "Repository structure",
                    "Limitations", "PhonePe Graduate Trainee"]:
        assert heading.lower() in text.lower(), f"README is missing a section about: {heading}"
    assert "dashboard_preview.png" in text, "README must embed the dashboard preview"


def test_readme_headline_numbers_match_the_final_run(project_root, segment_results, metadata,
                                                     forecast_summary, experiment_notes):
    """The README is hand-written, so pin its quoted figures to the pipeline outputs."""
    text = (project_root / "README.md").read_text(encoding="utf-8")
    scale = segment_results[segment_results.action.eq("Scale")]
    expected = {
        "customer count": f"{metadata['customers']:,}",
        "transaction count": f"{metadata['transactions']:,}",
        "successful transactions": f"{metadata['successful_transactions']:,}",
        "assignments": f"{metadata['campaign_assignments']:,}",
        "redemptions": f"{metadata['redemptions']:,}",
        "rfm rows": f"{metadata['rfm_snapshot_rows']:,}",
        "total cashback cost": f"{segment_results.cashback_cost.sum():,.0f}",
        "scale cashback cost": f"{scale.cashback_cost.sum():,.0f}",
        "blanket roi": f"{segment_results.incremental_profit.sum() / segment_results.cashback_cost.sum():.1%}",
        "focused roi": f"{scale.incremental_profit.sum() / scale.cashback_cost.sum():.1%}",
        "selected model": forecast_summary["selected_model"],
        "holdout mae": f"{forecast_summary['mae']:.2f}",
        "holdout window start": forecast_summary["holdout_start"],
        "holdout window end": forecast_summary["holdout_end"],
        "txns per retained": f"{experiment_notes['assumptions']['txns_per_incremental_retained']:.2f}",
    }
    missing = {label: value for label, value in expected.items() if value not in text}
    assert not missing, f"README quotes stale numbers, expected to find: {missing}"

    # Every segment, its action and its rounded ROI must appear in the recommendation table.
    for row in segment_results.itertuples(index=False):
        assert row.segment in text
        assert f"{row.roi:.1%}" in text, f"README is missing {row.segment} ROI {row.roi:.1%}"


def test_readme_states_the_scale_recommendation(project_root, segment_results):
    text = (project_root / "README.md").read_text(encoding="utf-8")
    recommendation = text.split("**Recommendation:**")[1].split("\n\n")[0]
    for segment in segment_results[segment_results.action.eq("Scale")].segment:
        assert segment in recommendation, f"{segment} is a Scale segment but is not recommended"
    for segment in segment_results[segment_results.action.eq("Do not target")].segment:
        assert segment in recommendation, f"{segment} should be named as stopped"


def test_interview_material_is_complete(project_root):
    text = (project_root / "docs" / "interview_talking_points.md").read_text(encoding="utf-8")
    star = re.search(r"## Five STAR stories(.+?)^## ", text, re.S | re.M)
    assert star, "STAR section missing"
    assert len(re.findall(r"^\d+\. \*\*", star.group(1), re.M)) == 5, "expected five STAR stories"
    questions = re.search(r"## Five likely questions.*?\n(.+?)^## ", text, re.S | re.M)
    assert questions and len(re.findall(r"^\d+\. \*\*", questions.group(1), re.M)) == 5
    bullets = re.search(r"## Two resume bullets(.+?)^## ", text, re.S | re.M)
    assert bullets and len(re.findall(r"^- ", bullets.group(1), re.M)) == 2
    assert "## 60-second explanation" in text
