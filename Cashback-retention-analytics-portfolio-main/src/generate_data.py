"""Deterministic synthetic fintech customer, transaction, and campaign data."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from config import (CONTRIBUTION_MARGIN_RATE, DATA_DIR, DB_DIR, END_DATE,
                    N_CUSTOMERS, OUTPUT_DIR, SEED, START_DATE)

SEGMENTS = ["New", "Promising", "Active", "Loyal", "High value", "At risk", "Dormant"]
BASE_RATES = {"New": 8.0, "Promising": 13.0, "Active": 22.0, "Loyal": 36.0,
              "High value": 31.0, "At risk": 11.0, "Dormant": 3.5}
AMOUNT_MEANS = {"New": 430, "Promising": 520, "Active": 620, "Loyal": 760,
                "High value": 1450, "At risk": 680, "Dormant": 490}
EFFECTS = {"New": 0.05, "Promising": 0.24, "Active": 0.14, "Loyal": 0.07,
           "High value": 0.09, "At risk": 0.31, "Dormant": 0.02}
REDEEM = {"New": 0.18, "Promising": 0.39, "Active": 0.34, "Loyal": 0.29,
          "High value": 0.28, "At risk": 0.43, "Dormant": 0.11}


def _ensure_dirs() -> None:
    for path in (DATA_DIR, DB_DIR, OUTPUT_DIR, OUTPUT_DIR / "charts"):
        path.mkdir(parents=True, exist_ok=True)


def generate_customers(rng: np.random.Generator) -> pd.DataFrame:
    customer_id = np.arange(1, N_CUSTOMERS + 1)
    segment = rng.choice(SEGMENTS, N_CUSTOMERS, p=[.10, .13, .22, .16, .10, .18, .11])
    signup_offsets = rng.integers(0, 300, N_CUSTOMERS)
    # New customers are genuinely newer; all other types predate most campaigns.
    signup_offsets = np.where(segment == "New", rng.integers(240, 340, N_CUSTOMERS), signup_offsets)
    return pd.DataFrame({
        "customer_id": customer_id,
        "signup_date": pd.Timestamp(START_DATE) + pd.to_timedelta(signup_offsets, unit="D"),
        "region": rng.choice(["North", "South", "East", "West", "Central"], N_CUSTOMERS,
                             p=[.22, .25, .18, .24, .11]),
        "acquisition_channel": rng.choice(["Organic", "Referral", "Paid social", "Partner", "Search"],
                                          N_CUSTOMERS, p=[.34, .24, .16, .14, .12]),
        "age_band": rng.choice(["18-24", "25-34", "35-44", "45+"], N_CUSTOMERS,
                               p=[.29, .39, .22, .10]),
        "initial_customer_type": segment,
    })


def generate_baseline_transactions(customers: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    days = (pd.Timestamp(END_DATE) - pd.Timestamp(START_DATE)).days + 1
    region_mult = customers["region"].map({"North": 1.02, "South": 1.12, "East": .91,
                                           "West": 1.08, "Central": .94}).to_numpy()
    rates = customers["initial_customer_type"].map(BASE_RATES).to_numpy() * region_mult
    counts = rng.poisson(rates)
    cids = np.repeat(customers["customer_id"].to_numpy(), counts)
    segs = np.repeat(customers["initial_customer_type"].to_numpy(), counts)
    signs = np.repeat(customers["signup_date"].to_numpy(), counts)
    n = len(cids)
    # Weekly/month-end acceptance makes seasonality visible while retaining independent draws.
    raw_offsets = rng.integers(0, days, n)
    dates = pd.Timestamp(START_DATE) + pd.to_timedelta(raw_offsets, unit="D")
    bump = np.where(pd.DatetimeIndex(dates).dayofweek >= 5, .16, 0) + np.where(pd.DatetimeIndex(dates).day >= 25, .10, 0)
    keep = rng.random(n) < np.minimum(.96, .80 + bump)
    keep &= dates.to_numpy() >= signs
    cids, segs, dates = cids[keep], segs[keep], dates[keep]
    n = len(cids)
    means = pd.Series(segs).map(AMOUNT_MEANS).to_numpy()
    amounts = rng.lognormal(np.log(means) - .35, .72)
    # Natural churn: at-risk and dormant transactions skew early.
    daynum = (pd.DatetimeIndex(dates) - pd.Timestamp(START_DATE)).days.to_numpy()
    churn_prob = np.where(segs == "Dormant", .52 * daynum / days,
                         np.where(segs == "At risk", .30 * daynum / days, 0))
    keep2 = rng.random(n) > churn_prob
    tx = pd.DataFrame({
        "customer_id": cids[keep2], "transaction_date": dates[keep2],
        "merchant_category": rng.choice(["Grocery", "Bills", "Recharge", "Travel", "Food", "Shopping"],
                                               keep2.sum(), p=[.24, .17, .16, .10, .18, .15]),
        "payment_method": rng.choice(["UPI", "Wallet", "Card"], keep2.sum(), p=[.72, .17, .11]),
        "amount": np.round(amounts[keep2], 2),
        "transaction_status": rng.choice(["Success", "Failed", "Reversed"], keep2.sum(), p=[.965, .025, .01]),
        "is_campaign_increment": 0,
    })
    return tx


def _rfm_as_of(customers: pd.DataFrame, tx: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    # A customer who has not signed up by the cutoff does not exist yet and cannot be
    # targeted. Without this filter their days-since-signup is negative, which falls through
    # the "New" rule and enrols them in a campaign that predates their own account.
    customers = customers[customers.signup_date < cutoff]
    successful = tx[(tx.transaction_status == "Success") & (tx.transaction_date < cutoff)]
    agg = successful.groupby("customer_id").agg(
        last_txn=("transaction_date", "max"), frequency=("transaction_date", "size"), monetary=("amount", "sum"))
    rfm = customers[["customer_id", "signup_date"]].merge(agg, on="customer_id", how="left")
    rfm["recency"] = (cutoff - rfm["last_txn"]).dt.days.fillna(999).astype(int)
    rfm["frequency"] = rfm["frequency"].fillna(0).astype(int)
    rfm["monetary"] = rfm["monetary"].fillna(0.0)
    # Robust rank-based scores with documented business overlays.
    rfm["r_score"] = pd.qcut(rfm["recency"].rank(method="first", ascending=False), 5, labels=False) + 1
    rfm["f_score"] = pd.qcut(rfm["frequency"].rank(method="first"), 5, labels=False) + 1
    rfm["m_score"] = pd.qcut(rfm["monetary"].rank(method="first"), 5, labels=False) + 1
    days_since_signup = (cutoff - rfm["signup_date"]).dt.days
    conditions = [
        days_since_signup <= 45,
        (rfm.recency > 120) | (rfm.frequency == 0),
        (rfm.recency > 60) & (rfm.frequency > 0),
        (rfm.m_score == 5) & (rfm.frequency >= 8),
        (rfm.f_score >= 4) & (rfm.r_score >= 4),
        (rfm.r_score >= 3) & (rfm.f_score >= 3),
    ]
    rfm["segment"] = np.select(conditions,
        ["New", "Dormant", "At risk", "High value", "Loyal", "Active"], default="Promising")
    return rfm


def generate_campaigns_and_effects(customers: pd.DataFrame, tx: pd.DataFrame,
                                   rng: np.random.Generator):
    campaigns = pd.DataFrame([
        [1, "Reactivation Boost", "2025-08-15", "2025-09-13", "At risk + Dormant", 40.0, 250.0],
        [2, "Habit Builder", "2025-10-01", "2025-10-30", "Promising + Active", 35.0, 300.0],
        [3, "Year-end Value", "2025-11-15", "2025-12-14", "All eligible", 50.0, 500.0],
    ], columns=["campaign_id", "campaign_name", "start_date", "end_date", "target_segment", "cashback_offer", "minimum_spend"])
    campaigns[["start_date", "end_date"]] = campaigns[["start_date", "end_date"]].apply(pd.to_datetime)
    assignments, redemptions, rfm_rows, increment_rows = [], [], [], []
    # `history` grows as each campaign completes, so a snapshot taken before campaign N
    # sees every transaction that had actually occurred by then -- including incremental
    # transactions produced by campaigns 1..N-1. This keeps `rfm_snapshots` exactly
    # reproducible from the `transactions` table (see sql/03_rfm_segmentation.sql) while
    # still using only strictly pre-assignment data.
    history = tx
    for camp in campaigns.itertuples(index=False):
        rfm = _rfm_as_of(customers, history, camp.start_date)
        rfm["campaign_id"] = camp.campaign_id
        rfm_rows.append(rfm)
        allowed = (["At risk", "Dormant"] if camp.campaign_id == 1 else
                   ["Promising", "Active"] if camp.campaign_id == 2 else SEGMENTS)
        eligible = rfm[rfm.segment.isin(allowed)].copy()
        eligible = eligible.sample(n=min(12_000, len(eligible)), random_state=SEED + camp.campaign_id)
        treatment = rng.random(len(eligible)) < .5
        a = pd.DataFrame({"campaign_id": camp.campaign_id,
                          "customer_id": eligible.customer_id.to_numpy(),
                          "treatment_group": np.where(treatment, "Treatment", "Control"),
                          "assignment_date": camp.start_date,
                          "offer_received": treatment.astype(int)})
        assignments.append(a)
        treated = eligible[treatment].copy()
        redeem_prob = treated.segment.map(REDEEM).to_numpy()
        redeemed = rng.random(len(treated)) < redeem_prob
        redeemed_ids = treated.loc[redeemed, "customer_id"].to_numpy()
        redemptions.append(pd.DataFrame({
            "campaign_id": camp.campaign_id, "customer_id": redeemed_ids,
            "redemption_date": camp.start_date + pd.to_timedelta(rng.integers(1, 25, len(redeemed_ids)), unit="D"),
            "cashback_cost": camp.cashback_offer,
        }))
        # Incremental transactions are injected only for treated customers, with segment heterogeneity.
        mu = treated.segment.map(EFFECTS).to_numpy() * 1.9
        extra_n = rng.poisson(mu)
        ids = np.repeat(treated.customer_id.to_numpy(), extra_n)
        segs = np.repeat(treated.segment.to_numpy(), extra_n)
        if len(ids):
            means = pd.Series(segs).map(AMOUNT_MEANS).to_numpy()
            wave = pd.DataFrame({
                "customer_id": ids,
                "transaction_date": camp.start_date + pd.to_timedelta(rng.integers(1, 31, len(ids)), unit="D"),
                "merchant_category": rng.choice(["Grocery", "Bills", "Recharge", "Travel", "Food", "Shopping"], len(ids)),
                "payment_method": rng.choice(["UPI", "Wallet", "Card"], len(ids), p=[.76, .15, .09]),
                "amount": np.round(rng.lognormal(np.log(means) - .35, .65), 2),
                "transaction_status": "Success", "is_campaign_increment": camp.campaign_id,
            })
            increment_rows.append(wave)
            history = pd.concat([history, wave], ignore_index=True)
    return campaigns, pd.concat(assignments, ignore_index=True), pd.concat(redemptions, ignore_index=True), pd.concat(rfm_rows, ignore_index=True), pd.concat(increment_rows, ignore_index=True)


def generate_all(write: bool = True):
    _ensure_dirs()
    rng = np.random.default_rng(SEED)
    customers = generate_customers(rng)
    tx = generate_baseline_transactions(customers, rng)
    campaigns, assignments, redemptions, rfm, increments = generate_campaigns_and_effects(customers, tx, rng)
    tx = pd.concat([tx, increments], ignore_index=True).sort_values(["transaction_date", "customer_id"]).reset_index(drop=True)
    tx.insert(0, "transaction_id", np.arange(1, len(tx) + 1))
    if write:
        tables = {"customers": customers, "transactions": tx, "campaigns": campaigns,
                  "campaign_assignments": assignments, "cashback_redemptions": redemptions,
                  "rfm_snapshots": rfm}
        for name, df in tables.items():
            df.to_csv(DATA_DIR / f"{name}.csv", index=False)
            df.head(250).to_csv(DATA_DIR / f"{name}_sample.csv", index=False)
        db_path = DB_DIR / "cashback_analytics.db"
        with sqlite3.connect(db_path) as conn:
            for name, df in tables.items():
                df.to_sql(name, conn, if_exists="replace", index=False)
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_customer ON customers(customer_id)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_txn ON transactions(transaction_id)")
        metadata = {"seed": SEED, "customers": len(customers), "transactions": len(tx),
                    "successful_transactions": int(tx.transaction_status.eq("Success").sum()),
                    "campaigns": len(campaigns),
                    "campaign_assignments": len(assignments), "redemptions": len(redemptions),
                    "rfm_snapshot_rows": len(rfm),
                    "start_date": START_DATE, "end_date": END_DATE,
                    "reporting_period": f"{START_DATE} to {END_DATE}",
                    "contribution_margin_rate": CONTRIBUTION_MARGIN_RATE}
        (OUTPUT_DIR / "generation_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return customers, tx, campaigns, assignments, redemptions, rfm


if __name__ == "__main__":
    generate_all()
