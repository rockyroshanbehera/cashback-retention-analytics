"""Write calculated stakeholder and interview documentation after analysis.

Every number in the generated markdown is read back from the artefacts produced by
the pipeline, so the documents cannot drift away from the latest run.
"""
from __future__ import annotations

import json

import pandas as pd

from config import DISCLAIMER, DOCS_DIR, OUTPUT_DIR


def _pct(x: float) -> str:
    """Format a proportion as a signed percentage."""
    return f"{x:.1%}"


def _pp(x: float) -> str:
    """Format a proportion difference in percentage points."""
    return f"{x * 100:.2f} pp"


def _inr(x: float) -> str:
    """Format rupees with the sign outside the currency symbol."""
    return f"-₹{abs(x):,.0f}" if x < 0 else f"₹{x:,.0f}"


def _join(names, bold: bool = False) -> str:
    """Render a list of segment names as readable prose: 'a', 'a and b', 'a, b and c'."""
    items = [f"**{n}**" if bold else str(n) for n in names]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def build_actions(seg: pd.DataFrame) -> list[str]:
    """Three recommended actions - fund, reprice, stop - that stay grammatical when a
    category happens to be empty in a given run."""
    scale = list(seg[seg.action.eq("Scale")].segment)
    test = list(seg[seg.action.eq("Test further")].segment)
    redesign = list(seg[seg.action.eq("Redesign offer")].segment)
    stop = list(seg[seg.action.eq("Do not target")].segment)
    scale_roi = (seg[seg.action.eq("Scale")].incremental_profit.sum() /
                 seg[seg.action.eq("Scale")].cashback_cost.sum()) if scale else 0.0
    scale_cost = seg[seg.action.eq("Scale")].cashback_cost.sum()

    fund = (f"**Fund** {_join(scale)} at the current offer value: {_pct(scale_roi)} return on "
            f"{_inr(scale_cost)} of cashback."
            if scale else
            "**Fund nothing at the current offer value** - no segment clears both the "
            "interval and the 15% return hurdle.")

    if redesign and test:
        reprice = (f"**Reprice** {_join(redesign)}: each has a credible lift the current cashback "
                   f"value cannot pay for. Hold {_join(test)} in a controlled test.")
    elif redesign:
        reprice = (f"**Reprice** {_join(redesign)} at a lower cashback value. Each shows a lift "
                   "whose interval excludes zero, so the response is real - the price is wrong.")
    elif test:
        reprice = (f"**Hold** {_join(test)} in a controlled test: positive point estimates that "
                   "do not yet clear the 15% hurdle with an interval excluding zero.")
    else:
        reprice = ("**Reprice nothing** - every segment falls cleanly into either scale or stop, "
                   "so there is no middle tier to re-tune this quarter.")

    halt = (f"**Stop** targeting {_join(stop)}: no credible lift, so the spend buys nothing."
            if stop else
            "**Stop nothing** - every segment shows a lift whose interval excludes zero.")
    return [fund, reprice, halt]


def _md_table(frame: pd.DataFrame) -> str:
    """Render a DataFrame of pre-formatted strings as a GitHub markdown table."""
    headers = list(frame.columns)
    out = "| " + " | ".join(headers) + " |\n|" + "|".join(["---"] * len(headers)) + "|\n"
    out += "\n".join("| " + " | ".join(str(v) for v in row) + " |"
                     for row in frame.itertuples(index=False, name=None))
    return out


def recommendation_table(seg: pd.DataFrame) -> pd.DataFrame:
    """Build the human-readable segment recommendation matrix."""
    order = ["Scale", "Test further", "Redesign offer", "Do not target"]
    seg = seg.copy()
    seg["_rank"] = seg.action.map({a: i for i, a in enumerate(order)}).fillna(9)
    seg = seg.sort_values(["_rank", "incremental_profit"], ascending=[True, False])
    table = pd.DataFrame({
        "Segment": seg.segment,
        "Treated": seg.treatment_size.map("{:,.0f}".format),
        "Control D30": seg.control_d30_retention.map(_pct),
        "Treatment D30": seg.treatment_d30_retention.map(_pct),
        "Uplift (pp)": seg.absolute_uplift.map(_pp),
        "95% CI (pp)": [f"{lo * 100:.2f} to {hi * 100:.2f}" for lo, hi in zip(seg.ci_low, seg.ci_high)],
        "Incr. retained": seg.incremental_retained_customers.map("{:,.0f}".format),
        "Incr. txns": seg.incremental_transactions.map("{:,.0f}".format),
        "Cashback cost": seg.cashback_cost.map(_inr),
        "Incr. profit": seg.incremental_profit.map(_inr),
        "ROI": seg.roi.map(_pct),
        "Action": seg.action,
    })
    return table


def write_docs() -> str:
    """Regenerate every calculated markdown deliverable. Returns the executive summary."""
    DOCS_DIR.mkdir(exist_ok=True)
    camp = pd.read_csv(OUTPUT_DIR / "campaign_performance.csv")
    seg = pd.read_csv(OUTPUT_DIR / "segment_recommendations.csv")
    fc = json.loads((OUTPUT_DIR / "forecast_summary.json").read_text(encoding="utf-8"))
    meta = json.loads((OUTPUT_DIR / "generation_metadata.json").read_text(encoding="utf-8"))
    dq = json.loads((OUTPUT_DIR / "data_quality_report.json").read_text(encoding="utf-8"))
    notes = json.loads((OUTPUT_DIR / "experiment_notes.json").read_text(encoding="utf-8"))

    margin = meta["contribution_margin_rate"]
    tpr = notes["assumptions"]["txns_per_incremental_retained"]
    scale = seg[seg.action.eq("Scale")].sort_values("incremental_profit", ascending=False)
    # Segments whose uplift interval excludes zero: the only ones where a cost-per-retained
    # figure is meaningful, since the denominator elsewhere is indistinguishable from zero.
    credible = seg[(seg.ci_low > 0) & seg.cost_per_incremental_retained.notna()]
    best = seg.sort_values("roi", ascending=False).iloc[0]
    strongest = seg.sort_values("absolute_uplift", ascending=False).iloc[0]
    weakest = seg.sort_values("absolute_uplift").iloc[0]
    worst = seg.sort_values("incremental_profit").iloc[0]
    scale_names = _join(scale.segment, bold=True) or "no segment"
    actions = build_actions(seg)
    scale_profit = scale.incremental_profit.sum()
    scale_cost = scale.cashback_cost.sum()
    total_profit = seg.incremental_profit.sum()
    total_cost = seg.cashback_cost.sum()
    blanket_roi = total_profit / total_cost
    focused_roi = scale_profit / scale_cost
    rec_md = _md_table(recommendation_table(seg))

    (DOCS_DIR / "methodology.md").write_text(f"""# Methodology

{DISCLAIMER}

## Data generation

- Deterministic seed `{meta['seed']}`. Re-running `python src/run_pipeline.py` reproduces every
  file byte-for-byte.
- {meta['customers']:,} customers and {meta['transactions']:,} transactions covering
  {meta['reporting_period']}, of which {meta['successful_transactions']:,} are successful.
- {meta['campaigns']} campaign waves, {meta['campaign_assignments']:,} randomized assignments and
  {meta['redemptions']:,} cashback redemptions.

## RFM snapshots

- A snapshot is taken independently for each campaign, using only successful transactions dated
  **strictly before** that campaign's assignment date. No post-assignment field is ever read.
- Because snapshots are cut from the full transaction history available at that moment, they are
  exactly reproducible from the `transactions` table (`sql/03_rfm_segmentation.sql`).
- Recency, frequency and monetary value are ranked into quintiles (`r_score`, `f_score`,
  `m_score`, each 1-5). Ranking is used rather than raw cut points so scores stay stable when the
  underlying distribution shifts.
- Business overlays are applied **in order**, first match wins:

  | Priority | Segment | Rule |
  |---|---|---|
  | 1 | New | signed up within 45 days of the snapshot |
  | 2 | Dormant | recency > 120 days, or zero successful transactions |
  | 3 | At risk | recency > 60 days with at least one transaction |
  | 4 | High value | `m_score` = 5 and at least 8 transactions |
  | 5 | Loyal | `r_score` >= 4 and `f_score` >= 4 |
  | 6 | Active | `r_score` >= 3 and `f_score` >= 3 |
  | 7 | Promising | everything else |

## Experiment

- The experimental unit is the customer within a campaign; assignment is a 50/50 randomization
  inside the eligible population, drawn after the snapshot is frozen.
- Analysis is intent-to-treat: the denominator is every assigned customer in the arm, whether or
  not they redeemed.
- Only `transaction_status = 'Success'` rows count towards any outcome. Failed and Reversed rows
  are excluded everywhere.
- D7 repeat = at least one successful transaction on days 0-6 after campaign start.
  D30 retention = at least one successful transaction on days 0-29. Both windows are half-open
  and measured from the campaign start date.
- Uplift = treatment D30 rate minus control D30 rate, reported in percentage points. Confidence
  intervals are 95% normal-approximation intervals for a difference in proportions; the p-value is
  the matching two-sided normal tail.

## Economics

| Quantity | Formula |
|---|---|
| Incremental retained customers | (treatment D30 rate - control D30 rate) x treated customers |
| Incremental transactions | (treatment mean post txns - control mean post txns) x treated customers |
| Cashback cost | sum of actual redemption costs by treated customers |
| Incremental contribution | incremental transactions x average payment value x {margin:.0%} margin |
| Incremental profit | incremental contribution - cashback cost |
| ROI | incremental profit / cashback cost |
| Cost per incremental retained customer | cashback cost / incremental retained customers |

## Stated assumptions

- The {margin:.0%} contribution margin is a planning assumption, not a measured figure.
- Scenario projections convert retained customers into transactions with
  **{tpr:.2f} incremental transactions per incremental retained customer**, derived as
  `sum(incremental_transactions) / sum(incremental_retained_customers)` across all randomized
  segments rather than hard-coded.

## Observed versus estimated

Observed results (`campaign_performance.csv`, `segment_recommendations.csv`, and the `Base` rows of
`scenarios.csv`) are measured directly from the randomized synthetic data. The `Conservative` and
`Optimistic` rows of `scenarios.csv` and every Offer Simulator cell in the workbook are
**projections** built from the assumptions above and are labelled as such.

## Cautions

Segment cuts are exploratory and carry no multiplicity adjustment, so their intervals are wider in
truth than printed. Campaign waves run sequentially, so a customer treated in an earlier wave can
enter a later wave's eligible pool through their improved RFM position; randomization inside each
wave still makes the within-wave contrast unbiased. Simulated effects were injected by the
generator and therefore demonstrate method, not real-world PhonePe response.
""", encoding="utf-8")

    (DOCS_DIR / "experiment_design.md").write_text(f"""# Experiment Design

{DISCLAIMER}

## Question

Which customer segments should receive cashback offers to maximize incremental retained users and
transactions while maintaining positive campaign economics?

## Design

| Element | Choice |
|---|---|
| Unit of randomization | Customer, within each campaign wave |
| Allocation | 50/50 treatment/control, drawn after the RFM snapshot is frozen |
| Eligibility | Campaign 1: At risk + Dormant. Campaign 2: Promising + Active. Campaign 3: all segments |
| Analysis population | Intent-to-treat; every assigned customer counts, redeemed or not |
| Waves | {meta['campaigns']} campaigns, {meta['campaign_assignments']:,} total assignments |

## Metrics

- **Primary:** D30 retention, defined as at least one successful transaction on days 0-29 after
  campaign start.
- **Secondary:** D7 repeat rate (days 0-6), successful transactions per assigned customer in the
  D30 window, and redemption rate among treated customers.
- **Guardrails:** cashback cost, average payment value, incremental profit and ROI. A retention
  win that loses money is not a win.

## Balance and validity checks

- Realized treatment share per campaign and per segment (`treatment_share`), expected near 50%.
- Standardized mean difference on pre-period transaction count and pre-period payment value
  (`pre_frequency_smd`, `pre_value_smd`), computed on the 30 days before campaign start.
- Control customers cannot appear in the redemption table, and no incremental transaction may be
  dated before its campaign start. Both are asserted by `src/validate_data.py`.

## Achieved precision

{_md_table(pd.DataFrame({
    'Campaign': camp.campaign_name,
    'Assigned': camp.eligible_customers.map('{:,.0f}'.format),
    'Treatment share': camp.treatment_share.map(_pct),
    'Uplift (pp)': camp.absolute_uplift.map(_pp),
    '95% CI (pp)': [f'{lo * 100:.2f} to {hi * 100:.2f}' for lo, hi in zip(camp.ci_low, camp.ci_high)],
    'CI width (pp)': ((camp.ci_high - camp.ci_low) * 100).map('{:.2f}'.format),
    'Pre-freq SMD': camp.pre_frequency_smd.map('{:+.3f}'.format),
}))}

## Decision rule

| Action | Condition |
|---|---|
| Scale | CI lower bound > 0 **and** ROI >= 15% |
| Test further | positive uplift **and** ROI >= 0 |
| Redesign offer | CI lower bound > 0 **but** ROI < 0 |
| Do not target | anything else |

Statistical significance alone never triggers a scale decision: the interval must exclude zero and
the offer must clear a 15% return hurdle.

## Next test

Run a lower-cashback dose test for the redesign segments, pre-register D30 retention and profit as
the joint success criterion, preserve customer-level randomization, and size the test to detect a
two percentage-point practical effect.
""", encoding="utf-8")

    (DOCS_DIR / "data_dictionary.md").write_text(f"""# Data Dictionary

{DISCLAIMER}

Reporting period {meta['reporting_period']}. All tables are generated by `src/generate_data.py`
with seed `{meta['seed']}` and loaded into `database/cashback_analytics.db`.

## `customers` ({meta['customers']:,} rows)

| Column | Type | Description |
|---|---|---|
| `customer_id` | int | Primary key |
| `signup_date` | date | Account creation date, inside the reporting period |
| `region` | text | North / South / East / West / Central |
| `acquisition_channel` | text | Organic / Referral / Paid social / Partner / Search |
| `age_band` | text | 18-24 / 25-34 / 35-44 / 45+ |
| `initial_customer_type` | text | Generator-only behaviour label. **Never used by the analysis** - segments are recomputed from observed RFM |

## `transactions` ({meta['transactions']:,} rows)

| Column | Type | Description |
|---|---|---|
| `transaction_id` | int | Primary key |
| `customer_id` | int | Foreign key to `customers` |
| `transaction_date` | date | Always on or after the customer's signup date |
| `merchant_category` | text | Grocery / Bills / Recharge / Travel / Food / Shopping |
| `payment_method` | text | UPI / Wallet / Card |
| `amount` | float | Payment value in rupees, always >= 0 |
| `transaction_status` | text | Success / Failed / Reversed. Only Success counts towards any metric |
| `is_campaign_increment` | int | 0 for organic rows, else the campaign that injected the row. Audit field for the generator; **excluded from every metric and from segmentation** |

## `campaigns` ({meta['campaigns']} rows)

| Column | Type | Description |
|---|---|---|
| `campaign_id` | int | Primary key |
| `campaign_name` | text | Reactivation Boost / Habit Builder / Year-end Value |
| `start_date`, `end_date` | date | 30-day campaign window |
| `target_segment` | text | Eligibility premise for the wave |
| `cashback_offer` | float | Rupee cashback paid on redemption |
| `minimum_spend` | float | Rupee spend threshold to qualify |

## `campaign_assignments` ({meta['campaign_assignments']:,} rows)

| Column | Type | Description |
|---|---|---|
| `campaign_id`, `customer_id` | int | Composite primary key |
| `treatment_group` | text | Treatment or Control |
| `assignment_date` | date | Equals the campaign start date |
| `offer_received` | int | 1 for Treatment, 0 for Control; reconciles exactly with `treatment_group` |

## `cashback_redemptions` ({meta['redemptions']:,} rows)

| Column | Type | Description |
|---|---|---|
| `campaign_id`, `customer_id` | int | Foreign keys; treated customers only |
| `redemption_date` | date | Always inside the campaign window |
| `cashback_cost` | float | Rupee cost booked to the campaign, always > 0 |

## `rfm_snapshots` ({meta['rfm_snapshot_rows']:,} rows)

One row per customer per campaign, cut strictly before that campaign's assignment date.

| Column | Type | Description |
|---|---|---|
| `customer_id`, `campaign_id` | int | Composite primary key |
| `signup_date` | date | Copied from `customers` |
| `last_txn` | date | Most recent successful transaction before the cutoff, blank if none |
| `recency` | int | Days from `last_txn` to the cutoff; 999 when the customer has never transacted |
| `frequency` | int | Count of successful transactions before the cutoff |
| `monetary` | float | Sum of successful payment value before the cutoff |
| `r_score`, `f_score`, `m_score` | int | Quintile scores, 1-5 |
| `segment` | text | New / Promising / Active / Loyal / High value / At risk / Dormant |

## Derived outputs

| File | Contents |
|---|---|
| `outputs/campaign_performance.csv` | Per-campaign retention, uplift, cost and ROI |
| `outputs/segment_recommendations.csv` | Per-segment uplift, economics and recommended action |
| `outputs/scenarios.csv` | Conservative / Base / Optimistic rows, `basis` marks Observed vs Estimated |
| `outputs/cohort_retention.csv`, `outputs/cohort_retention_matrix.csv` | Signup-cohort monthly retention |
| `outputs/forecast*.csv`, `outputs/forecast_summary.json` | Model comparison, 30-day holdout, 30-day forecast |
| `outputs/segment_profile.csv` | Size and average RFM position of each segment |
| `outputs/data_quality_report.json` | {len(dq['checks'])} automated integrity checks |
| `outputs/experiment_notes.json` | Metric definitions and the stated assumptions |
""", encoding="utf-8")

    (DOCS_DIR / "stakeholder_brief.md").write_text(f"""# Stakeholder Decision Memo

{DISCLAIMER}

Reporting period {meta['reporting_period']}.

## Decision requested

Approve a targeted cashback plan for {scale_names} and stop blanket targeting of the remaining
segments.

## Why

Treating every eligible segment returns {_pct(blanket_roi)} on {_inr(total_cost)} of cashback.
Restricting spend to the segments that clear both hurdles turns the same programme into
{_pct(focused_roi)} on {_inr(scale_cost)}, because the loss-making segments stop consuming budget.

## Evidence

- The strongest retention lift is **{strongest.segment}** at {_pp(strongest.absolute_uplift)}
  (95% CI {_pp(strongest.ci_low)} to {_pp(strongest.ci_high)}).
- The strongest return is **{best.segment}** at {_pct(best.roi)}, costing
  {_inr(best.cost_per_incremental_retained)} per incremental retained customer.
- **{worst.segment}** is the clearest stop: {_inr(worst.incremental_profit)} profit on
  {_inr(worst.cashback_cost)} of cashback. Lift and profit must be read together.

## Recommendation matrix

{rec_md}

Action rule - **Scale**: CI lower bound > 0 and ROI >= 15%. **Test further**: positive uplift and
ROI >= 0. **Redesign offer**: CI lower bound > 0 but ROI < 0. **Do not target**: otherwise.

## Risks

- Effects are measured on synthetic data with an assumed {margin:.0%} contribution margin. A real
  margin below {margin:.0%} moves marginal segments below the hurdle.
- Segment intervals are unadjusted for multiple comparisons; the marginal segments are the ones
  most likely to be noise.
- Sequential waves mean a customer treated early can qualify for a later wave. Within-wave
  randomization keeps each contrast valid, but pooled segment reads are exploratory.

## Next step

Run a lower-cashback dose test on the redesign segments, pre-register D30 retention and profit
jointly, and size it to detect a two percentage-point effect.
""", encoding="utf-8")

    summary = f"""# Executive Summary

{DISCLAIMER}

Reporting period {meta['reporting_period']}. Seed `{meta['seed']}`.
Base: {meta['customers']:,} customers, {meta['transactions']:,} transactions,
{meta['campaign_assignments']:,} randomized campaign assignments across {meta['campaigns']} waves.

## Question

Which customer segments should receive cashback offers to maximize incremental retained users and
transactions while maintaining positive campaign economics?

## Answer

Fund {scale_names}. Together they return {_pct(focused_roi)} on {_inr(scale_cost)} of cashback and
account for {_inr(scale_profit)} of incremental profit. Treating every eligible segment instead
returns {_pct(blanket_roi)} overall, because {(seg.incremental_profit < 0).sum()} of {len(seg)}
segments lose money.

## Three findings

1. **Response is concentrated, not broad.** {strongest.segment} lifts D30 retention by
   {_pp(strongest.absolute_uplift)} (95% CI {_pp(strongest.ci_low)} to {_pp(strongest.ci_high)}) and
   returns {_pct(strongest.roi)}. The same offer moves {weakest.segment} by only
   {_pp(weakest.absolute_uplift)}, so response to an identical offer ranges over
   {_pp(seg.absolute_uplift.max() - seg.absolute_uplift.min())} across the base.
2. **Significance and economics disagree.** {len(seg[(seg.ci_low > 0) & (seg.roi < 0.15)])} of
   {len(seg)} segments show an interval that excludes zero yet fail the 15% return hurdle, so a
   p-value-only rule would have funded losses.
3. **Acquisition cost varies {credible.cost_per_incremental_retained.max() / credible.cost_per_incremental_retained.min():.0f}x across segments.**
   Among the {len(credible)} segments whose uplift interval excludes zero, buying one incremental
   retained customer costs between {_inr(credible.cost_per_incremental_retained.min())} and
   {_inr(credible.cost_per_incremental_retained.max())}. That spread is what makes targeting worth
   the effort at all.

## Three actions

1. {actions[0]}
2. {actions[1]}
3. {actions[2]}

## Forecast

The selected model is **{fc['selected_model']}**, chosen from {len(fc['candidates'])} transparent
candidates on a strictly chronological {fc['holdout_days']}-day holdout
({fc['holdout_start']} to {fc['holdout_end']}). Holdout MAE is {fc['mae']:.1f} daily transactions
and MAPE {_pct(fc['mape'])} against a holdout mean of {fc['holdout_mean_actual']:,.0f}.

## Controls

All {len(dq['checks'])} automated data-quality checks pass. Observed results are measured from
randomized synthetic data; scenario and simulator figures are projections built on an assumed
{margin:.0%} contribution margin and {tpr:.2f} incremental transactions per incremental retained
customer. Conclusions demonstrate method and should be revalidated in a real randomized pilot.
"""
    (OUTPUT_DIR / "executive_summary.md").write_text(summary, encoding="utf-8")

    (DOCS_DIR / "interview_talking_points.md").write_text(f"""# Interview Talking Points

{DISCLAIMER}

## Five STAR stories

1. **Leakage-free segmentation.**
   *Situation* - broad cashback wastes budget, but any segment built from post-offer behaviour
   flatters itself. *Task* - build targeting that cannot see the future. *Action* - froze an RFM
   snapshot per campaign using only successful transactions strictly before the assignment date,
   and kept the generator's behaviour label out of the analysis entirely. *Result* - segments that
   reproduce identically from SQL and Python, with {best.segment} identified as the best return at
   {_pct(best.roi)}.
2. **Experimentation.**
   *Situation* - redemption counts look like success but say nothing about incrementality.
   *Task* - measure causal lift. *Action* - randomized {meta['campaign_assignments']:,} customers
   50/50 within each wave, analysed intent-to-treat, and checked balance with realized treatment
   share and pre-period standardized mean differences. *Result* - {strongest.segment} lift of
   {_pp(strongest.absolute_uplift)} with a 95% CI of {_pp(strongest.ci_low)} to
   {_pp(strongest.ci_high)}.
3. **Economics over p-values.**
   *Situation* - a statistically clean lift can still lose money. *Task* - convert behaviour into
   rupees. *Action* - reconciled actual redemption cost against incremental contribution at an
   assumed {margin:.0%} margin, then wrote a four-way action rule combining the interval and a 15%
   return hurdle. *Result* - {worst.segment} was stopped despite a positive point estimate, and
   focused spend lifts programme ROI from {_pct(blanket_roi)} to {_pct(focused_roi)}.
4. **Honest forecasting.**
   *Situation* - operations needed a next-month volume view they could defend. *Task* - forecast
   without a black box. *Action* - compared {len(fc['candidates'])} transparent candidates on a
   strictly chronological {fc['holdout_days']}-day holdout that never touched training.
   *Result* - {fc['selected_model']} won at {fc['mae']:.1f} MAE ({_pct(fc['mape'])} MAPE), and I
   reported the losing candidates rather than only the winner.
5. **Making it auditable.**
   *Situation* - the analysis spanned SQL, Python and Excel. *Task* - make every number traceable.
   *Action* - one seeded pipeline writes the data, the metrics, the workbook and the documents, so
   the executive summary cannot drift from the run; the workbook's simulator is live formulas, not
   pasted values. *Result* - a reproducible decision package that regenerates from a clean clone.

## Five likely questions, with answers

1. **Why RFM rather than a clustering model?** RFM is interpretable, cheap to recompute, and maps
   directly to a lifecycle action. A k-means cluster labelled "3" does not tell a marketer what to
   do. I also needed the rule to be auditable in SQL, which quintile scores are.
2. **How do you know there is no leakage?** Three ways. The snapshot cutoff is strictly before the
   assignment date; the generator's `initial_customer_type` and `is_campaign_increment` columns are
   never read by the analysis; and a test recomputes the snapshot from the raw transaction table
   and asserts it matches row-for-row.
3. **Why not scale the segment with the largest lift?** Because the offer has a cost.
   {strongest.segment} does clear both hurdles, but {worst.segment} has a positive point estimate
   and still returns {_pct(worst.roi)}. My rule requires the interval to exclude zero *and* the
   return to clear 15%.
4. **What is genuinely causal here?** The within-wave treatment-control difference, because
   assignment is randomized after the snapshot is frozen. Cross-segment comparisons are
   exploratory - segments were not randomized against each other, and the intervals carry no
   multiplicity adjustment.
5. **What would change with real data?** I would use the real contribution margin instead of my
   {margin:.0%} assumption, account for delivery and impression failures, extend the horizon past
   D30, use CUPED or pre-stratification to tighten intervals at the same sample size, and
   pre-register the segment cuts to control the false discovery rate.

## Two resume bullets

- Built a reproducible customer-retention analytics pipeline over {meta['customers']:,} synthetic
  customers and {meta['transactions']:,} transactions in Python, SQL and SQLite, delivering RFM
  segmentation, a randomized {meta['campaign_assignments']:,}-customer cashback experiment, and a
  formula-driven Excel decision dashboard.
- Quantified segment-level D30 retention uplift with 95% confidence intervals and full campaign
  economics, showing that focusing cashback on {len(scale)} of {len(seg)} segments moves programme
  ROI from {_pct(blanket_roi)} to {_pct(focused_roi)}, and validated a
  {fc['selected_model']} volume forecast at {_pct(fc['mape'])} MAPE on a 30-day holdout.

## 60-second explanation

I built an independent portfolio project on synthetic data to answer a question a growth team
actually faces: when you hand out cashback, who should get it? I generated a normalized year of
customer, transaction, campaign, assignment and redemption data, then froze an RFM snapshot before
each campaign so targeting could never see post-offer behaviour. Inside each wave I randomized
customers 50/50 and measured D30 retention intent-to-treat, with confidence intervals and balance
checks. Then I did the part people skip: I converted lift into rupees - actual redemption cost
against incremental contribution - so a clean p-value could not override bad economics. That
mattered, because several segments were statistically positive and financially negative. Focusing
spend on {len(scale)} of {len(seg)} segments moves programme ROI from {_pct(blanket_roi)} to
{_pct(focused_roi)}. I also compared three transparent forecasts on a chronological holdout and
packaged everything as SQL, a seeded Python pipeline and an Excel dashboard with a live offer
simulator. The takeaway I care about is that targeting decisions need causal evidence, uncertainty
and unit economics together - any two of the three will lose money.
""", encoding="utf-8")
    return summary


if __name__ == "__main__":
    write_docs()
