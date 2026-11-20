"""Data-quality and experiment-integrity checks."""
from __future__ import annotations

import json
import pandas as pd
from config import DATA_DIR, OUTPUT_DIR, SEED


def validate():
    c = pd.read_csv(DATA_DIR / "customers.csv", parse_dates=["signup_date"])
    t = pd.read_csv(DATA_DIR / "transactions.csv", parse_dates=["transaction_date"])
    cp = pd.read_csv(DATA_DIR / "campaigns.csv", parse_dates=["start_date", "end_date"])
    a = pd.read_csv(DATA_DIR / "campaign_assignments.csv", parse_dates=["assignment_date"])
    r = pd.read_csv(DATA_DIR / "cashback_redemptions.csv", parse_dates=["redemption_date"])
    checks = {
        "customer_pk_unique": c.customer_id.is_unique,
        "transaction_pk_unique": t.transaction_id.is_unique,
        "transaction_fk_valid": t.customer_id.isin(c.customer_id).all(),
        "assignment_fk_valid": a.customer_id.isin(c.customer_id).all() and a.campaign_id.isin(cp.campaign_id).all(),
        "nonnegative_amounts": (t.amount >= 0).all(),
        "valid_transaction_dates": t.transaction_date.between("2025-01-01", "2025-12-31").all(),
        "no_transaction_before_signup": t.merge(c[["customer_id", "signup_date"]], on="customer_id")
                                         .eval("transaction_date >= signup_date").all(),
        "no_assignment_before_signup": a.merge(c[["customer_id", "signup_date"]], on="customer_id")
                                        .eval("assignment_date >= signup_date").all(),
        "no_duplicate_assignment": ~a.duplicated(["campaign_id", "customer_id"]).any(),
        "offer_matches_treatment": (a.offer_received.eq(a.treatment_group.eq("Treatment").astype(int))).all(),
        "no_control_redemption": len(r.merge(a, on=["campaign_id", "customer_id"]).query("treatment_group == 'Control'")) == 0,
        "valid_redemption_dates": r.merge(cp, on="campaign_id").eval("redemption_date >= start_date & redemption_date <= end_date").all(),
        "valid_redemption_cost": (r.cashback_cost > 0).all(),
        "missing_critical_fields": not (c.isna().any().any() or t[["transaction_id", "customer_id", "transaction_date", "amount", "transaction_status"]].isna().any().any()),
        "assignment_balance": a.groupby("campaign_id").treatment_group.value_counts(normalize=True).between(.47, .53).all(),
        "no_prestart_campaign_increment": t[t.is_campaign_increment.gt(0)].merge(cp, left_on="is_campaign_increment", right_on="campaign_id").eval("transaction_date >= start_date").all(),
    }
    result = {"seed": SEED, "all_passed": all(bool(v) for v in checks.values()), "checks": {k: bool(v) for k, v in checks.items()}}
    (OUTPUT_DIR / "data_quality_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result["all_passed"]:
        raise AssertionError([k for k, v in checks.items() if not v])
    return result


if __name__ == "__main__":
    validate()

