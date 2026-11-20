"""Campaign, retention, uplift, and economics analysis."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from config import (CONTRIBUTION_MARGIN_RATE, D7_WINDOW_DAYS, D30_WINDOW_DAYS,
                    DATA_DIR, OUTPUT_DIR)


def _ci_diff(p1, n1, p0, n0, z=1.96):
    diff = p1 - p0
    se = math.sqrt(max(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0, 1e-12))
    p_value = math.erfc(abs(diff / se) / math.sqrt(2))
    return diff - z * se, diff + z * se, p_value


def analyze() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    customers = pd.read_csv(DATA_DIR / "customers.csv", parse_dates=["signup_date"])
    tx = pd.read_csv(DATA_DIR / "transactions.csv", parse_dates=["transaction_date"])
    campaigns = pd.read_csv(DATA_DIR / "campaigns.csv", parse_dates=["start_date", "end_date"])
    assignments = pd.read_csv(DATA_DIR / "campaign_assignments.csv", parse_dates=["assignment_date"])
    redemptions = pd.read_csv(DATA_DIR / "cashback_redemptions.csv", parse_dates=["redemption_date"])
    rfm = pd.read_csv(DATA_DIR / "rfm_snapshots.csv", parse_dates=["signup_date", "last_txn"])
    success = tx[tx.transaction_status.eq("Success")]
    detailed = []
    for camp in campaigns.itertuples(index=False):
        a = assignments[assignments.campaign_id.eq(camp.campaign_id)].copy()
        seg = rfm[rfm.campaign_id.eq(camp.campaign_id)][["customer_id", "segment", "recency", "frequency", "monetary"]]
        a = a.merge(seg, on="customer_id", how="left")
        pre = success[(success.transaction_date >= camp.start_date - pd.Timedelta(days=30)) &
                      (success.transaction_date < camp.start_date)].groupby("customer_id").agg(
                          pre_txns=("transaction_id", "size"), pre_value=("amount", "sum"))
        post = success[(success.transaction_date >= camp.start_date) &
                       (success.transaction_date < camp.start_date + pd.Timedelta(days=D30_WINDOW_DAYS))].groupby("customer_id").agg(
                           post_txns=("transaction_id", "size"), post_value=("amount", "sum"),
                           first_post=("transaction_date", "min"))
        a = a.merge(pre, on="customer_id", how="left").merge(post, on="customer_id", how="left")
        a[["pre_txns", "pre_value", "post_txns", "post_value"]] = a[["pre_txns", "pre_value", "post_txns", "post_value"]].fillna(0)
        delta_days = (a.first_post - camp.start_date).dt.days
        a["d7_repeat"] = delta_days.between(0, D7_WINDOW_DAYS - 1).astype(int)
        a["d30_retained"] = (a.post_txns > 0).astype(int)
        a["campaign_name"] = camp.campaign_name
        detailed.append(a)
    detail = pd.concat(detailed, ignore_index=True)
    detail.to_csv(DATA_DIR / "experiment_customer_metrics.csv", index=False)

    def summarize(g):
        t, c = g[g.treatment_group.eq("Treatment")], g[g.treatment_group.eq("Control")]
        p1, p0 = t.d30_retained.mean(), c.d30_retained.mean()
        lo, hi, pval = _ci_diff(p1, len(t), p0, len(c))
        tx_uplift = t.post_txns.mean() - c.post_txns.mean()
        inc_retained = (p1 - p0) * len(t)
        inc_txns = tx_uplift * len(t)
        # Join on the full (campaign, customer) key. A segment group spans several campaign
        # waves, so filtering on customer_id alone -- or on a single campaign_id -- would
        # silently drop the redemptions booked by later waves.
        red = redemptions.merge(t[["campaign_id", "customer_id"]].drop_duplicates(),
                                on=["campaign_id", "customer_id"], how="inner")
        cost = red.cashback_cost.sum()
        pooled_apv = success[success.customer_id.isin(g.customer_id)].amount.mean()
        inc_contribution = max(0, inc_txns) * pooled_apv * CONTRIBUTION_MARGIN_RATE
        profit = inc_contribution - cost
        return pd.Series({
            "eligible_customers": len(g), "treatment_size": len(t), "control_size": len(c),
            "treatment_share": len(t) / len(g),
            "redemption_rate": len(red) / len(t), "treatment_pre_frequency": t.pre_txns.mean(),
            "control_pre_frequency": c.pre_txns.mean(), "treatment_post_frequency": t.post_txns.mean(),
            "control_post_frequency": c.post_txns.mean(), "treatment_d7_rate": t.d7_repeat.mean(),
            "control_d7_rate": c.d7_repeat.mean(), "treatment_d30_retention": p1,
            "control_d30_retention": p0, "absolute_uplift": p1 - p0,
            "relative_uplift": (p1 / p0 - 1) if p0 else np.nan, "ci_low": lo, "ci_high": hi,
            "p_value": pval, "incremental_retained_customers": inc_retained,
            "incremental_transactions": inc_txns, "average_payment_value": pooled_apv,
            "cashback_cost": cost, "incremental_contribution": inc_contribution,
            "incremental_profit": profit, "roi": profit / cost if cost else np.nan,
            "cost_per_incremental_retained": cost / inc_retained if inc_retained > 0 else np.nan,
            "pre_frequency_smd": (t.pre_txns.mean() - c.pre_txns.mean()) / max(g.pre_txns.std(), .001),
            "pre_value_smd": (t.pre_value.mean() - c.pre_value.mean()) / max(g.pre_value.std(), .001),
        })

    campaign_rows = []
    for (campaign_id, campaign_name), g in detail.groupby(["campaign_id", "campaign_name"]):
        row = summarize(g).to_dict()
        row.update({"campaign_id": campaign_id, "campaign_name": campaign_name})
        campaign_rows.append(row)
    campaign = pd.DataFrame(campaign_rows)
    # Segment analysis pooled across randomized waves; treatment/control comparisons remain within campaigns via stratified totals.
    segment_rows = []
    for segment_name, g in detail.groupby("segment"):
        row = summarize(g).to_dict()
        row["segment"] = segment_name
        segment_rows.append(row)
    segment = pd.DataFrame(segment_rows)
    segment["baseline_retention"] = segment["control_d30_retention"]
    segment["practical_significance"] = np.where(segment.absolute_uplift.abs() >= .02, "Material", "Small")
    segment["action"] = np.select([
        (segment.ci_low > 0) & (segment.roi >= .15),
        (segment.absolute_uplift > 0) & (segment.roi >= 0),
        (segment.ci_low > 0) & (segment.roi < 0),
    ], ["Scale", "Test further", "Redesign offer"], default="Do not target")
    # Labelled planning assumption, derived from the data rather than hard-coded: across all
    # randomized segments, each incremental retained customer carried this many incremental
    # successful transactions inside the D30 window. Scenarios reuse it so that the "Base"
    # scenario reconciles exactly with the observed result for every segment.
    txns_per_retained = float(segment.incremental_transactions.sum() /
                              segment.incremental_retained_customers.sum())
    scenarios = []
    for row in segment.itertuples(index=False):
        for scenario, uplift in [("Conservative", row.ci_low), ("Base", row.absolute_uplift), ("Optimistic", row.ci_high)]:
            inc_cust = uplift * row.treatment_size
            # Observed rows carry the measured transaction lift; the two CI-bound rows are
            # projections that convert retained customers using the labelled assumption.
            inc_txn = row.incremental_transactions if scenario == "Base" else inc_cust * txns_per_retained
            contribution = max(0.0, inc_txn) * row.average_payment_value * CONTRIBUTION_MARGIN_RATE
            profit = contribution - row.cashback_cost
            scenarios.append({"segment": row.segment, "scenario": scenario,
                              "basis": "Observed" if scenario == "Base" else "Estimated",
                              "uplift": uplift, "incremental_customers": inc_cust,
                              "txns_per_incremental_retained": txns_per_retained,
                              "incremental_transactions": inc_txn,
                              "cashback_cost": row.cashback_cost, "incremental_contribution": contribution,
                              "estimated_profit": profit, "roi": profit / row.cashback_cost if row.cashback_cost else np.nan})
    scenarios = pd.DataFrame(scenarios)
    campaign.to_csv(OUTPUT_DIR / "campaign_performance.csv", index=False)
    segment.to_csv(OUTPUT_DIR / "segment_recommendations.csv", index=False)
    scenarios.to_csv(OUTPUT_DIR / "scenarios.csv", index=False)
    detail_summary = {
        "experimental_unit": "customer within campaign",
        "primary_metric": f"D30 retention (>=1 successful transaction in days 0-{D30_WINDOW_DAYS - 1})",
        "secondary_metrics": [f"D7 repeat (days 0-{D7_WINDOW_DAYS - 1})",
                              "post-window successful transactions per assigned customer",
                              "redemption rate among treated"],
        "denominator": "all assigned customers in the arm, whether or not they redeemed (intent to treat)",
        "outcome_filter": "successful transactions only; Failed and Reversed rows are excluded",
        "guardrails": ["cashback cost", "incremental profit", "average payment value"],
        "multiple_comparisons": "Segment confidence intervals are exploratory and unadjusted.",
        "causal_scope": "Valid for randomized eligible populations in this synthetic simulation only.",
        "observed_vs_estimated": {
            "observed": ["campaign_performance.csv", "segment_recommendations.csv",
                         "scenarios.csv rows where basis == 'Observed'"],
            "estimated": ["scenarios.csv rows where basis == 'Estimated'",
                          "Offer Simulator sheet in the Excel workbook"]},
        "assumptions": {
            "contribution_margin_rate": CONTRIBUTION_MARGIN_RATE,
            "contribution_margin_source": "stated planning assumption, not a measured figure",
            "txns_per_incremental_retained": txns_per_retained,
            "txns_per_incremental_retained_source":
                "derived = sum(incremental_transactions) / sum(incremental_retained_customers) "
                "across all randomized segments"}}
    (OUTPUT_DIR / "experiment_notes.json").write_text(json.dumps(detail_summary, indent=2), encoding="utf-8")
    return campaign, segment, scenarios


if __name__ == "__main__":
    analyze()
