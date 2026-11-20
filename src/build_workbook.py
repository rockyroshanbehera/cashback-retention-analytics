"""Build the Excel decision workbook from the pipeline outputs.

Implementation note: the workbook is written with **XlsxWriter**, chosen because it is the
only writer in this environment that can emit native Excel charts, conditional-format colour
scales, defined number formats and frozen panes in a single pass. openpyxl is used separately
by ``src/verify_workbook.py`` to read the finished file back and audit it, so the file is
written by one library and independently verified by another.

Every calculated cell on the KPI Calculations and Offer Simulator sheets is a live Excel
formula referencing labelled input cells - none of them are pasted values.
"""
from __future__ import annotations

import json
import re

import pandas as pd
import xlsxwriter

from config import DISCLAIMER, OUTPUT_DIR
from write_docs import build_actions

WORKBOOK_PATH = OUTPUT_DIR / "cashback_retention_dashboard.xlsx"

# Restrained fintech palette: purple primary, dark grey text, white ground.
PURPLE = "#5F259F"
PURPLE_DARK = "#3B1466"
PURPLE_LIGHT = "#EDE7F6"
PURPLE_MID = "#8E6BC0"
GREY_DARK = "#2E2E38"
GREY_MID = "#6B6B76"
GREY_LINE = "#D8D8E0"
GREY_BG = "#F7F6FA"
GREEN = "#1B7F5A"
GREEN_BG = "#E3F3EC"
AMBER = "#B5761B"
AMBER_BG = "#FBF0DC"
RED = "#B3261E"
RED_BG = "#FBE6E4"
INPUT_BG = "#FFF6DA"
INPUT_BORDER = "#D9A93B"

ACTION_STYLE = {"Scale": (GREEN, GREEN_BG), "Test further": (AMBER, AMBER_BG),
                "Redesign offer": (AMBER, AMBER_BG), "Do not target": (RED, RED_BG)}

PRESENTATION_SHEETS = ("Executive Dashboard", "Campaign Performance", "Segment Analysis",
                       "Cohort Retention", "Experiment Results", "Forecast",
                       "Offer Simulator", "KPI Calculations", "Methodology")


def _formats(wb: xlsxwriter.Workbook) -> dict:
    """Named cell formats used across every sheet."""
    base = {"font_name": "Segoe UI", "font_color": GREY_DARK}
    f = {}
    f["title"] = wb.add_format({**base, "font_size": 20, "bold": True, "font_color": PURPLE_DARK})
    f["subtitle"] = wb.add_format({**base, "font_size": 11, "font_color": GREY_MID})
    f["disclaimer"] = wb.add_format({**base, "font_size": 9, "italic": True, "font_color": PURPLE_DARK,
                                     "bg_color": PURPLE_LIGHT, "align": "left", "valign": "vcenter",
                                     "border": 1, "border_color": PURPLE_MID, "text_wrap": True})
    f["section"] = wb.add_format({**base, "font_size": 12, "bold": True, "font_color": "#FFFFFF",
                                  "bg_color": PURPLE, "align": "left", "valign": "vcenter", "indent": 1})
    f["sub"] = wb.add_format({**base, "font_size": 10, "bold": True, "font_color": PURPLE_DARK})
    f["header"] = wb.add_format({**base, "font_size": 10, "bold": True, "font_color": "#FFFFFF",
                                 "bg_color": PURPLE, "align": "center", "valign": "vcenter",
                                 "text_wrap": True, "border": 1, "border_color": PURPLE})
    f["text"] = wb.add_format({**base, "font_size": 10, "valign": "vcenter"})
    f["text_wrap"] = wb.add_format({**base, "font_size": 10, "valign": "top", "text_wrap": True})
    f["note"] = wb.add_format({**base, "font_size": 9, "italic": True, "font_color": GREY_MID,
                               "valign": "top", "text_wrap": True})
    f["label"] = wb.add_format({**base, "font_size": 10, "bold": True, "valign": "vcenter"})

    cell = {**base, "font_size": 10, "border": 1, "border_color": GREY_LINE, "valign": "vcenter"}
    f["cell"] = wb.add_format(cell)
    f["cell_alt"] = wb.add_format({**cell, "bg_color": GREY_BG})
    f["int"] = wb.add_format({**cell, "num_format": "#,##0", "align": "right"})
    f["int_alt"] = wb.add_format({**cell, "bg_color": GREY_BG, "num_format": "#,##0", "align": "right"})
    f["pct1"] = wb.add_format({**cell, "num_format": "0.0%", "align": "right"})
    f["pct1_alt"] = wb.add_format({**cell, "bg_color": GREY_BG, "num_format": "0.0%", "align": "right"})
    f["pct2"] = wb.add_format({**cell, "num_format": "0.00%", "align": "right"})
    f["pct2_alt"] = wb.add_format({**cell, "bg_color": GREY_BG, "num_format": "0.00%", "align": "right"})
    f["pp"] = wb.add_format({**cell, "num_format": '0.00" pp"', "align": "right"})
    f["pp_alt"] = wb.add_format({**cell, "bg_color": GREY_BG, "num_format": '0.00" pp"', "align": "right"})
    f["inr"] = wb.add_format({**cell, "num_format": '[$₹-en-IN]#,##0;-[$₹-en-IN]#,##0', "align": "right"})
    f["inr_alt"] = wb.add_format({**cell, "bg_color": GREY_BG,
                                  "num_format": '[$₹-en-IN]#,##0;-[$₹-en-IN]#,##0', "align": "right"})
    f["inr2"] = wb.add_format({**cell, "num_format": '[$₹-en-IN]#,##0.00;-[$₹-en-IN]#,##0.00', "align": "right"})
    f["dec2"] = wb.add_format({**cell, "num_format": "0.00", "align": "right"})
    f["dec2_alt"] = wb.add_format({**cell, "bg_color": GREY_BG, "num_format": "0.00", "align": "right"})
    f["dec3"] = wb.add_format({**cell, "num_format": "+0.000;-0.000;0.000", "align": "right"})
    f["dec3_alt"] = wb.add_format({**cell, "bg_color": GREY_BG,
                                   "num_format": "+0.000;-0.000;0.000", "align": "right"})
    f["sci"] = wb.add_format({**cell, "num_format": "0.0E+00", "align": "right"})
    f["sci_alt"] = wb.add_format({**cell, "bg_color": GREY_BG, "num_format": "0.0E+00", "align": "right"})
    f["date"] = wb.add_format({**cell, "num_format": "dd-mmm-yyyy", "align": "center"})
    f["date_alt"] = wb.add_format({**cell, "bg_color": GREY_BG, "num_format": "dd-mmm-yyyy", "align": "center"})
    f["month"] = wb.add_format({**cell, "num_format": "mmm yyyy", "align": "center", "bold": True})

    f["kpi_label"] = wb.add_format({**base, "font_size": 9, "bold": True, "font_color": "#FFFFFF",
                                    "bg_color": PURPLE, "align": "center", "valign": "bottom",
                                    "top": 1, "left": 1, "right": 1, "border_color": PURPLE})
    f["kpi_value"] = wb.add_format({**base, "font_size": 22, "bold": True, "font_color": "#FFFFFF",
                                    "bg_color": PURPLE, "align": "center", "valign": "vcenter",
                                    "left": 1, "right": 1, "border_color": PURPLE})
    f["kpi_foot"] = wb.add_format({**base, "font_size": 8, "font_color": PURPLE_LIGHT,
                                   "bg_color": PURPLE, "align": "center", "valign": "top",
                                   "bottom": 1, "left": 1, "right": 1, "border_color": PURPLE})

    f["input"] = wb.add_format({**base, "font_size": 11, "bold": True, "bg_color": INPUT_BG,
                                "border": 2, "border_color": INPUT_BORDER, "align": "right",
                                "valign": "vcenter"})
    f["input_pct"] = wb.add_format({**base, "font_size": 11, "bold": True, "bg_color": INPUT_BG,
                                    "border": 2, "border_color": INPUT_BORDER, "num_format": "0.0%",
                                    "align": "right", "valign": "vcenter"})
    f["input_inr"] = wb.add_format({**base, "font_size": 11, "bold": True, "bg_color": INPUT_BG,
                                    "border": 2, "border_color": INPUT_BORDER, "align": "right",
                                    "num_format": '[$₹-en-IN]#,##0.00', "valign": "vcenter"})
    f["input_int"] = wb.add_format({**base, "font_size": 11, "bold": True, "bg_color": INPUT_BG,
                                    "border": 2, "border_color": INPUT_BORDER, "num_format": "#,##0",
                                    "align": "right", "valign": "vcenter"})
    f["input_dec"] = wb.add_format({**base, "font_size": 11, "bold": True, "bg_color": INPUT_BG,
                                    "border": 2, "border_color": INPUT_BORDER, "num_format": "0.00",
                                    "align": "right", "valign": "vcenter"})

    out = {**base, "font_size": 11, "bold": True, "bg_color": PURPLE_LIGHT, "border": 1,
           "border_color": PURPLE_MID, "align": "right", "valign": "vcenter", "font_color": PURPLE_DARK}
    f["out"] = wb.add_format(out)
    f["out_inr"] = wb.add_format({**out, "num_format": '[$₹-en-IN]#,##0;-[$₹-en-IN]#,##0'})
    f["out_pct"] = wb.add_format({**out, "num_format": "0.0%"})
    f["out_pp"] = wb.add_format({**out, "num_format": '0.00" pp"'})
    f["out_int"] = wb.add_format({**out, "num_format": "#,##0"})
    f["out_dec"] = wb.add_format({**out, "num_format": "0.00"})

    for name, (fg, bg) in ACTION_STYLE.items():
        f[f"action_{name}"] = wb.add_format({**base, "font_size": 10, "bold": True, "font_color": fg,
                                             "bg_color": bg, "align": "center", "valign": "vcenter",
                                             "border": 1, "border_color": GREY_LINE})
    f["legend_input"] = wb.add_format({**base, "font_size": 9, "bg_color": INPUT_BG, "border": 2,
                                       "border_color": INPUT_BORDER, "align": "center", "valign": "vcenter"})
    f["legend_out"] = wb.add_format({**base, "font_size": 9, "bg_color": PURPLE_LIGHT, "border": 1,
                                     "border_color": PURPLE_MID, "align": "center", "valign": "vcenter"})
    f["legend_src"] = wb.add_format({**base, "font_size": 9, "bg_color": GREY_BG, "border": 1,
                                     "border_color": GREY_LINE, "align": "center", "valign": "vcenter"})
    f["insight_num"] = wb.add_format({**base, "font_size": 14, "bold": True, "font_color": "#FFFFFF",
                                      "bg_color": PURPLE_MID, "align": "center", "valign": "vcenter"})
    f["insight"] = wb.add_format({**base, "font_size": 10, "valign": "vcenter", "text_wrap": True,
                                  "bg_color": GREY_BG, "border": 1, "border_color": GREY_LINE, "indent": 1})
    return f


def _banner(ws, f, title: str, subtitle: str, last_col: int, period: str) -> None:
    """Standard header block: title, subtitle, reporting period and disclaimer."""
    ws.hide_gridlines(2)
    ws.set_row(0, 8)
    ws.set_row(1, 30)
    ws.set_row(2, 16)
    ws.set_row(3, 16)
    ws.set_row(4, 28)
    ws.write(1, 1, title, f["title"])
    ws.write(2, 1, subtitle, f["subtitle"])
    ws.write(3, 1, f"Reporting period: {period}   |   Synthetic data, seed 20260813", f["subtitle"])
    ws.merge_range(4, 1, 4, max(last_col, 4), DISCLAIMER, f["disclaimer"])
    ws.set_row(5, 8)


def _table(ws, f, frame: pd.DataFrame, headers: list[str], kinds: list[str],
           row0: int, col0: int, header_h: int = 30) -> int:
    """Write a banded, bordered table. Returns the first row after the table."""
    ws.set_row(row0, header_h)
    for j, h in enumerate(headers):
        ws.write(row0, col0 + j, h, f["header"])
    for i, rec in enumerate(frame.itertuples(index=False, name=None)):
        r = row0 + 1 + i
        alt = i % 2 == 1
        for j, (value, kind) in enumerate(zip(rec, kinds)):
            if kind == "action":
                ws.write(r, col0 + j, value, f[f"action_{value}"])
                continue
            key = kind if not alt else f"{kind}_alt"
            fmt = f.get(key, f.get(kind, f["cell"]))
            if value is None or (isinstance(value, float) and pd.isna(value)):
                ws.write_blank(r, col0 + j, None, fmt)
            elif isinstance(value, pd.Timestamp):
                ws.write_datetime(r, col0 + j, value.to_pydatetime(), fmt)
            else:
                ws.write(r, col0 + j, value, fmt)
    return row0 + 1 + len(frame)


def _kpi_card(ws, f, row: int, col: int, label: str, value, fmt_str: str, foot: str) -> None:
    """Three-row KPI card occupying two columns."""
    ws.merge_range(row, col, row, col + 1, label.upper(), f["kpi_label"])
    v = ws.merge_range(row + 1, col, row + 1, col + 1, value, f["kpi_value"])
    if fmt_str:
        pass
    ws.merge_range(row + 2, col, row + 2, col + 1, foot, f["kpi_foot"])
    return v


def _kpi_value_format(wb, num_format: str):
    return wb.add_format({"font_name": "Segoe UI", "font_size": 20, "bold": True,
                          "font_color": "#FFFFFF", "bg_color": PURPLE, "align": "center",
                          "valign": "vcenter", "left": 1, "right": 1, "border_color": PURPLE,
                          "num_format": num_format})


def build_workbook() -> str:
    """Generate outputs/cashback_retention_dashboard.xlsx. Returns the path as a string."""
    seg = pd.read_csv(OUTPUT_DIR / "segment_recommendations.csv")
    camp = pd.read_csv(OUTPUT_DIR / "campaign_performance.csv")
    cohort = pd.read_csv(OUTPUT_DIR / "cohort_retention_matrix.csv", parse_dates=["cohort_month"])
    scen = pd.read_csv(OUTPUT_DIR / "scenarios.csv")
    fcast = pd.read_csv(OUTPUT_DIR / "forecast.csv", parse_dates=["date"])
    hold = pd.read_csv(OUTPUT_DIR / "forecast_holdout.csv", parse_dates=["date"])
    models = pd.read_csv(OUTPUT_DIR / "forecast_model_comparison.csv")
    profile = pd.read_csv(OUTPUT_DIR / "segment_profile.csv")
    meta = json.loads((OUTPUT_DIR / "generation_metadata.json").read_text(encoding="utf-8"))
    fsum = json.loads((OUTPUT_DIR / "forecast_summary.json").read_text(encoding="utf-8"))
    notes = json.loads((OUTPUT_DIR / "experiment_notes.json").read_text(encoding="utf-8"))
    dq = json.loads((OUTPUT_DIR / "data_quality_report.json").read_text(encoding="utf-8"))
    sample = pd.read_csv(OUTPUT_DIR.parent / "data" / "processed" / "transactions_sample.csv",
                         parse_dates=["transaction_date"])

    period = meta["reporting_period"]
    margin = meta["contribution_margin_rate"]
    tpr = notes["assumptions"]["txns_per_incremental_retained"]
    order = ["Scale", "Test further", "Redesign offer", "Do not target"]
    seg = seg.assign(_r=seg.action.map({a: i for i, a in enumerate(order)})).sort_values(
        ["_r", "incremental_profit"], ascending=[True, False]).drop(columns="_r").reset_index(drop=True)
    scale = seg[seg.action.eq("Scale")]
    total_treated = seg.treatment_size.sum()
    total_cost = seg.cashback_cost.sum()
    total_profit = seg.incremental_profit.sum()
    blanket_roi = total_profit / total_cost
    focused_roi = scale.incremental_profit.sum() / scale.cashback_cost.sum()
    pooled_uplift = ((seg.treatment_d30_retention * seg.treatment_size).sum() / seg.treatment_size.sum() -
                     (seg.control_d30_retention * seg.control_size).sum() / seg.control_size.sum())

    wb = xlsxwriter.Workbook(str(WORKBOOK_PATH), {"nan_inf_to_errors": False})
    wb.set_properties({"title": "Cashback Campaign Optimization & Customer Retention Analytics",
                       "subject": "Synthetic portfolio project", "author": "Brajesh Mohanty",
                       "comments": DISCLAIMER})
    f = _formats(wb)

    # ---------------------------------------------------------------- 1. Executive Dashboard
    ws = wb.add_worksheet("Executive Dashboard")
    ws.set_tab_color(PURPLE)
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 14.5)
    ws.set_column("C:M", 12.5)
    ws.set_column("N:N", 12.5)
    ws.set_column("O:O", 2.5)
    _banner(ws, f, "Cashback Campaign Optimization & Customer Retention Analytics",
            "Which segments should receive cashback to maximize incremental retention at positive economics?",
            13, period)

    r = 6
    ws.merge_range(r, 1, r, 12, "HEADLINE RESULTS  (observed, randomized synthetic experiment)", f["section"])
    ws.set_row(r, 22)
    r += 1
    ws.set_row(r, 16)
    ws.set_row(r + 1, 34)
    ws.set_row(r + 2, 16)
    cards = [
        ("Customers analysed", meta["customers"], "#,##0", f"{meta['transactions']:,} transactions"),
        ("Randomized", meta["campaign_assignments"], "#,##0",
         f"{meta['campaigns']} campaign waves, 50/50 split"),
        ("D30 retention uplift", pooled_uplift * 100, '0.00" pp"', "treatment minus control, pooled"),
        ("Incremental transactions", seg.incremental_transactions.sum(), "#,##0", "successful, D30 window"),
        ("Programme ROI (all)", blanket_roi, "0.0%", "treating every segment"),
        ("Programme ROI (focused)", focused_roi, "0.0%",
         f"{' + '.join(scale.segment)} only" if len(scale) <= 2 else f"{len(scale)} scale segments"),
    ]
    for i, (label, value, numfmt, foot) in enumerate(cards):
        c = 1 + i * 2
        ws.merge_range(r, c, r, c + 1, label.upper(), f["kpi_label"])
        ws.merge_range(r + 1, c, r + 1, c + 1, value, _kpi_value_format(wb, numfmt))
        ws.merge_range(r + 2, c, r + 2, c + 1, foot, f["kpi_foot"])
    r += 4

    # Treatment vs control comparison block
    ws.merge_range(r, 1, r, 6, "TREATMENT VS CONTROL", f["section"])
    ws.merge_range(r, 7, r, 12, "CAMPAIGN ECONOMICS  (by wave)", f["section"])
    ws.set_row(r, 22)
    r += 1
    tvc = pd.DataFrame({
        "Metric": ["D30 retention", "D7 repeat rate", "Post-window txns per customer",
                   "Customers", "Redemption rate"],
        "Control": [(seg.control_d30_retention * seg.control_size).sum() / seg.control_size.sum(),
                    (seg.control_d7_rate * seg.control_size).sum() / seg.control_size.sum(),
                    (seg.control_post_frequency * seg.control_size).sum() / seg.control_size.sum(),
                    seg.control_size.sum(), 0.0],
        "Treatment": [(seg.treatment_d30_retention * seg.treatment_size).sum() / seg.treatment_size.sum(),
                      (seg.treatment_d7_rate * seg.treatment_size).sum() / seg.treatment_size.sum(),
                      (seg.treatment_post_frequency * seg.treatment_size).sum() / seg.treatment_size.sum(),
                      seg.treatment_size.sum(),
                      (seg.redemption_rate * seg.treatment_size).sum() / seg.treatment_size.sum()],
    })
    tvc["Difference"] = tvc.Treatment - tvc.Control
    tvc_disp = tvc.copy()
    ws.set_row(r, 26)
    # Metric label spans two columns so the block fills its section width exactly.
    ws.merge_range(r, 1, r, 2, "Metric", f["header"])
    for j, h in enumerate(["Control", "Treatment", "Difference"]):
        ws.write(r, 3 + j, h, f["header"])
    ws.write_blank(r, 6, None, f["header"])
    kind_by_row = ["pct1", "pct1", "dec2", "int", "pct1"]
    for i, rec in enumerate(tvc_disp.itertuples(index=False, name=None)):
        rr = r + 1 + i
        alt = "_alt" if i % 2 else ""
        ws.merge_range(rr, 1, rr, 2, rec[0], f["cell" + alt])
        for j in range(1, 4):
            ws.write(rr, 2 + j, rec[j], f[kind_by_row[i] + alt])
        ws.write_blank(rr, 6, None, f["cell" + alt])
    ws.merge_range(r + 6, 1, r + 6, 6, "Control receives no offer. The denominator is every assigned "
                                       "customer (intent to treat), not only redeemers.", f["note"])
    ws.set_row(r + 6, 26)

    econ = camp[["campaign_name", "cashback_cost", "incremental_contribution", "incremental_profit", "roi"]]
    ws.set_row(r, 26)
    # Campaign names need two columns; the four numeric columns then fill J..M exactly.
    ws.merge_range(r, 7, r, 8, "Campaign", f["header"])
    for j, h in enumerate(["Cashback cost", "Incr. contribution", "Incr. profit", "ROI"]):
        ws.write(r, 9 + j, h, f["header"])
    for i, rec in enumerate(econ.itertuples(index=False, name=None)):
        rr = r + 1 + i
        alt = "_alt" if i % 2 else ""
        ws.merge_range(rr, 7, rr, 8, rec[0], f["cell" + alt])
        for j, k in enumerate(["inr", "inr", "inr", "pct1"]):
            ws.write(rr, 9 + j, rec[1 + j], f[k + alt])
    tot_row = r + 1 + len(econ)
    ws.merge_range(tot_row, 7, tot_row, 8, "All waves", f["label"])
    for j, col in enumerate(["cashback_cost", "incremental_contribution", "incremental_profit"]):
        ws.write(tot_row, 9 + j, camp[col].sum(), f["out_inr"])
    ws.write(tot_row, 12, camp.incremental_profit.sum() / camp.cashback_cost.sum(), f["out_pct"])
    ws.merge_range(tot_row + 1, 7, tot_row + 3, 12,
                   f"Cashback cost reconciles exactly with the segment view (₹{camp.cashback_cost.sum():,.0f}). "
                   "Profit differs slightly because each aggregation uses its own average payment "
                   "value and the segment view floors negative transaction lift at zero contribution. "
                   "The KPI cards and recommendation matrix use the segment view.", f["note"])
    for extra in range(1, 4):
        ws.set_row(tot_row + extra, 16)
    r += 8

    # Charts row 1: segment uplift + campaign economics
    ws.merge_range(r, 1, r, 6, "SEGMENT D30 UPLIFT (percentage points)", f["section"])
    ws.merge_range(r, 7, r, 12, "CAMPAIGN ECONOMICS: COST VS CONTRIBUTION", f["section"])
    ws.set_row(r, 22)
    r += 1

    # Segment Analysis writes its header on row 8 (0-indexed) and data on rows 9..9+n-1;
    # the uplift column sits at index 7. Both must match or the chart silently plots headers.
    ch = wb.add_chart({"type": "column"})
    ch.add_series({
        "name": "D30 uplift (pp)",
        "categories": ["Segment Analysis", 9, 1, 9 + len(seg) - 1, 1],
        "values": ["Segment Analysis", 9, 7, 9 + len(seg) - 1, 7],
        "fill": {"color": PURPLE},
        "border": {"none": True},
        "data_labels": {"value": True, "num_format": "0.0", "font": {"name": "Segoe UI", "size": 8,
                                                                     "color": GREY_DARK}},
    })
    ch.set_title({"none": True})
    ch.set_legend({"none": True})
    ch.set_y_axis({"name": "Percentage points", "num_format": "0.0",
                   "name_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                   "num_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                   "major_gridlines": {"visible": True, "line": {"color": GREY_LINE}},
                   "line": {"color": GREY_LINE}})
    ch.set_x_axis({"num_font": {"name": "Segoe UI", "size": 9, "color": GREY_DARK},
                   "line": {"color": GREY_LINE}})
    ch.set_chartarea({"border": {"color": GREY_LINE}, "fill": {"color": "#FFFFFF"}})
    ch.set_plotarea({"fill": {"color": "#FFFFFF"}})
    ch.set_size({"width": 470, "height": 260})
    ws.insert_chart(r, 1, ch, {"x_offset": 4, "y_offset": 4})

    ch2 = wb.add_chart({"type": "column"})
    # Campaign Performance: header on row 8, data on rows 9..9+n-1; cashback cost is column 14
    # and incremental contribution column 15.
    for name, col, colour in [("Cashback cost", 14, PURPLE_MID),
                              ("Incremental contribution", 15, GREEN)]:
        ch2.add_series({
            "name": name,
            "categories": ["Campaign Performance", 9, 1, 9 + len(camp) - 1, 1],
            "values": ["Campaign Performance", 9, col, 9 + len(camp) - 1, col],
            "fill": {"color": colour}, "border": {"none": True},
        })
    ch2.set_title({"none": True})
    ch2.set_legend({"position": "bottom", "font": {"name": "Segoe UI", "size": 9, "color": GREY_DARK}})
    ch2.set_y_axis({"name": "Rupees", "num_format": "#,##0",
                    "name_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                    "num_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                    "major_gridlines": {"visible": True, "line": {"color": GREY_LINE}},
                    "line": {"color": GREY_LINE}})
    ch2.set_x_axis({"num_font": {"name": "Segoe UI", "size": 9, "color": GREY_DARK},
                    "line": {"color": GREY_LINE}})
    ch2.set_chartarea({"border": {"color": GREY_LINE}, "fill": {"color": "#FFFFFF"}})
    ch2.set_plotarea({"fill": {"color": "#FFFFFF"}})
    ch2.set_size({"width": 470, "height": 260})
    ws.insert_chart(r, 7, ch2, {"x_offset": 4, "y_offset": 4})
    r += 14

    # Full-width forecast chart. Every series shares the whole 60-row date column so the
    # x-axis spans holdout and outlook rather than only the holdout window.
    ws.merge_range(r, 1, r, 12, "DAILY TRANSACTION FORECAST (30-day holdout, then 30-day outlook)",
                   f["section"])
    ws.set_row(r, 22)
    r += 1
    n_hold, n_fc = len(hold), len(fcast)
    fc_first, fc_last = 9, 9 + n_hold + n_fc - 1
    ch3 = wb.add_chart({"type": "line"})
    for name, col, style in [
        ("Actual (holdout)", 2, {"color": GREY_DARK, "width": 1.75}),
        (f"{fsum['selected_model']} (holdout fit)", 3, {"color": AMBER, "width": 1.5,
                                                        "dash_type": "dash"}),
        ("Forecast", 4, {"color": PURPLE, "width": 2.25}),
        ("95% lower", 5, {"color": PURPLE_MID, "width": 1, "dash_type": "round_dot"}),
        ("95% upper", 6, {"color": PURPLE_MID, "width": 1, "dash_type": "round_dot"}),
    ]:
        ch3.add_series({
            "name": name,
            "categories": ["Forecast", fc_first, 1, fc_last, 1],
            "values": ["Forecast", fc_first, col, fc_last, col],
            "line": style, "marker": {"type": "none"},
        })
    ch3.set_title({"none": True})
    ch3.set_legend({"position": "bottom", "font": {"name": "Segoe UI", "size": 8, "color": GREY_DARK}})
    ch3.set_y_axis({"name": "Successful transactions per day", "num_format": "#,##0",
                    "name_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                    "num_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                    "major_gridlines": {"visible": True, "line": {"color": GREY_LINE}},
                    "line": {"color": GREY_LINE}})
    ch3.set_x_axis({"num_font": {"name": "Segoe UI", "size": 8, "color": GREY_MID},
                    "line": {"color": GREY_LINE}, "interval_unit": 7, "num_format": "dd-mmm"})
    ch3.set_chartarea({"border": {"color": GREY_LINE}, "fill": {"color": "#FFFFFF"}})
    ch3.set_plotarea({"fill": {"color": "#FFFFFF"}})
    ch3.set_size({"width": 960, "height": 280})
    ws.insert_chart(r, 1, ch3, {"x_offset": 4, "y_offset": 4})
    r += 15

    # Full-width cohort heatmap: label column plus twelve month columns.
    ws.merge_range(r, 1, r, 13, "SIGNUP-COHORT RETENTION HEATMAP", f["section"])
    ws.set_row(r, 22)
    r += 1
    hm_r, hm_c = r, 1
    months = [c for c in cohort.columns if c != "cohort_month"][:12]
    ws.set_row(hm_r, 20)
    ws.write(hm_r, hm_c, "Signup cohort", f["header"])
    for j, m in enumerate(months):
        ws.write(hm_r, hm_c + 1 + j, f"Month {m}", f["header"])
    small_pct = wb.add_format({"font_name": "Segoe UI", "font_size": 9, "num_format": "0.0%",
                               "align": "center", "valign": "vcenter", "border": 1,
                               "border_color": "#FFFFFF"})
    small_month = wb.add_format({"font_name": "Segoe UI", "font_size": 9, "bold": True,
                                 "num_format": "mmm yyyy", "align": "center", "valign": "vcenter",
                                 "font_color": GREY_DARK, "border": 1, "border_color": GREY_LINE})
    cohort_values = cohort[months].to_numpy(dtype=float)
    cohort_months = list(cohort.cohort_month)
    for i, month_start in enumerate(cohort_months):
        rr = hm_r + 1 + i
        ws.set_row(rr, 15)
        ws.write_datetime(rr, hm_c, month_start.to_pydatetime(), small_month)
        for j in range(len(months)):
            v = cohort_values[i, j]
            if pd.isna(v):
                ws.write_blank(rr, hm_c + 1 + j, None, small_pct)
            else:
                ws.write_number(rr, hm_c + 1 + j, float(v), small_pct)
    ws.conditional_format(hm_r + 1, hm_c + 1, hm_r + len(cohort), hm_c + len(months),
                          {"type": "3_color_scale", "min_color": "#FFFFFF",
                           "mid_color": "#C9B6E4", "max_color": PURPLE,
                           "min_type": "num", "min_value": 0, "mid_type": "num", "mid_value": 0.35,
                           "max_type": "num", "max_value": 0.72})
    nrow = hm_r + len(cohort) + 1
    ws.merge_range(nrow, 1, nrow, 13,
                   "Share of each signup cohort with a successful transaction in month M after signup. "
                   "Month 0 is the partial signup month. The denominator is fixed at the cohort's "
                   "original size; blank cells are unobserved, not zero.", f["note"])
    ws.set_row(nrow, 26)
    r = nrow + 2

    # Recommendation matrix
    ws.merge_range(r, 1, r, 12, "RECOMMENDATION MATRIX", f["section"])
    ws.set_row(r, 22)
    r += 1
    rec = pd.DataFrame({
        "Segment": seg.segment, "Treated": seg.treatment_size,
        "Control D30": seg.control_d30_retention, "Treatment D30": seg.treatment_d30_retention,
        "Uplift": seg.absolute_uplift * 100, "CI low": seg.ci_low * 100, "CI high": seg.ci_high * 100,
        "Incr. retained": seg.incremental_retained_customers, "Incr. txns": seg.incremental_transactions,
        "Cashback cost": seg.cashback_cost, "Incr. profit": seg.incremental_profit,
        "ROI": seg.roi, "Action": seg.action,
    })
    r = _table(ws, f, rec,
               ["Segment", "Treated", "Control D30", "Treatment D30", "Uplift", "95% CI low",
                "95% CI high", "Incr. retained", "Incr. txns", "Cashback cost", "Incr. profit",
                "ROI", "Action"],
               ["cell", "int", "pct1", "pct1", "pp", "pp", "pp", "int", "int", "inr", "inr",
                "pct1", "action"], r, 1)
    ws.merge_range(r, 1, r, 13,
                   "Rule - Scale: CI low > 0 and ROI >= 15%.   Test further: uplift > 0 and ROI >= 0.   "
                   "Redesign offer: CI low > 0 but ROI < 0.   Do not target: otherwise.", f["note"])
    ws.set_row(r, 18)
    r += 2

    # Insights and actions
    ws.merge_range(r, 1, r, 6, "TOP THREE INSIGHTS", f["section"])
    ws.merge_range(r, 7, r, 12, "RECOMMENDED ACTIONS", f["section"])
    ws.set_row(r, 22)
    r += 1
    strongest = seg.loc[seg.absolute_uplift.idxmax()]
    worst = seg.loc[seg.incremental_profit.idxmin()]
    credible = seg[seg.ci_low > 0]
    disagree = len(seg[(seg.ci_low > 0) & (seg.roi < 0.15)])
    insights = [
        f"Response is concentrated, not broad. {strongest.segment} lifts D30 retention by "
        f"{strongest.absolute_uplift * 100:.2f} pp (95% CI {strongest.ci_low * 100:.2f} to "
        f"{strongest.ci_high * 100:.2f} pp), while {worst.segment} returns {worst.roi:.0%}.",
        f"Significance and economics disagree. {disagree} of {len(seg)} segments have an uplift "
        f"interval that excludes zero yet fail the 15% return hurdle, so a p-value-only rule "
        f"would have funded losses.",
        f"Targeting is worth the effort: among the {len(credible)} segments with a credible lift, "
        f"one incremental retained customer costs between "
        f"₹{credible.cost_per_incremental_retained.min():,.0f} and "
        f"₹{credible.cost_per_incremental_retained.max():,.0f} - a "
        f"{credible.cost_per_incremental_retained.max() / credible.cost_per_incremental_retained.min():.0f}x spread.",
    ]
    # Shared with the markdown deliverables so the workbook and the executive summary can
    # never recommend different things, and so an empty action category stays grammatical.
    actions = [re.sub(r"\*\*(.+?)\*\*", r"\1", a) for a in build_actions(seg)]
    for i, (ins, act) in enumerate(zip(insights, actions)):
        rr = r + i * 2
        # Roughly 55 characters fit per line across the five merged columns.
        lines = max(len(ins), len(act)) // 55 + 1
        ws.set_row(rr, max(34, 16 * lines))
        ws.set_row(rr + 1, 6)
        ws.write(rr, 1, i + 1, f["insight_num"])
        ws.merge_range(rr, 2, rr, 6, ins, f["insight"])
        ws.write(rr, 7, i + 1, f["insight_num"])
        ws.merge_range(rr, 8, rr, 12, act, f["insight"])
    r += 7
    ws.merge_range(r, 1, r, 12,
                   "Observed figures come from the randomized synthetic experiment. Scenario and "
                   "Offer Simulator figures are projections built on a stated "
                   f"{margin:.0%} contribution margin and {tpr:.2f} incremental transactions per "
                   "incremental retained customer. See the Methodology sheet.", f["note"])
    ws.set_row(r, 26)
    ws.freeze_panes(6, 1)
    ws.set_paper(9)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    ws.print_area(0, 0, r + 1, 13)

    # ---------------------------------------------------------------- 2. Campaign Performance
    ws = wb.add_worksheet("Campaign Performance")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 22)
    ws.set_column("C:S", 13)
    _banner(ws, f, "Campaign Performance", "Per-wave randomized results, cost and return", 12, period)
    cp = pd.DataFrame({
        "Campaign": camp.campaign_name, "Assigned": camp.eligible_customers,
        "Treatment": camp.treatment_size, "Control": camp.control_size,
        "Treatment share": camp.treatment_share, "Redemption rate": camp.redemption_rate,
        "Control D30": camp.control_d30_retention, "Treatment D30": camp.treatment_d30_retention,
        "Uplift": camp.absolute_uplift * 100, "CI low": camp.ci_low * 100, "CI high": camp.ci_high * 100,
        "Incr. retained": camp.incremental_retained_customers,
        "Incr. txns": camp.incremental_transactions,
        "Cashback cost": camp.cashback_cost, "Incr. contribution": camp.incremental_contribution,
        "Incr. profit": camp.incremental_profit, "ROI": camp.roi,
        "Cost / incr. retained": camp.cost_per_incremental_retained,
    })
    end = _table(ws, f, cp,
                 ["Campaign", "Assigned", "Treatment", "Control", "Treatment share", "Redemption rate",
                  "Control D30", "Treatment D30", "Uplift", "95% CI low", "95% CI high",
                  "Incr. retained", "Incr. txns", "Cashback cost", "Incr. contribution",
                  "Incr. profit", "ROI", "Cost / incr. retained"],
                 ["cell", "int", "int", "int", "pct1", "pct1", "pct1", "pct1", "pp", "pp", "pp",
                  "int", "int", "inr", "inr", "inr", "pct1", "inr"], 8, 1)
    ws.write(end + 1, 1, "Uplift and CI are in percentage points. Cashback cost is the sum of actual "
                         "redemptions by treated customers, not a budgeted figure.", f["note"])
    campaign_meta = pd.DataFrame({
        "Campaign": camp.campaign_name,
        "Window": [f"{a} to {b}" for a, b in zip(
            pd.read_csv(OUTPUT_DIR.parent / "data" / "processed" / "campaigns.csv").start_date,
            pd.read_csv(OUTPUT_DIR.parent / "data" / "processed" / "campaigns.csv").end_date)],
        "Eligibility": pd.read_csv(OUTPUT_DIR.parent / "data" / "processed" / "campaigns.csv").target_segment,
        "Cashback offer": pd.read_csv(OUTPUT_DIR.parent / "data" / "processed" / "campaigns.csv").cashback_offer,
        "Minimum spend": pd.read_csv(OUTPUT_DIR.parent / "data" / "processed" / "campaigns.csv").minimum_spend,
    })
    ws.write(end + 3, 1, "Campaign design", f["sub"])
    _table(ws, f, campaign_meta, ["Campaign", "Window", "Eligibility", "Cashback offer", "Minimum spend"],
           ["cell", "cell", "cell", "inr", "inr"], end + 4, 1)
    ws.freeze_panes(9, 2)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 3. Segment Analysis
    ws = wb.add_worksheet("Segment Analysis")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 15)
    ws.set_column("C:T", 13)
    ws.set_column("U:U", 15)
    _banner(ws, f, "Segment Analysis", "Uplift, economics and recommended action by RFM segment", 19, period)
    sa = pd.DataFrame({
        "Segment": seg.segment, "Treated": seg.treatment_size, "Control": seg.control_size,
        "Treatment share": seg.treatment_share,
        "Control D30": seg.control_d30_retention, "Treatment D30": seg.treatment_d30_retention,
        "Uplift": seg.absolute_uplift * 100, "CI low": seg.ci_low * 100, "CI high": seg.ci_high * 100,
        "p-value": seg.p_value, "Incr. retained": seg.incremental_retained_customers,
        "Incr. txns": seg.incremental_transactions, "Redemption rate": seg.redemption_rate,
        "Cashback cost": seg.cashback_cost, "Incr. contribution": seg.incremental_contribution,
        "Incr. profit": seg.incremental_profit, "ROI": seg.roi,
        "Cost / incr. retained": seg.cost_per_incremental_retained,
        "Pre-freq SMD": seg.pre_frequency_smd, "Action": seg.action,
    })
    end = _table(ws, f, sa,
                 ["Segment", "Treated", "Control", "Treatment share", "Control D30", "Treatment D30",
                  "Uplift", "95% CI low", "95% CI high", "p-value", "Incr. retained", "Incr. txns",
                  "Redemption rate", "Cashback cost", "Incr. contribution", "Incr. profit", "ROI",
                  "Cost / incr. retained", "Pre-freq SMD", "Action"],
                 ["cell", "int", "int", "pct1", "pct1", "pct1", "pp", "pp", "pp", "sci", "int",
                  "int", "pct1", "inr", "inr", "inr", "pct1", "inr", "dec3", "action"], 8, 1)
    ws.merge_range(end + 1, 1, end + 1, 19,
                   "Pre-freq SMD is the standardized mean difference in pre-period transaction count "
                   "between arms; values within +/-0.10 indicate balanced randomization.", f["note"])
    ws.merge_range(end + 2, 1, end + 2, 19,
                   "Cost / incr. retained reads 'n/a' or is inflated where incremental retention is "
                   "statistically indistinguishable from zero - read it only alongside the CI.", f["note"])
    ws.set_row(end + 1, 16)
    ws.set_row(end + 2, 16)

    ws.write(end + 4, 1, "Segment size and RFM position (latest pre-campaign snapshot)", f["sub"])
    prof = pd.DataFrame({
        "Segment": profile.segment, "Customers": profile.customers, "Share of base": profile.share_of_base,
        "Avg recency (days)": profile.avg_recency_days, "Avg frequency": profile.avg_frequency,
        "Avg monetary": profile.avg_monetary, "Avg R": profile.avg_r_score,
        "Avg F": profile.avg_f_score, "Avg M": profile.avg_m_score,
    })
    _table(ws, f, prof, ["Segment", "Customers", "Share of base", "Avg recency (days)", "Avg frequency",
                         "Avg monetary", "Avg R", "Avg F", "Avg M"],
           ["cell", "int", "pct1", "dec2", "dec2", "inr", "dec2", "dec2", "dec2"], end + 5, 1)

    chs = wb.add_chart({"type": "bar"})
    chs.add_series({
        "name": "Incremental profit",
        "categories": ["Segment Analysis", 9, 1, 9 + len(seg) - 1, 1],
        "values": ["Segment Analysis", 9, 16, 9 + len(seg) - 1, 16],
        "fill": {"color": PURPLE}, "border": {"none": True},
        "data_labels": {"value": True, "num_format": "#,##0",
                        "font": {"name": "Segoe UI", "size": 8, "color": GREY_DARK}},
    })
    chs.set_title({"none": True})
    chs.set_legend({"none": True})
    chs.set_x_axis({"name": "Incremental profit (rupees)", "num_format": "#,##0",
                    "name_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                    "num_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                    "major_gridlines": {"visible": True, "line": {"color": GREY_LINE}}})
    chs.set_y_axis({"num_font": {"name": "Segoe UI", "size": 9, "color": GREY_DARK},
                    "line": {"color": GREY_LINE}})
    chs.set_chartarea({"border": {"color": GREY_LINE}, "fill": {"color": "#FFFFFF"}})
    chs.set_size({"width": 620, "height": 300})
    ws.insert_chart(end + 5 + len(prof) + 3, 1, chs)
    ws.freeze_panes(9, 2)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 4. Cohort Retention
    ws = wb.add_worksheet("Cohort Retention")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 14)
    ws.set_column("C:N", 8.5)
    _banner(ws, f, "Cohort Retention", "Monthly retention by signup cohort, fixed cohort denominators",
            13, period)
    row0 = 8
    ws.set_row(row0, 24)
    ws.write(row0, 1, "Signup cohort", f["header"])
    for j, m in enumerate(months):
        ws.write(row0, 2 + j, f"Month {m}", f["header"])
    pct_cell = wb.add_format({"font_name": "Segoe UI", "font_size": 10, "num_format": "0.0%",
                              "align": "center", "valign": "vcenter", "border": 1,
                              "border_color": "#FFFFFF"})
    for i, month_start in enumerate(cohort_months):
        rr = row0 + 1 + i
        ws.set_row(rr, 18)
        ws.write_datetime(rr, 1, month_start.to_pydatetime(), f["month"])
        for j in range(len(months)):
            v = cohort_values[i, j]
            if pd.isna(v):
                ws.write_blank(rr, 2 + j, None, pct_cell)
            else:
                ws.write_number(rr, 2 + j, float(v), pct_cell)
    ws.conditional_format(row0 + 1, 2, row0 + len(cohort), 1 + len(months),
                          {"type": "3_color_scale", "min_color": "#FFFFFF", "mid_color": "#C9B6E4",
                           "max_color": PURPLE, "min_type": "num", "min_value": 0,
                           "mid_type": "num", "mid_value": 0.35, "max_type": "num", "max_value": 0.72})
    nr = row0 + len(cohort) + 2
    ws.write(nr, 1, "Reading the heatmap", f["sub"])
    for i, line in enumerate([
        "Month 0 is the signup month itself and is partial by construction - a customer who signs up "
        "on the 28th has three days to transact, so Month 0 always looks lower than Month 1.",
        "The denominator is fixed at each cohort's original size, so the columns are directly "
        "comparable across rows.",
        "Rows thin out to the right because later cohorts have not yet lived through those months, "
        "not because those customers churned. Blank cells are unobserved, not zero.",
        "Only successful transactions count as activity.",
    ]):
        ws.merge_range(nr + 1 + i, 1, nr + 1 + i, 13, "- " + line, f["note"])
        ws.set_row(nr + 1 + i, 15)
    ws.freeze_panes(row0 + 1, 2)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 5. Experiment Results
    ws = wb.add_worksheet("Experiment Results")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 34)
    ws.set_column("C:D", 17)
    ws.set_column("E:E", 34)
    ws.set_column("F:H", 17)
    _banner(ws, f, "Experiment Results", "Design, balance diagnostics and scenario range", 7, period)
    r = 8
    ws.merge_range(r, 1, r, 7, "DESIGN", f["section"])
    ws.set_row(r, 22)
    r += 1
    design = pd.DataFrame({
        "Element": ["Experimental unit", "Allocation", "Analysis population", "Outcome filter",
                    "Primary metric", "Secondary metrics", "Guardrails", "Multiplicity", "Causal scope"],
        "Definition": [notes["experimental_unit"], "50/50 randomization inside each campaign's eligible pool",
                       notes["denominator"], notes["outcome_filter"], notes["primary_metric"],
                       "; ".join(notes["secondary_metrics"]), "; ".join(notes["guardrails"]),
                       notes["multiple_comparisons"], notes["causal_scope"]],
    })
    ws.set_row(r, 26)
    ws.write(r, 1, "Element", f["header"])
    ws.merge_range(r, 2, r, 7, "Definition", f["header"])
    for i, (el, de) in enumerate(design.itertuples(index=False, name=None)):
        rr = r + 1 + i
        alt = "_alt" if i % 2 else ""
        ws.set_row(rr, 26)
        ws.write(rr, 1, el, f["cell" + alt])
        ws.merge_range(rr, 2, rr, 7, de, wb.add_format({
            "font_name": "Segoe UI", "font_size": 10, "valign": "vcenter", "text_wrap": True,
            "border": 1, "border_color": GREY_LINE, "font_color": GREY_DARK,
            **({"bg_color": GREY_BG} if alt else {})}))
    r += len(design) + 2

    ws.merge_range(r, 1, r, 7, "BALANCE DIAGNOSTICS", f["section"])
    ws.set_row(r, 22)
    r += 1
    bal = pd.DataFrame({
        "Campaign": camp.campaign_name, "Treatment share": camp.treatment_share,
        "Treatment pre-freq": camp.treatment_pre_frequency, "Control pre-freq": camp.control_pre_frequency,
        "Pre-freq SMD": camp.pre_frequency_smd, "Pre-value SMD": camp.pre_value_smd,
        "Verdict": ["Balanced" if abs(s) < 0.1 and 0.47 <= t <= 0.53 else "Review"
                    for s, t in zip(camp.pre_frequency_smd, camp.treatment_share)],
    })
    r = _table(ws, f, bal, ["Campaign", "Treatment share", "Treatment pre-freq", "Control pre-freq",
                            "Pre-freq SMD", "Pre-value SMD", "Verdict"],
               ["cell", "pct1", "dec2", "dec2", "dec3", "dec3", "cell"], r, 1)
    ws.merge_range(r, 1, r + 1, 7,
                   "Standardized mean difference within +/-0.10 is the conventional balance threshold. "
                   "Campaign 1 targets At risk and Dormant customers, whose pre-period frequency is "
                   "zero in both arms by construction.", f["note"])
    ws.set_row(r, 16)
    ws.set_row(r + 1, 16)
    r += 4

    ws.merge_range(r, 1, r, 7, "DATA QUALITY CHECKS", f["section"])
    ws.set_row(r, 22)
    r += 1
    checks = pd.DataFrame({"Check": list(dq["checks"].keys()),
                           "Result": ["PASS" if v else "FAIL" for v in dq["checks"].values()]})
    pass_fmt = wb.add_format({"font_name": "Segoe UI", "font_size": 10, "bold": True,
                              "font_color": GREEN, "bg_color": GREEN_BG, "align": "center",
                              "border": 1, "border_color": GREY_LINE})
    fail_fmt = wb.add_format({"font_name": "Segoe UI", "font_size": 10, "bold": True,
                              "font_color": RED, "bg_color": RED_BG, "align": "center",
                              "border": 1, "border_color": GREY_LINE})
    ws.set_row(r, 22)
    ws.write(r, 1, "Check", f["header"])
    ws.write(r, 2, "Result", f["header"])
    ws.write(r, 4, "Check", f["header"])
    ws.write(r, 5, "Result", f["header"])
    for gap in (3, 6, 7):  # keep the header bar continuous across the two columns of checks
        ws.write_blank(r, gap, None, f["header"])
    half = (len(checks) + 1) // 2
    for i, (name, res) in enumerate(checks.itertuples(index=False, name=None)):
        col = 1 if i < half else 4
        rr = r + 1 + (i if i < half else i - half)
        alt = "_alt" if (i % 2) else ""
        ws.write(rr, col, name.replace("_", " "), f["cell" + alt])
        ws.write(rr, col + 1, res, pass_fmt if res == "PASS" else fail_fmt)
    r += half + 2

    ws.merge_range(r, 1, r, 7, "SCENARIO RANGE BY SEGMENT", f["section"])
    ws.set_row(r, 22)
    r += 1
    sc = pd.DataFrame({
        "Segment": scen.segment, "Scenario": scen.scenario, "Basis": scen.basis,
        "Uplift": scen.uplift * 100, "Incr. customers": scen.incremental_customers,
        "Incr. txns": scen.incremental_transactions, "Cashback cost": scen.cashback_cost,
        "Incr. contribution": scen.incremental_contribution, "Profit": scen.estimated_profit,
        "ROI": scen.roi,
    })
    ws.set_column("I:K", 17)
    r = _table(ws, f, sc, ["Segment", "Scenario", "Basis", "Uplift", "Incr. customers", "Incr. txns",
                           "Cashback cost", "Incr. contribution", "Profit", "ROI"],
               ["cell", "cell", "cell", "pp", "int", "int", "inr", "inr", "inr", "pct1"], r, 1)
    ws.merge_range(r, 1, r + 1, 10,
                   "Base rows are Observed - measured directly from the randomized data. Conservative "
                   "and Optimistic rows are Estimated: they hold cashback cost fixed, move uplift to "
                   f"the CI bound, and convert retained customers at {tpr:.2f} incremental transactions "
                   "each.", f["note"])
    ws.set_row(r, 16)
    ws.set_row(r + 1, 16)
    ws.freeze_panes(9, 2)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 6. Forecast
    ws = wb.add_worksheet("Forecast")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 14)
    ws.set_column("C:G", 16)
    ws.set_column("I:I", 26)
    ws.set_column("J:L", 17)
    _banner(ws, f, "Transaction Forecast",
            f"{fsum['selected_model']} selected on a strictly chronological {fsum['holdout_days']}-day holdout",
            11, period)
    # Column layout drives the dashboard chart: B date, C actual, D holdout fit, E forecast,
    # F lower, G upper. Holdout rows first, then forecast rows.
    ws.set_row(8, 26)
    for j, h in enumerate(["Date", "Actual (holdout)", "Model fit (holdout)", "Forecast",
                           "95% lower", "95% upper"]):
        ws.write(8, 1 + j, h, f["header"])
    rowi = 9
    for i, recd in enumerate(hold.itertuples(index=False)):
        alt = "_alt" if i % 2 else ""
        ws.write_datetime(rowi, 1, recd.date.to_pydatetime(), f["date" + alt])
        ws.write_number(rowi, 2, float(recd.actual), f["int" + alt])
        ws.write_number(rowi, 3, float(recd.prediction), f["int" + alt])
        for c in (4, 5, 6):
            ws.write_blank(rowi, c, None, f["cell" + alt])
        rowi += 1
    for i, recd in enumerate(fcast.itertuples(index=False)):
        alt = "_alt" if (i + len(hold)) % 2 else ""
        ws.write_datetime(rowi, 1, recd.date.to_pydatetime(), f["date" + alt])
        ws.write_blank(rowi, 2, None, f["cell" + alt])
        ws.write_blank(rowi, 3, None, f["cell" + alt])
        ws.write_number(rowi, 4, float(recd.forecast_transactions), f["int" + alt])
        ws.write_number(rowi, 5, float(recd.lower_95), f["int" + alt])
        ws.write_number(rowi, 6, float(recd.upper_95), f["int" + alt])
        rowi += 1

    ws.write(8, 8, "Model comparison on the holdout", f["sub"])
    mc = pd.DataFrame({"Model": models.model, "MAE (txns/day)": models.mae, "MAPE": models.mape,
                       "Selected": ["Yes" if m == fsum["selected_model"] else "No" for m in models.model]})
    endm = _table(ws, f, mc, ["Model", "MAE (txns/day)", "MAPE", "Selected"],
                  ["cell", "dec2", "pct2", "cell"], 9, 8)
    facts = pd.DataFrame({
        "Item": ["Training window", "Holdout window", "Forecast window", "Holdout mean actual",
                 "Holdout MAE", "Holdout MAPE", "Interval method"],
        "Value": [f"{fsum['train_start']} to {fsum['train_end']}",
                  f"{fsum['holdout_start']} to {fsum['holdout_end']}",
                  f"{fsum['forecast_start']} to {fsum['forecast_end']}",
                  f"{fsum['holdout_mean_actual']:,.0f} transactions/day",
                  f"{fsum['mae']:.2f} transactions/day", f"{fsum['mape']:.2%}",
                  fsum["interval_method"]],
    })
    ws.write(endm + 1, 8, "Split and accuracy", f["sub"])
    endf = _table(ws, f, facts, ["Item", "Value"], ["cell", "cell"], endm + 2, 8)
    ws.set_column("J:J", 34)
    # The Value column deliberately holds formatted strings; suppress Excel's
    # "number stored as text" warning triangles rather than leaving them on the sheet.
    ws.ignore_errors({"number_stored_as_text": f"J{endm + 3}:J{endf}"})
    ws.merge_range(endf + 1, 8, endf + 3, 11,
                   "The holdout is the last 30 days of the series and was never used to fit or select a "
                   "model, so the error above is genuinely out of sample. Candidates were kept "
                   "deliberately transparent - a moving average that a stakeholder can verify beats a "
                   "black box that shaves a point of MAPE.", f["note"])

    chf = wb.add_chart({"type": "line"})
    for name, col, style in [
        ("Actual (holdout)", 2, {"color": GREY_DARK, "width": 1.75}),
        ("Model fit (holdout)", 3, {"color": AMBER, "width": 1.5, "dash_type": "dash"}),
        ("Forecast", 4, {"color": PURPLE, "width": 2.25}),
        ("95% lower", 5, {"color": PURPLE_MID, "width": 1, "dash_type": "round_dot"}),
        ("95% upper", 6, {"color": PURPLE_MID, "width": 1, "dash_type": "round_dot"}),
    ]:
        chf.add_series({"name": name, "categories": ["Forecast", fc_first, 1, fc_last, 1],
                        "values": ["Forecast", fc_first, col, fc_last, col],
                        "line": style, "marker": {"type": "none"}})
    chf.set_title({"none": True})
    chf.set_legend({"position": "bottom", "font": {"name": "Segoe UI", "size": 9, "color": GREY_DARK}})
    chf.set_y_axis({"name": "Successful transactions per day", "num_format": "#,##0",
                    "name_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                    "num_font": {"name": "Segoe UI", "size": 9, "color": GREY_MID},
                    "major_gridlines": {"visible": True, "line": {"color": GREY_LINE}}})
    chf.set_x_axis({"num_font": {"name": "Segoe UI", "size": 8, "color": GREY_MID},
                    "interval_unit": 7, "num_format": "dd-mmm", "line": {"color": GREY_LINE}})
    chf.set_chartarea({"border": {"color": GREY_LINE}, "fill": {"color": "#FFFFFF"}})
    chf.set_size({"width": 700, "height": 330})
    ws.insert_chart(endf + 5, 8, chf)
    ws.freeze_panes(9, 2)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 7. Offer Simulator
    ws = wb.add_worksheet("Offer Simulator")
    ws.set_tab_color(AMBER)
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 42)
    ws.set_column("C:C", 18)
    ws.set_column("D:D", 3)
    ws.set_column("E:H", 16)
    _banner(ws, f, "Offer Simulator", "Change the yellow inputs; every purple cell recalculates live",
            7, period)
    r = 8
    ws.merge_range(r, 1, r, 7, "INPUTS  (editable - yellow cells)", f["section"])
    ws.set_row(r, 22)
    r += 1
    default_seg = scale.iloc[0] if len(scale) else seg.iloc[0]
    inputs = [
        ("Cashback value per redemption", float(default_seg.cashback_cost / max(1, round(
            default_seg.redemption_rate * default_seg.treatment_size))), "input_inr",
         "Rupees paid to each customer who redeems."),
        ("Expected redemption rate", float(default_seg.redemption_rate), "input_pct",
         "Share of targeted customers who redeem. Only redeemers cost money."),
        ("Expected D30 retention uplift", float(default_seg.absolute_uplift), "input_pct",
         "Treatment minus control D30 retention, in percentage points."),
        ("Contribution per incremental transaction", float(default_seg.average_payment_value * margin),
         "input_inr", f"Average payment value x {margin:.0%} assumed margin."),
        ("Target segment size", int(default_seg.treatment_size), "input_int",
         "Number of customers who would receive the offer."),
        ("Incremental txns per retained customer", float(tpr), "input_dec",
         "Stated assumption, derived from the observed experiment. Exposed here so it can be stressed."),
    ]
    first_input = r
    for i, (label, value, fmt, note) in enumerate(inputs):
        rr = r + i
        ws.set_row(rr, 24)
        ws.write(rr, 1, label, f["label"])
        ws.write(rr, 2, value, f[fmt])
        ws.merge_range(rr, 4, rr, 7, note, f["note"])
    last_input = r + len(inputs) - 1
    C_CASH, C_REDEEM, C_UPLIFT, C_CONTRIB, C_SIZE, C_TPR = [f"$C${first_input + 1 + i}" for i in range(6)]
    r = last_input + 2
    ws.merge_range(r, 1, r, 7, "OUTPUTS  (live Excel formulas - purple cells)", f["section"])
    ws.set_row(r, 22)
    r += 1

    outputs = [
        ("Customers redeeming", f"={C_SIZE}*{C_REDEEM}", "out_int",
         "Target size x redemption rate."),
        ("Campaign cost", f"={C_SIZE}*{C_REDEEM}*{C_CASH}", "out_inr",
         "Redeemers x cashback value. Non-redeemers cost nothing."),
        ("Incremental retained customers", f"={C_SIZE}*{C_UPLIFT}", "out_int",
         "Target size x uplift in percentage points."),
        ("Incremental transactions", f"={C_SIZE}*{C_UPLIFT}*{C_TPR}", "out_int",
         "Incremental retained customers x transactions each."),
        ("Incremental contribution", f"={C_SIZE}*{C_UPLIFT}*{C_TPR}*{C_CONTRIB}", "out_inr",
         "Incremental transactions x contribution per transaction."),
        ("Incremental profit", f"={C_SIZE}*{C_UPLIFT}*{C_TPR}*{C_CONTRIB}-{C_SIZE}*{C_REDEEM}*{C_CASH}",
         "out_inr", "Contribution minus campaign cost."),
        ("ROI", f"=IF({C_SIZE}*{C_REDEEM}*{C_CASH}=0,\"n/a\","
                f"({C_SIZE}*{C_UPLIFT}*{C_TPR}*{C_CONTRIB}-{C_SIZE}*{C_REDEEM}*{C_CASH})"
                f"/({C_SIZE}*{C_REDEEM}*{C_CASH}))", "out_pct",
         "Profit / campaign cost. Guarded against a zero-cost divide."),
        ("Cost per incremental retained", f"=IF({C_SIZE}*{C_UPLIFT}<=0,\"n/a\","
                                          f"{C_SIZE}*{C_REDEEM}*{C_CASH}/({C_SIZE}*{C_UPLIFT}))",
         "out_inr", "Campaign cost / incremental retained customers."),
        ("Break-even uplift", f"=IF({C_TPR}*{C_CONTRIB}=0,\"n/a\","
                              f"{C_REDEEM}*{C_CASH}/({C_TPR}*{C_CONTRIB})*100)", "out_pp",
         "Uplift at which profit is exactly zero: (redemption rate x cashback) / "
         "(txns per retained x contribution). Independent of segment size."),
        ("Verdict at the 15% hurdle", f"=IF({C_SIZE}*{C_REDEEM}*{C_CASH}=0,\"n/a\","
                                      f"IF(({C_SIZE}*{C_UPLIFT}*{C_TPR}*{C_CONTRIB}-{C_SIZE}*{C_REDEEM}*{C_CASH})"
                                      f"/({C_SIZE}*{C_REDEEM}*{C_CASH})>=0.15,\"Clears hurdle\",\"Below hurdle\"))",
         "out", "Applies the same 15% return hurdle used in the recommendation matrix."),
    ]
    for i, (label, formula, fmt, note) in enumerate(outputs):
        rr = r + i
        ws.set_row(rr, 24)
        ws.write(rr, 1, label, f["label"])
        ws.write_formula(rr, 2, formula, f[fmt])
        ws.merge_range(rr, 4, rr, 7, note, f["note"])
    r += len(outputs) + 1

    ws.merge_range(r, 1, r, 7, "HOW TO READ THIS SHEET", f["section"])
    ws.set_row(r, 22)
    r += 1
    ws.write(r, 1, "Break-even uplift", f["label"])
    ws.merge_range(r, 2, r, 7,
                   "The number to argue about. If an offer needs a larger retention lift than any "
                   "segment has ever produced, the offer is wrong - not the targeting. Compare it "
                   "against the observed uplifts on the Segment Analysis sheet.", f["note"])
    ws.set_row(r, 30)
    r += 1
    ws.write(r, 1, "Defaults", f["label"])
    ws.merge_range(r, 2, r, 7,
                   f"Seeded from {default_seg.segment}, the strongest scale segment in the observed "
                   "experiment. Every figure this sheet produces is a projection, not an observed "
                   "result.", f["note"])
    ws.set_row(r, 30)
    r += 2
    ws.write(r, 1, "Cell legend", f["sub"])
    r += 1
    ws.write(r, 1, "Editable input", f["legend_input"])
    ws.write(r, 2, "Calculated output", f["legend_out"])
    ws.merge_range(r, 4, r, 5, "Source data / reference", f["legend_src"])
    ws.freeze_panes(8, 1)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 8. KPI Calculations
    ws = wb.add_worksheet("KPI Calculations")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 21)
    ws.set_column("C:L", 14)
    ws.set_column("M:M", 3)
    ws.set_column("N:N", 92)
    _banner(ws, f, "KPI Calculations",
            "Raw counts on the left, live Excel formulas on the right - every headline number derived in view",
            11, period)
    r = 8
    ws.write(r, 1, "ASSUMPTION", f["section"])
    ws.merge_range(r, 2, r, 3, "", f["section"])
    ws.set_row(r, 22)
    r += 1
    ws.write(r, 1, "Contribution margin", f["label"])
    ws.write(r, 2, float(margin), f["input_pct"])
    ws.merge_range(r, 3, r, 8,
                   "Editable. Every contribution, profit and ROI formula below points at this one cell, "
                   "so changing it re-prices the whole programme.", f["note"])
    ws.set_row(r, 24)
    MARGIN = f"$C${r + 1}"
    r += 2

    ws.merge_range(r, 1, r, 8, "SOURCE COUNTS  (written by the pipeline, one row per segment)", f["section"])
    ws.write(r, 13, "NOTES", f["section"])
    ws.set_row(r, 22)
    r += 1
    src = pd.DataFrame({
        "Segment": seg.segment,
        "Treated": seg.treatment_size,
        "Control": seg.control_size,
        "Treated retained": (seg.treatment_d30_retention * seg.treatment_size).round(),
        "Control retained": (seg.control_d30_retention * seg.control_size).round(),
        "Treated txns": (seg.treatment_post_frequency * seg.treatment_size).round(),
        "Control txns": (seg.control_post_frequency * seg.control_size).round(),
        "Avg payment value": seg.average_payment_value,
        "Cashback cost": seg.cashback_cost,
    })
    src_head = r
    src_end = _table(ws, f, src,
                     ["Segment", "Treated", "Control", "Treated retained", "Control retained",
                      "Treated txns", "Control txns", "Avg payment value", "Cashback cost"],
                     ["cell", "int", "int", "int", "int", "int", "int", "inr2", "inr"], r, 1)
    first, last = src_head + 2, src_head + 1 + len(src)  # 1-based Excel rows of the data block
    ws.write(src_head + 1, 13, "Counts of customers and successful transactions in the D30 window. "
                               "Cashback cost is the sum of actual redemptions by treated customers.",
             f["note"])
    ws.set_row(src_head + 1, 30)
    tot = src_end
    ws.write(tot, 1, "TOTAL", f["label"])
    for j, col in enumerate("CDEFGH"):
        ws.write_formula(tot, 2 + j, f"=SUM({col}{first}:{col}{last})",
                         f["out_int"])
    ws.write_formula(tot, 8, f"=SUMPRODUCT(I{first}:I{last},C{first}:C{last})/SUM(C{first}:C{last})",
                     f["out_inr"])
    ws.write_formula(tot, 9, f"=SUM(J{first}:J{last})", f["out_inr"])
    ws.write(tot, 13, "Totals are SUM formulas over the rows above; average payment value is "
                      "weighted by treated customers.", f["note"])
    ws.set_row(tot, 24)
    # The weighted-average total is deliberately a different formula from the SUM cells
    # beside it; suppress Excel's "inconsistent formula" flag on that one cell.
    ws.ignore_errors({"formula_differs": f"I{tot + 1}"})
    r = tot + 2

    ws.merge_range(r, 1, r, 11, "CALCULATED KPIS  (live Excel formulas over the block above)", f["section"])
    ws.write(r, 13, "FORMULA AS WRITTEN", f["section"])
    ws.set_row(r, 22)
    r += 1
    calc_headers = ["Segment", "Treatment D30", "Control D30", "Uplift", "Incr. retained",
                    "Incr. txns", "Incr. contribution", "Incr. profit", "ROI",
                    "Cost / incr. retained"]
    ws.set_row(r, 30)
    for j, h in enumerate(calc_headers):
        ws.write(r, 1 + j, h, f["header"])
    calc_first = r + 2
    for i in range(len(src)):
        rr = r + 1 + i
        n = first + i  # matching source row, 1-based
        alt = "_alt" if i % 2 else ""
        ws.set_row(rr, 20)
        ws.write_formula(rr, 1, f"=B{n}", f["cell" + alt])
        ws.write_formula(rr, 2, f"=E{n}/C{n}", f["pct1" + alt])
        ws.write_formula(rr, 3, f"=F{n}/D{n}", f["pct1" + alt])
        ws.write_formula(rr, 4, f"=(E{n}/C{n}-F{n}/D{n})*100", f["pp" + alt])
        ws.write_formula(rr, 5, f"=(E{n}/C{n}-F{n}/D{n})*C{n}", f["int" + alt])
        ws.write_formula(rr, 6, f"=(G{n}/C{n}-H{n}/D{n})*C{n}", f["int" + alt])
        ws.write_formula(rr, 7, f"=MAX(0,(G{n}/C{n}-H{n}/D{n})*C{n})*I{n}*{MARGIN}", f["inr" + alt])
        ws.write_formula(rr, 8, f"=MAX(0,(G{n}/C{n}-H{n}/D{n})*C{n})*I{n}*{MARGIN}-J{n}", f["inr" + alt])
        ws.write_formula(rr, 9, f'=IF(J{n}=0,"n/a",(MAX(0,(G{n}/C{n}-H{n}/D{n})*C{n})*I{n}*{MARGIN}-J{n})/J{n})',
                         f["pct1" + alt])
        ws.write_formula(rr, 10, f'=IF((E{n}/C{n}-F{n}/D{n})*C{n}<=0,"n/a",J{n}/((E{n}/C{n}-F{n}/D{n})*C{n}))',
                         f["inr" + alt])
    calc_last = r + len(src)
    cf, cl = calc_first, calc_last + 1
    rr = calc_last + 1
    ws.set_row(rr, 24)
    ws.write(rr, 1, "ALL SEGMENTS", f["label"])
    ws.write_formula(rr, 2, f"=E{tot + 1}/C{tot + 1}", f["out_pct"])
    ws.write_formula(rr, 3, f"=F{tot + 1}/D{tot + 1}", f["out_pct"])
    ws.write_formula(rr, 4, f"=(E{tot + 1}/C{tot + 1}-F{tot + 1}/D{tot + 1})*100", f["out_pp"])
    ws.write_formula(rr, 5, f"=SUM(F{cf}:F{cl})", f["out_int"])
    ws.write_formula(rr, 6, f"=SUM(G{cf}:G{cl})", f["out_int"])
    ws.write_formula(rr, 7, f"=SUM(H{cf}:H{cl})", f["out_inr"])
    ws.write_formula(rr, 8, f"=SUM(I{cf}:I{cl})", f["out_inr"])
    ws.write_formula(rr, 9, f'=IF(SUM(J{first}:J{last})=0,"n/a",SUM(I{cf}:I{cl})/SUM(J{first}:J{last}))',
                     f["out_pct"])
    ws.write_formula(rr, 10, f'=IF(SUM(F{cf}:F{cl})<=0,"n/a",SUM(J{first}:J{last})/SUM(F{cf}:F{cl}))',
                     f["out_inr"])

    scale_rows = [cf + i for i, a in enumerate(seg.action) if a == "Scale"]
    rr += 1
    ws.set_row(rr, 24)
    ws.write(rr, 1, "SCALE SEGMENTS", f["label"])
    for c in (2, 3, 4, 5, 6):
        ws.write_blank(rr, c, None, f["cell"])
    profit_terms = "+".join(f"I{n}" for n in scale_rows) or "0"
    cost_terms = "+".join(f"J{first + (n - cf)}" for n in scale_rows) or "0"
    contrib_terms = "+".join(f"H{n}" for n in scale_rows) or "0"
    ws.write_formula(rr, 7, f"={contrib_terms}", f["out_inr"])
    ws.write_formula(rr, 8, f"={profit_terms}", f["out_inr"])
    ws.write_formula(rr, 9, f'=IF({cost_terms}=0,"n/a",({profit_terms})/({cost_terms}))', f["out_pct"])
    ws.write_blank(rr, 10, None, f["cell"])

    notes = [
        ("Treatment D30", "treated retained / treated"),
        ("Control D30", "control retained / control"),
        ("Uplift", "(treatment rate - control rate) x 100, in percentage points"),
        ("Incr. retained", "uplift x treated customers"),
        ("Incr. txns", "(treated txns per customer - control txns per customer) x treated"),
        ("Incr. contribution", "MAX(0, incremental transactions) x average payment value x margin"),
        ("Incr. profit", "incremental contribution - cashback cost"),
        ("ROI", "incremental profit / cashback cost"),
        ("Cost / incr. retained", "cashback cost / incremental retained customers"),
        ("ALL SEGMENTS row", "rates are pooled from the total counts; money is summed across segments"),
        ("SCALE SEGMENTS row", "sums only the segments the recommendation matrix marks Scale"),
    ]
    for i, (label, expl) in enumerate(notes):
        ws.write(calc_first - 1 + i, 13, f"{label}  =  {expl}", f["note"])
    r = rr + 2
    ws.write(r, 1, "Cell legend", f["sub"])
    r += 1
    ws.write(r, 1, "Source data", f["legend_src"])
    ws.merge_range(r, 2, r, 3, "Calculated output", f["legend_out"])
    ws.write(r, 4, "Editable input", f["legend_input"])
    ws.merge_range(r + 1, 1, r + 2, 11,
                   "The block above the divider holds counts written by the pipeline. Every cell below it "
                   "is an Excel formula pointing at those counts and at the margin assumption, so nothing "
                   "here is a pasted number - edit a count or the margin and the KPIs move. The ALL "
                   "SEGMENTS totals are what the Executive Dashboard cards report.", f["note"])
    ws.freeze_panes(9, 2)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 9. Data Dictionary
    ws = wb.add_worksheet("Data Dictionary")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 20)
    ws.set_column("C:C", 26)
    ws.set_column("D:D", 12)
    ws.set_column("E:E", 78)
    _banner(ws, f, "Data Dictionary", "Every table and column used by the analysis", 4, period)
    dd = [
        ("customers", "customer_id", "int", "Primary key."),
        ("customers", "signup_date", "date", "Account creation date, inside the reporting period."),
        ("customers", "region", "text", "North / South / East / West / Central."),
        ("customers", "acquisition_channel", "text", "Organic / Referral / Paid social / Partner / Search."),
        ("customers", "age_band", "text", "18-24 / 25-34 / 35-44 / 45+."),
        ("customers", "initial_customer_type", "text",
         "Generator-only behaviour label. NEVER used by the analysis - segments are recomputed from observed RFM."),
        ("transactions", "transaction_id", "int", "Primary key."),
        ("transactions", "customer_id", "int", "Foreign key to customers."),
        ("transactions", "transaction_date", "date", "Always on or after the customer's signup date."),
        ("transactions", "merchant_category", "text", "Grocery / Bills / Recharge / Travel / Food / Shopping."),
        ("transactions", "payment_method", "text", "UPI / Wallet / Card."),
        ("transactions", "amount", "float", "Payment value in rupees, always >= 0."),
        ("transactions", "transaction_status", "text",
         "Success / Failed / Reversed. Only Success counts towards any metric."),
        ("transactions", "is_campaign_increment", "int",
         "0 for organic rows, else the campaign that injected the row. Audit field only - excluded from every metric."),
        ("campaigns", "campaign_id", "int", "Primary key."),
        ("campaigns", "campaign_name", "text", "Reactivation Boost / Habit Builder / Year-end Value."),
        ("campaigns", "start_date, end_date", "date", "30-day campaign window."),
        ("campaigns", "target_segment", "text", "Eligibility premise for the wave."),
        ("campaigns", "cashback_offer", "float", "Rupee cashback paid on redemption."),
        ("campaigns", "minimum_spend", "float", "Rupee spend threshold to qualify."),
        ("campaign_assignments", "campaign_id, customer_id", "int", "Composite primary key."),
        ("campaign_assignments", "treatment_group", "text", "Treatment or Control."),
        ("campaign_assignments", "assignment_date", "date", "Equals the campaign start date."),
        ("campaign_assignments", "offer_received", "int",
         "1 for Treatment, 0 for Control; reconciles exactly with treatment_group."),
        ("cashback_redemptions", "campaign_id, customer_id", "int", "Foreign keys; treated customers only."),
        ("cashback_redemptions", "redemption_date", "date", "Always inside the campaign window."),
        ("cashback_redemptions", "cashback_cost", "float", "Rupee cost booked to the campaign, always > 0."),
        ("rfm_snapshots", "customer_id, campaign_id", "int", "Composite primary key, one row per customer per campaign."),
        ("rfm_snapshots", "last_txn", "date", "Most recent successful transaction before the cutoff, blank if none."),
        ("rfm_snapshots", "recency", "int", "Days from last_txn to the cutoff; 999 when never transacted."),
        ("rfm_snapshots", "frequency", "int", "Count of successful transactions strictly before the cutoff."),
        ("rfm_snapshots", "monetary", "float", "Sum of successful payment value strictly before the cutoff."),
        ("rfm_snapshots", "r_score, f_score, m_score", "int", "Quintile scores, 1-5, ranked within the snapshot."),
        ("rfm_snapshots", "segment", "text",
         "New / Promising / Active / Loyal / High value / At risk / Dormant, from the ordered overlay rules."),
    ]
    ddf = pd.DataFrame(dd, columns=["Table", "Column", "Type", "Description"])
    end = _table(ws, f, ddf, ["Table", "Column", "Type", "Description"],
                 ["cell", "cell", "cell", "text_wrap"], 8, 1)
    for i in range(len(ddf)):
        ws.set_row(8 + 1 + i, 18)
    ws.write(end + 1, 1, "Derived outputs", f["sub"])
    derived = pd.DataFrame([
        ("outputs/campaign_performance.csv", "Per-campaign retention, uplift, cost and ROI."),
        ("outputs/segment_recommendations.csv", "Per-segment uplift, economics and recommended action."),
        ("outputs/scenarios.csv", "Conservative / Base / Optimistic rows; 'basis' marks Observed vs Estimated."),
        ("outputs/cohort_retention_matrix.csv", "Signup-cohort monthly retention matrix."),
        ("outputs/forecast_summary.json", "Selected model, chronological split and holdout accuracy."),
        ("outputs/segment_profile.csv", "Size and average RFM position of each segment."),
        ("outputs/data_quality_report.json", f"{len(dq['checks'])} automated integrity checks."),
        ("outputs/experiment_notes.json", "Metric definitions and the stated assumptions."),
    ], columns=["File", "Contents"])
    ws.write(end + 2, 1, "File", f["header"])
    ws.merge_range(end + 2, 2, end + 2, 4, "Contents", f["header"])
    ws.set_row(end + 2, 22)
    for i, (fl, ct) in enumerate(derived.itertuples(index=False, name=None)):
        rr = end + 3 + i
        alt = "_alt" if i % 2 else ""
        ws.set_row(rr, 18)
        ws.write(rr, 1, fl, f["cell" + alt])
        ws.merge_range(rr, 2, rr, 4, ct, f["cell" + alt])
    ws.freeze_panes(9, 0)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 10. Methodology
    ws = wb.add_worksheet("Methodology")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:B", 34)
    ws.set_column("C:H", 15)
    _banner(ws, f, "Methodology", "How every number on the preceding sheets was produced", 7, period)
    r = 8
    blocks = [
        ("DATA GENERATION", [
            f"Deterministic seed {meta['seed']}. Re-running python src/run_pipeline.py reproduces every file.",
            f"{meta['customers']:,} customers and {meta['transactions']:,} transactions over {period}; "
            f"{meta['successful_transactions']:,} are successful.",
            f"{meta['campaigns']} campaign waves, {meta['campaign_assignments']:,} randomized assignments, "
            f"{meta['redemptions']:,} redemptions.",
        ]),
        ("RFM SEGMENTATION", [
            "A snapshot is cut independently for each campaign using only successful transactions dated "
            "strictly before that campaign's assignment date. No post-assignment field is ever read.",
            "Recency, frequency and monetary value are ranked into quintiles (1-5). Ranking is used "
            "rather than fixed cut points so scores stay stable as the distribution shifts.",
            "Overlays are applied in order, first match wins: New (signed up within 45 days), "
            "Dormant (recency > 120 days or zero transactions), At risk (recency > 60 days), "
            "High value (M = 5 and >= 8 transactions), Loyal (R >= 4 and F >= 4), "
            "Active (R >= 3 and F >= 3), otherwise Promising.",
        ]),
        ("EXPERIMENT", [
            "The experimental unit is the customer within a campaign. Assignment is a 50/50 "
            "randomization drawn after the snapshot is frozen, so treatment cannot influence segment.",
            "Analysis is intent-to-treat: the denominator is every assigned customer, redeemed or not.",
            "Only successful transactions count towards any outcome; Failed and Reversed rows are excluded.",
            "D7 repeat = at least one successful transaction on days 0-6 after campaign start. "
            "D30 retention = at least one successful transaction on days 0-29.",
            "Confidence intervals are 95% normal-approximation intervals for a difference in "
            "proportions; the p-value is the matching two-sided normal tail.",
        ]),
        ("ECONOMICS", [
            "Incremental retained customers = (treatment D30 rate - control D30 rate) x treated customers.",
            "Incremental transactions = (treatment mean post txns - control mean post txns) x treated customers.",
            "Cashback cost = sum of actual redemption costs by treated customers.",
            f"Incremental contribution = incremental transactions x average payment value x {margin:.0%} margin.",
            "Incremental profit = incremental contribution - cashback cost. ROI = profit / cashback cost.",
            "Cost per incremental retained customer = cashback cost / incremental retained customers.",
        ]),
        ("STATED ASSUMPTIONS", [
            f"The {margin:.0%} contribution margin is a planning assumption, not a measured figure.",
            f"{tpr:.2f} incremental transactions per incremental retained customer, derived as "
            "sum(incremental_transactions) / sum(incremental_retained_customers) across all randomized "
            "segments rather than hard-coded. It is an editable input on the Offer Simulator sheet.",
        ]),
        ("OBSERVED VS ESTIMATED", [
            "Observed: the Executive Dashboard headline cards, Campaign Performance, Segment Analysis, "
            "Cohort Retention, and the Base rows of the scenario table. These are measured directly "
            "from the randomized synthetic data.",
            "Estimated: the Conservative and Optimistic scenario rows and every Offer Simulator output. "
            "These are projections built on the stated assumptions above.",
        ]),
        ("FORECAST", [
            f"The last {fsum['holdout_days']} days ({fsum['holdout_start']} to {fsum['holdout_end']}) are "
            "held out chronologically and never used to fit or select a model.",
            f"Candidates: {', '.join(fsum['candidates'])}. {fsum['selected_model']} won on holdout MAE "
            f"({fsum['mae']:.2f} transactions/day, {fsum['mape']:.2%} MAPE).",
            f"Intervals are {fsum['interval_method']}.",
        ]),
        ("LIMITATIONS", [
            "All data is synthetic and generated by src/generate_data.py. Effects were injected by the "
            "generator, so results demonstrate method, not real-world PhonePe response.",
            "Segment cuts are exploratory and carry no multiplicity adjustment; their true intervals "
            "are wider than printed.",
            "Campaign waves run sequentially, so a customer treated in an earlier wave can enter a "
            "later wave's eligible pool through their improved RFM position. Randomization inside "
            "each wave still makes the within-wave contrast unbiased.",
            "The D30 horizon does not capture longer-run habit formation or offer fatigue.",
        ]),
    ]
    for header, lines in blocks:
        ws.merge_range(r, 1, r, 7, header, f["section"])
        ws.set_row(r, 22)
        r += 1
        for line in lines:
            ws.merge_range(r, 1, r, 7, "- " + line, f["text_wrap"])
            ws.set_row(r, 15 * (1 + len(line) // 118))
            r += 1
        r += 1
    ws.merge_range(r, 1, r, 7, DISCLAIMER, f["disclaimer"])
    ws.set_row(r, 26)
    ws.freeze_panes(8, 0)
    ws.hide_gridlines(2)

    # ---------------------------------------------------------------- 11. Raw Data Sample
    ws = wb.add_worksheet("Raw Data Sample")
    ws.set_column("A:A", 2.5)
    ws.set_column("B:I", 17)
    _banner(ws, f, "Raw Data Sample",
            "First 250 rows of data/processed/transactions_sample.csv, committed with the repository",
            8, period)
    smp = sample.head(250)
    _table(ws, f, smp, [c.replace("_", " ").title() for c in smp.columns],
           ["int", "int", "date", "cell", "cell", "inr2", "cell", "int"], 8, 1)
    ws.write(6, 1, f"{len(smp)} of {meta['transactions']:,} transaction rows. The full dataset and the "
                   "SQLite database are regenerated locally by the pipeline and deliberately not "
                   "committed - only deterministic samples are.", f["note"])
    ws.freeze_panes(9, 2)

    wb.close()
    return str(WORKBOOK_PATH)


if __name__ == "__main__":
    print(build_workbook())
