# Experiment Design

Independent portfolio project using synthetic data. Not affiliated with or based on internal data from PhonePe.

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
| Waves | 3 campaigns, 27,861 total assignments |

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

| Campaign | Assigned | Treatment share | Uplift (pp) | 95% CI (pp) | CI width (pp) | Pre-freq SMD |
|---|---|---|---|---|---|---|
| Reactivation Boost | 3,861 | 50.5% | 12.98 pp | 9.90 to 16.06 | 6.16 | +0.000 |
| Habit Builder | 12,000 | 49.3% | 11.16 pp | 9.49 to 12.83 | 3.34 | +0.008 |
| Year-end Value | 12,000 | 50.9% | 8.83 pp | 7.15 to 10.51 | 3.36 | -0.015 |

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
