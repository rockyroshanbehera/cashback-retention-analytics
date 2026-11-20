"""Experiment validity: no leakage, balanced arms, and correct RFM/retention definitions."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import D7_WINDOW_DAYS, D30_WINDOW_DAYS
from generate_data import _rfm_as_of

TOL = 1e-9


def test_assignment_is_balanced(assignments):
    """Realized treatment share must sit near 50% in every campaign."""
    share = assignments.groupby("campaign_id").treatment_group.value_counts(normalize=True)
    assert share.between(0.47, 0.53).all(), f"unbalanced allocation:\n{share}"


def test_offer_flag_reconciles_with_treatment_group(assignments):
    expected = assignments.treatment_group.eq("Treatment").astype(int)
    assert assignments.offer_received.equals(expected)


def test_no_treatment_leakage_into_control(assignments, redemptions):
    """A control customer must never appear in the redemption table for that campaign."""
    control = assignments[assignments.treatment_group.eq("Control")][["campaign_id", "customer_id"]]
    leaked = redemptions.merge(control, on=["campaign_id", "customer_id"], how="inner")
    assert leaked.empty, f"{len(leaked)} control customers redeemed cashback"


def test_no_incremental_transaction_before_its_campaign(transactions, campaigns):
    injected = transactions[transactions.is_campaign_increment.gt(0)]
    merged = injected.merge(campaigns[["campaign_id", "start_date"]],
                            left_on="is_campaign_increment", right_on="campaign_id")
    assert (merged.transaction_date >= merged.start_date).all()


def test_incremental_transactions_only_reach_treated_customers(transactions, assignments):
    injected = transactions[transactions.is_campaign_increment.gt(0)][
        ["customer_id", "is_campaign_increment"]].drop_duplicates()
    treated = assignments[assignments.treatment_group.eq("Treatment")][["campaign_id", "customer_id"]]
    merged = injected.merge(treated, left_on=["is_campaign_increment", "customer_id"],
                            right_on=["campaign_id", "customer_id"], how="left")
    assert merged.campaign_id.notna().all(), "an untreated customer received injected transactions"


def test_rfm_snapshot_uses_only_pre_assignment_data(rfm, campaigns):
    """Every snapshot's last transaction must precede its campaign start date."""
    merged = rfm.merge(campaigns[["campaign_id", "start_date"]], on="campaign_id")
    observed = merged[merged.last_txn.notna()]
    assert (observed.last_txn < observed.start_date).all()
    assert (observed.recency >= 0).all()


def test_rfm_snapshot_is_reproducible_from_transactions(customers, transactions, campaigns, rfm):
    """Recomputing RFM from the raw transaction table must reproduce the stored snapshot.

    This is the strongest available guarantee that no post-treatment field defines a segment:
    the snapshot is rebuilt from nothing but customers, successful transactions and the cutoff.
    """
    for camp in campaigns.itertuples(index=False):
        expected = _rfm_as_of(customers, transactions, camp.start_date)
        stored = rfm[rfm.campaign_id.eq(camp.campaign_id)].sort_values("customer_id")
        expected = expected.sort_values("customer_id")
        assert stored.customer_id.tolist() == expected.customer_id.tolist()
        for col in ["recency", "frequency", "r_score", "f_score", "m_score"]:
            assert stored[col].to_numpy().tolist() == expected[col].to_numpy().tolist(), \
                f"campaign {camp.campaign_id}: {col} does not reproduce"
        assert np.allclose(stored.monetary.to_numpy(), expected.monetary.to_numpy())
        assert stored.segment.tolist() == expected.segment.tolist()


def test_rfm_frequency_counts_only_successful_pre_cutoff_transactions(transactions, campaigns, rfm):
    success = transactions[transactions.transaction_status.eq("Success")]
    camp = campaigns.iloc[0]
    cut = camp.start_date
    expected = (success[success.transaction_date < cut].groupby("customer_id").size()
                .rename("expected").reset_index())
    snap = rfm[rfm.campaign_id.eq(camp.campaign_id)][["customer_id", "frequency"]]
    merged = snap.merge(expected, on="customer_id", how="left").fillna({"expected": 0})
    assert (merged.frequency == merged.expected).all()


def test_segment_labels_are_from_the_documented_set(rfm):
    assert set(rfm.segment) == {"New", "Promising", "Active", "Loyal", "High value",
                                "At risk", "Dormant"}


def _outcomes(transactions, assignments, campaigns, window):
    """Recompute per-customer retention independently of the analysis module."""
    success = transactions[transactions.transaction_status.eq("Success")]
    rows = []
    for camp in campaigns.itertuples(index=False):
        a = assignments[assignments.campaign_id.eq(camp.campaign_id)].copy()
        lo, hi = camp.start_date, camp.start_date + pd.Timedelta(days=window)
        active = set(success[(success.transaction_date >= lo) &
                             (success.transaction_date < hi)].customer_id)
        a["retained"] = a.customer_id.isin(active).astype(int)
        rows.append(a)
    return pd.concat(rows, ignore_index=True)


def test_d30_retention_matches_independent_recomputation(transactions, assignments, campaigns,
                                                         campaign_results):
    out = _outcomes(transactions, assignments, campaigns, D30_WINDOW_DAYS)
    rates = out.groupby(["campaign_id", "treatment_group"]).retained.mean().unstack()
    for row in campaign_results.itertuples(index=False):
        assert abs(rates.loc[row.campaign_id, "Treatment"] - row.treatment_d30_retention) < TOL
        assert abs(rates.loc[row.campaign_id, "Control"] - row.control_d30_retention) < TOL


def test_uplift_equals_treatment_minus_control(campaign_results, segment_results):
    for frame in (campaign_results, segment_results):
        expected = frame.treatment_d30_retention - frame.control_d30_retention
        assert np.allclose(frame.absolute_uplift, expected)
        # The interval must bracket the point estimate.
        assert (frame.ci_low <= frame.absolute_uplift + TOL).all()
        assert (frame.ci_high >= frame.absolute_uplift - TOL).all()


def test_retention_denominator_is_every_assigned_customer(campaign_results, assignments):
    counts = assignments.groupby(["campaign_id", "treatment_group"]).size().unstack()
    for row in campaign_results.itertuples(index=False):
        assert row.treatment_size == counts.loc[row.campaign_id, "Treatment"]
        assert row.control_size == counts.loc[row.campaign_id, "Control"]
        assert row.eligible_customers == row.treatment_size + row.control_size


def test_d7_window_is_narrower_than_d30(transactions, assignments, campaigns):
    d7 = _outcomes(transactions, assignments, campaigns, D7_WINDOW_DAYS)
    d30 = _outcomes(transactions, assignments, campaigns, D30_WINDOW_DAYS)
    assert d7.retained.sum() < d30.retained.sum()
    # Anyone active in the D7 window is necessarily active in the D30 window.
    joined = d7.merge(d30, on=["campaign_id", "customer_id"], suffixes=("_d7", "_d30"))
    assert not ((joined.retained_d7 == 1) & (joined.retained_d30 == 0)).any()


def test_outcomes_exclude_failed_and_reversed_transactions(transactions, assignments, campaigns,
                                                           campaign_results):
    """Counting every status instead of Success only must change the answer."""
    all_status = []
    for camp in campaigns.itertuples(index=False):
        a = assignments[assignments.campaign_id.eq(camp.campaign_id)].copy()
        lo, hi = camp.start_date, camp.start_date + pd.Timedelta(days=D30_WINDOW_DAYS)
        active = set(transactions[(transactions.transaction_date >= lo) &
                                  (transactions.transaction_date < hi)].customer_id)
        a["retained"] = a.customer_id.isin(active).astype(int)
        all_status.append(a)
    loose = pd.concat(all_status, ignore_index=True)
    loose_rate = loose[loose.treatment_group.eq("Treatment")].retained.mean()
    strict = (campaign_results.treatment_d30_retention * campaign_results.treatment_size).sum() / \
        campaign_results.treatment_size.sum()
    assert loose_rate > strict, "status filter appears to have no effect"


def test_pre_period_balance_is_within_conventional_threshold(campaign_results, segment_results):
    for frame in (campaign_results, segment_results):
        assert frame.pre_frequency_smd.abs().max() < 0.10
        assert frame.treatment_share.between(0.45, 0.55).all()
