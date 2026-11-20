# Methodology

Independent portfolio project using synthetic data. Not affiliated with or based on internal data from PhonePe.

## Data generation

- Deterministic seed `20260813`. Re-running `python src/run_pipeline.py` reproduces every
  file byte-for-byte.
- 40,000 customers and 373,237 transactions covering
  2025-01-01 to 2025-12-31, of which 360,210 are successful.
- 3 campaign waves, 27,861 randomized assignments and
  4,502 cashback redemptions.

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
| Incremental contribution | incremental transactions x average payment value x 8% margin |
| Incremental profit | incremental contribution - cashback cost |
| ROI | incremental profit / cashback cost |
| Cost per incremental retained customer | cashback cost / incremental retained customers |

## Stated assumptions

- The 8% contribution margin is a planning assumption, not a measured figure.
- Scenario projections convert retained customers into transactions with
  **2.93 incremental transactions per incremental retained customer**, derived as
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
