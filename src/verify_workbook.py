"""Audit the generated workbook and render presentation sheets to images.

The workbook is written by XlsxWriter and read back here by **openpyxl**, so the
file is produced and verified by two independent libraries. Where Microsoft Excel
is available the workbook is additionally opened through COM, which forces a full
recalculation - that is the only way to prove the formula cells evaluate to real
values rather than to #REF!, #VALUE!, #DIV/0!, #NAME? or #N/A.

Run directly:  python src/verify_workbook.py
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from openpyxl import load_workbook

from config import OUTPUT_DIR

WORKBOOK_PATH = OUTPUT_DIR / "cashback_retention_dashboard.xlsx"
PREVIEW_PATH = OUTPUT_DIR / "dashboard_preview.png"
RENDER_DIR = OUTPUT_DIR / "charts"
REPORT_PATH = OUTPUT_DIR / "workbook_verification.json"

REQUIRED_SHEETS = ["Executive Dashboard", "Campaign Performance", "Segment Analysis",
                   "Cohort Retention", "Experiment Results", "Forecast", "Offer Simulator",
                   "KPI Calculations", "Data Dictionary", "Methodology", "Raw Data Sample"]
EXCEL_ERRORS = ("#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A", "#NULL!", "#NUM!")
DISCLAIMER_KEY = "Not affiliated with or based on internal data from PhonePe"
VISUAL_SHEETS = ["Executive Dashboard", "Offer Simulator", "Segment Analysis",
                 "Cohort Retention", "Forecast", "KPI Calculations", "Experiment Results",
                 "Campaign Performance"]


def audit_static(path: Path = WORKBOOK_PATH) -> dict:
    """Structural audit of the written file: sheets, population, formulas, charts, errors."""
    wb = load_workbook(path)
    report: dict = {"workbook": str(path), "sheets": {}, "problems": []}
    report["sheet_order"] = wb.sheetnames

    missing = [s for s in REQUIRED_SHEETS if s not in wb.sheetnames]
    if missing:
        report["problems"].append(f"missing sheets: {missing}")
    if wb.sheetnames[:len(REQUIRED_SHEETS)] != REQUIRED_SHEETS:
        report["problems"].append(f"sheet order is {wb.sheetnames}, expected {REQUIRED_SHEETS}")

    for name in wb.sheetnames:
        ws = wb[name]
        non_empty = formulas = 0
        errors: list[str] = []
        text_blob: list[str] = []
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if v is None or v == "":
                    continue
                non_empty += 1
                if isinstance(v, str):
                    text_blob.append(v)
                    if v.startswith("="):
                        formulas += 1
                    for err in EXCEL_ERRORS:
                        if err in v:
                            errors.append(f"{cell.coordinate}: {v[:60]}")
        placeholders = [t for t in text_blob
                        if any(k in t for k in ("TODO", "FIXME", "TBD", "Lorem ipsum", "PLACEHOLDER"))]
        report["sheets"][name] = {
            "non_empty_cells": non_empty,
            "formula_cells": formulas,
            "charts": len(getattr(ws, "_charts", [])),
            "conditional_formats": len(list(ws.conditional_formatting)),
            "freeze_panes": ws.freeze_panes,
            "gridlines_hidden": not ws.sheet_view.showGridLines,
            "has_disclaimer": any(DISCLAIMER_KEY in t for t in text_blob),
            "excel_errors": errors,
            "placeholders": placeholders,
        }
        if non_empty == 0:
            report["problems"].append(f"{name}: sheet is empty")
        if errors:
            report["problems"].append(f"{name}: {len(errors)} Excel error strings")
        if placeholders:
            report["problems"].append(f"{name}: placeholder text {placeholders[:3]}")

    for name in ("Offer Simulator", "KPI Calculations"):
        if report["sheets"].get(name, {}).get("formula_cells", 0) < 8:
            report["problems"].append(f"{name}: expected live formulas, found "
                                      f"{report['sheets'].get(name, {}).get('formula_cells', 0)}")
    if report["sheets"].get("Executive Dashboard", {}).get("charts", 0) < 3:
        report["problems"].append("Executive Dashboard: expected at least 3 charts")
    if not report["sheets"].get("Executive Dashboard", {}).get("has_disclaimer"):
        report["problems"].append("Executive Dashboard: disclaimer missing")

    # Chart series must point at ranges that actually hold data.
    for name in wb.sheetnames:
        for ci, chart in enumerate(getattr(wb[name], "_charts", [])):
            for si, series in enumerate(chart.series):
                ref = getattr(getattr(series.val, "numRef", None), "f", None)
                if not ref:
                    report["problems"].append(f"{name}: chart {ci} series {si} has no value range")
                    continue
                sheet_ref = ref.split("!")[0].strip("'")
                if sheet_ref not in wb.sheetnames:
                    report["problems"].append(f"{name}: chart {ci} series {si} points at "
                                              f"unknown sheet {sheet_ref}")
                    continue
                span = ref.split("!")[1].replace("$", "")
                lo, hi = (span.split(":") + [span])[:2]
                target = wb[sheet_ref]
                populated = sum(1 for row in target[f"{lo}:{hi}"] for c in row
                                if c.value is not None and c.value != "")
                if populated == 0:
                    report["problems"].append(f"{name}: chart {ci} series {si} range {ref} is empty")
    wb.close()
    return report


def _excel_app():
    """Return a hidden Excel COM application, or None when Excel is unavailable."""
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        try:
            import comtypes.client as cc
            app = cc.CreateObject("Excel.Application")
        except Exception:
            return None, None
        app.Visible = False
        app.DisplayAlerts = False
        return app, "comtypes"
    import win32com.client
    try:
        app = win32com.client.DispatchEx("Excel.Application")
    except Exception:
        return None, None
    app.Visible = False
    app.DisplayAlerts = False
    return app, "win32com"


def _copy_picture(rng) -> None:
    """Copy a range to the clipboard as a picture.

    Excel intermittently refuses the first CopyPicture issued after a full recalculation,
    so retry briefly and fall back from bitmap to the metafile format before giving up.
    """
    last_error: Exception | None = None
    for fmt in (2, -4147):  # xlBitmap, then xlPicture
        for _ in range(3):
            try:
                rng.CopyPicture(1, fmt)  # xlScreen appearance
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.5)
    raise last_error


def _export_block(wb, ws, first_row: int, last_row: int, last_col: int, target: Path) -> None:
    """Export one horizontal band of a sheet to PNG.

    The picture is pasted into a chart canvas sized to the range itself. Sizing matters:
    a default-sized canvas leaves the chart's own empty axes visible around the paste,
    which would put a phantom chart into the QA images.
    """
    rng = ws.Range(ws.Cells(first_row, 1), ws.Cells(last_row, last_col))
    # A chart sheet scales the pasted picture to fill it, which a fixed-size ChartObject does
    # not. But Charts.Add() builds a series from the current selection, and that chart's axes
    # then show through behind the paste. Parking the selection on an empty cell far outside
    # the data gives Excel nothing to plot, so the canvas starts blank.
    ws.Activate()
    ws.Cells(1, 250).Select()
    _copy_picture(rng)
    chart = wb.Charts.Add()
    try:
        chart.ChartArea.Border.LineStyle = -4142  # xlNone
        chart.Paste()
        chart.Export(str(target.resolve()), "PNG")
    finally:
        chart.Delete()


def _render_sheet(wb, sheet_name: str, target: Path, max_rows_per_block: int = 45) -> None:
    """Render a whole sheet to one PNG, stitching bands when the range is too tall.

    Excel's CopyPicture fails outright on very large ranges, so tall sheets are captured
    in bands and joined vertically with Pillow.
    """
    ws = wb.Worksheets(sheet_name)
    ws.Activate()
    used = ws.UsedRange
    last_row = used.Row + used.Rows.Count - 1
    last_col = used.Column + used.Columns.Count - 1
    if last_row <= max_rows_per_block:
        _export_block(wb, ws, 1, last_row, last_col, target)
        return

    from PIL import Image
    bands, start = [], 1
    while start <= last_row:
        stop = min(start + max_rows_per_block - 1, last_row)
        band_path = target.with_name(f"{target.stem}_band{len(bands)}.png")
        _export_block(wb, ws, start, stop, last_col, band_path)
        bands.append(band_path)
        start = stop + 1
    images = [Image.open(p).convert("RGB") for p in bands]
    width = max(im.width for im in images)
    stitched = Image.new("RGB", (width, sum(im.height for im in images)), "white")
    y = 0
    for im in images:
        stitched.paste(im, (0, y))
        y += im.height
        im.close()
    stitched.save(target)
    for p in bands:
        p.unlink(missing_ok=True)


def evaluate_and_render(path: Path = WORKBOOK_PATH) -> dict:
    """Recalculate in Excel, capture evaluated formula values, and export sheet images."""
    app, backend = _excel_app()
    if app is None:
        return {"available": False,
                "reason": "Microsoft Excel COM automation is not available on this machine"}
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    result: dict = {"available": True, "backend": backend, "evaluated": {}, "renders": {},
                    "errors": []}
    wb = None
    try:
        wb = app.Workbooks.Open(str(path.resolve()))
        app.CalculateFullRebuild()
        for sheet_name in ("Offer Simulator", "KPI Calculations"):
            ws = wb.Worksheets(sheet_name)
            used = ws.UsedRange
            values = {}
            for row in range(1, used.Rows.Count + 1):
                for col in range(1, used.Columns.Count + 1):
                    cell = used.Cells(row, col)
                    formula = cell.Formula
                    if isinstance(formula, str) and formula.startswith("="):
                        label = ws.Cells(cell.Row, 2).Value
                        values[str(cell.Address)] = {
                            "label": label, "formula": formula, "value": cell.Text}
                        if any(e in str(cell.Text) for e in EXCEL_ERRORS):
                            result["errors"].append(
                                f"{sheet_name}!{str(cell.Address)} -> {cell.Text}")
            result["evaluated"][sheet_name] = values
        # Sweep every sheet for evaluated error values, not only the formula sheets.
        for i in range(1, wb.Worksheets.Count + 1):
            ws = wb.Worksheets(i)
            used = ws.UsedRange
            for row in range(1, min(used.Rows.Count, 400) + 1):
                for col in range(1, min(used.Columns.Count, 60) + 1):
                    cell = used.Cells(row, col)
                    text = cell.Text
                    if isinstance(text, str) and any(e in text for e in EXCEL_ERRORS):
                        result["errors"].append(f"{ws.Name}!{cell.Address} -> {text}")
        for sheet_name in VISUAL_SHEETS:
            target = RENDER_DIR / (sheet_name.lower().replace(" ", "_") + ".png")
            try:
                _render_sheet(wb, sheet_name, target)
                result["renders"][sheet_name] = str(target)
            except Exception as exc:  # rendering is best-effort per sheet
                result["errors"].append(f"render {sheet_name}: {exc}")
        pdf = RENDER_DIR / "dashboard_sheets.pdf"
        try:
            wb.Worksheets(VISUAL_SHEETS[0]).ExportAsFixedFormat(0, str(pdf.resolve()))
            result["pdf"] = str(pdf)
        except Exception as exc:
            result["errors"].append(f"pdf export: {exc}")
    finally:
        # Never let a cleanup failure mask the real error, and never leave Excel running.
        try:
            if wb is not None:
                wb.Close(False)
        except Exception as exc:
            result["errors"].append(f"workbook close: {exc}")
        try:
            app.Quit()
        except Exception as exc:
            result["errors"].append(f"excel quit: {exc}")
    dash = RENDER_DIR / "executive_dashboard.png"
    if dash.exists():
        shutil.copyfile(dash, PREVIEW_PATH)
        result["preview"] = str(PREVIEW_PATH)
    return result


def verify(path: Path = WORKBOOK_PATH) -> dict:
    """Run the full verification pass and write outputs/workbook_verification.json."""
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist - run src/build_workbook.py first")
    report = audit_static(path)
    report["excel"] = evaluate_and_render(path)
    report["problems"].extend(report["excel"].get("errors", []))
    report["passed"] = not report["problems"]
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    rep = verify()
    for sheet, info in rep["sheets"].items():
        print(f"{sheet:<24} cells={info['non_empty_cells']:<6} formulas={info['formula_cells']:<4} "
              f"charts={info['charts']:<2} cf={info['conditional_formats']:<2} "
              f"freeze={info['freeze_panes']}")
    excel = rep["excel"]
    print(f"\nExcel available: {excel['available']}")
    if excel.get("renders"):
        print("Rendered:", ", ".join(excel["renders"]))
    if rep["problems"]:
        print("\nPROBLEMS:")
        for p in rep["problems"]:
            print(" -", p)
        sys.exit(1)
    print("\nWorkbook verification passed.")
