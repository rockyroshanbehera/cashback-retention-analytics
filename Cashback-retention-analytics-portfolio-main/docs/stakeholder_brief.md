# Stakeholder Decision Memo

Independent portfolio project using synthetic data. Not affiliated with or based on internal data from PhonePe.

Reporting period 2025-01-01 to 2025-12-31.

## Decision requested

Approve a targeted cashback plan for **Promising**, **At risk** and **New** and stop blanket targeting of the remaining
segments.

## Why

Treating every eligible segment returns 10.1% on ₹187,630 of cashback.
Restricting spend to the segments that clear both hurdles turns the same programme into
39.8% on ₹100,805, because the loss-making segments stop consuming budget.

## Evidence

- The strongest retention lift is **At risk** at 24.61 pp
  (95% CI 20.88 pp to 28.35 pp).
- The strongest return is **At risk** at 45.9%, costing
  ₹76 per incremental retained customer.
- **Active** is the clearest stop: -₹7,792 profit on
  ₹53,005 of cashback. Lift and profit must be read together.

## Recommendation matrix

| Segment | Treated | Control D30 | Treatment D30 | Uplift (pp) | 95% CI (pp) | Incr. retained | Incr. txns | Cashback cost | Incr. profit | ROI | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Promising | 4,501 | 54.1% | 70.4% | 16.23 pp | 14.27 to 18.18 | 730 | 2,079 | ₹70,025 | ₹27,918 | 39.9% | Scale |
| At risk | 1,289 | 43.6% | 68.2% | 24.61 pp | 20.88 to 28.35 | 317 | 745 | ₹24,030 | ₹11,025 | 45.9% | Scale |
| New | 803 | 56.0% | 61.3% | 5.25 pp | 0.35 to 10.15 | 42 | 148 | ₹6,750 | ₹1,157 | 17.1% | Scale |
| High value | 1,178 | 87.5% | 90.3% | 2.87 pp | 0.31 to 5.43 | 34 | 197 | ₹16,850 | -₹2,633 | -15.6% | Redesign offer |
| Dormant | 1,660 | 27.6% | 30.8% | 3.20 pp | 0.10 to 6.31 | 53 | 75 | ₹7,620 | -₹4,304 | -56.5% | Redesign offer |
| Active | 3,879 | 69.1% | 75.3% | 6.22 pp | 4.22 to 8.21 | 241 | 891 | ₹53,005 | -₹7,792 | -14.7% | Redesign offer |
| Loyal | 657 | 77.8% | 79.8% | 1.98 pp | -2.49 to 6.45 | 13 | 63 | ₹9,350 | -₹6,490 | -69.4% | Do not target |

Action rule - **Scale**: CI lower bound > 0 and ROI >= 15%. **Test further**: positive uplift and
ROI >= 0. **Redesign offer**: CI lower bound > 0 but ROI < 0. **Do not target**: otherwise.

## Risks

- Effects are measured on synthetic data with an assumed 8% contribution margin. A real
  margin below 8% moves marginal segments below the hurdle.
- Segment intervals are unadjusted for multiple comparisons; the marginal segments are the ones
  most likely to be noise.
- Sequential waves mean a customer treated early can qualify for a later wave. Within-wave
  randomization keeps each contrast valid, but pooled segment reads are exploratory.

## Next step

Run a lower-cashback dose test on the redesign segments, pre-register D30 retention and profit
jointly, and size it to detect a two percentage-point effect.
