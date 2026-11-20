"""Campaign economics reconciliation, scenario labelling, cohorts and the forecast split."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import CONTRIBUTION_MARGIN_RATE, FORECAST_HOLDOUT_DAYS

TOL = 1e-6


def test_cashback_cost_reconciles_with_the_redemption_table(campaign_results, segment_results,
                                                            redemptions, assignments):
    """Both stratifications must account for exactly the redemptions treated customers made."""
    treated = assignments[assignments.treatment_group.eq("Treatment")][["campaign_id", "customer_id"]]
    booked = redemptions.merge(treated, on=["campaign_id", "customer_id"], how="inner")
    total = booked.cashback_cost.sum()
    assert abs(campaign_results.cashback_cost.sum() - total) < TOL
    assert abs(segment_results.cashback_cost.sum() - total) < TOL, \
        "segment costs do not sum to the redemption table - a campaign wave is being dropped"


def test_per_campaign_cost_matches_redemptions(campaign_results, redemptions, assignments):
    treated = assignments[assignments.treatment_group.eq("Treatment")][["campaign_id", "customer_id"]]
    booked = (redemptions.merge(treated, on=["campaign_id", "customer_id"], how="inner")
              .groupby("campaign_id").cashback_cost.sum())
    for row in campaign_results.itertuples(index=False):
        assert abs(row.cashback_cost - booked.loc[row.campaign_id]) < TOL


def test_redemption_rate_is_redeemers_over_treated(segment_results):
    assert segment_results.redemption_rate.between(0, 1).all()
    assert (segment_results.redemption_rate > 0).all()


def test_incremental_retained_formula(campaign_results, segment_results):
    for frame in (campaign_results, segment_results):
        expected = frame.absolute_uplift * frame.treatment_size
        assert np.allclose(frame.incremental_retained_customers, expected)


def test_incremental_transactions_formula(campaign_results, segment_results):
    for frame in (campaign_results, segment_results):
        expected = (frame.treatment_post_frequency - frame.control_post_frequency) * frame.treatment_size
        assert np.allclose(frame.incremental_transactions, expected)


def test_contribution_profit_and_roi_formulas(campaign_results, segment_results):
    for frame in (campaign_results, segment_results):
        contribution = (frame.incremental_transactions.clip(lower=0) *
                        frame.average_payment_value * CONTRIBUTION_MARGIN_RATE)
        assert np.allclose(frame.incremental_contribution, contribution)
        assert np.allclose(frame.incremental_profit,
                           frame.incremental_contribution - frame.cashback_cost)
        assert np.allclose(frame.roi, frame.incremental_profit / frame.cashback_cost)


def test_cost_per_incremental_retained_formula(segment_results):
    positive = segment_results[segment_results.incremental_retained_customers > 0]
    expected = positive.cashback_cost / positive.incremental_retained_customers
    assert np.allclose(positive.cost_per_incremental_retained, expected)


def test_action_rule_matches_its_documented_definition(segment_results):
    """Scale: CI low > 0 and ROI >= 15%. Test further: uplift > 0 and ROI >= 0.
    Redesign offer: CI low > 0 but ROI < 0. Do not target: otherwise."""
    for row in segment_results.itertuples(index=False):
        if row.ci_low > 0 and row.roi >= 0.15:
            expected = "Scale"
        elif row.absolute_uplift > 0 and row.roi >= 0:
            expected = "Test further"
        elif row.ci_low > 0 and row.roi < 0:
            expected = "Redesign offer"
        else:
            expected = "Do not target"
        assert row.action == expected, f"{row.segment}: expected {expected}, got {row.action}"


def test_every_segment_receives_an_action(segment_results):
    assert segment_results.action.notna().all()
    assert set(segment_results.action) <= {"Scale", "Test further", "Redesign offer", "Do not target"}
    assert len(segment_results) == 7


def test_scenarios_label_observed_versus_estimated(scenarios, segment_results, experiment_notes):
    assert set(scenarios.scenario) == {"Conservative", "Base", "Optimistic"}
    assert set(scenarios.basis) == {"Observed", "Estimated"}
    assert (scenarios[scenarios.scenario.eq("Base")].basis == "Observed").all()
    assert (scenarios[scenarios.scenario.ne("Base")].basis == "Estimated").all()
    # The observed Base rows must equal the measured segment results exactly.
    base = scenarios[scenarios.scenario.eq("Base")].set_index("segment").sort_index()
    seg = segment_results.set_index("segment").sort_index()
    assert np.allclose(base.uplift, seg.absolute_uplift)
    assert np.allclose(base.incremental_transactions, seg.incremental_transactions)
    assert np.allclose(base.roi, seg.roi)


def test_scenario_assumption_is_exposed_not_hidden(scenarios, experiment_notes, segment_results):
    tpr = experiment_notes["assumptions"]["txns_per_incremental_retained"]
    assert "txns_per_incremental_retained" in scenarios.columns
    assert np.allclose(scenarios.txns_per_incremental_retained, tpr)
    derived = (segment_results.incremental_transactions.sum() /
               segment_results.incremental_retained_customers.sum())
    assert abs(tpr - derived) < TOL, "the assumption is not derived from the observed data"


def test_scenario_bounds_order_correctly(scenarios):
    pivot = scenarios.pivot(index="segment", columns="scenario", values="uplift")
    assert (pivot["Conservative"] <= pivot["Base"] + TOL).all()
    assert (pivot["Base"] <= pivot["Optimistic"] + TOL).all()


def test_cohort_denominators_are_fixed_at_cohort_size(cohort, customers):
    sizes = customers.assign(m=customers.signup_date.dt.to_period("M").dt.to_timestamp()) \
        .groupby("m").customer_id.nunique()
    for month, group in cohort.groupby("cohort_month"):
        assert group.cohort_size.nunique() == 1, "cohort size varies within a cohort"
        assert group.cohort_size.iloc[0] == sizes.loc[month]
    assert cohort.retention_rate.between(0, 1).all()
    assert np.allclose(cohort.retention_rate, cohort.retained_customers / cohort.cohort_size)
    assert cohort.month_number.between(0, 11).all()


def test_forecast_split_is_chronological_and_held_out(forecast_summary, transactions):
    daily = transactions[transactions.transaction_status.eq("Success")].transaction_date
    last = daily.max()
    holdout_start = pd.Timestamp(forecast_summary["holdout_start"])
    holdout_end = pd.Timestamp(forecast_summary["holdout_end"])
    train_end = pd.Timestamp(forecast_summary["train_end"])
    assert forecast_summary["holdout_days"] == FORECAST_HOLDOUT_DAYS
    assert holdout_end == last, "holdout must end at the last observed day"
    assert (holdout_end - holdout_start).days == FORECAST_HOLDOUT_DAYS - 1
    assert train_end < holdout_start, "training window overlaps the holdout"


def test_forecast_starts_after_the_observed_series(forecast_summary, project_root):
    forecast = pd.read_csv(project_root / "outputs" / "forecast.csv", parse_dates=["date"])
    assert len(forecast) == FORECAST_HOLDOUT_DAYS
    assert forecast.date.min() > pd.Timestamp(forecast_summary["holdout_end"])
    assert (forecast.forecast_transactions >= 0).all()
    assert (forecast.lower_95 <= forecast.forecast_transactions).all()
    assert (forecast.upper_95 >= forecast.forecast_transactions).all()


def test_selected_model_is_the_best_on_the_holdout(forecast_summary, project_root):
    models = pd.read_csv(project_root / "outputs" / "forecast_model_comparison.csv")
    assert len(models) >= 3, "the comparison must keep the losing candidates"
    best = models.sort_values("mae").iloc[0]
    assert forecast_summary["selected_model"] == best.model
    assert abs(forecast_summary["mae"] - best.mae) < TOL
    assert abs(forecast_summary["mape"] - best.mape) < TOL
    assert 0 < forecast_summary["mape"] < 0.5
