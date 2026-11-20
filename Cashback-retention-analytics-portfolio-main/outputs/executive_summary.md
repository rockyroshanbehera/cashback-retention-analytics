# Executive Summary

Independent portfolio project using synthetic data. Not affiliated with or based on internal data from PhonePe.

Reporting period 2025-01-01 to 2025-12-31. Seed `20260813`.
Base: 40,000 customers, 373,237 transactions,
27,861 randomized campaign assignments across 3 waves.

## Question

Which customer segments should receive cashback offers to maximize incremental retained users and
transactions while maintaining positive campaign economics?

## Answer

Fund **Promising**, **At risk** and **New**. Together they return 39.8% on ₹100,805 of cashback and
account for ₹40,099 of incremental profit. Treating every eligible segment instead
returns 10.1% overall, because 4 of 7
segments lose money.

## Three findings

1. **Response is concentrated, not broad.** At risk lifts D30 retention by
   24.61 pp (95% CI 20.88 pp to 28.35 pp) and
   returns 45.9%. The same offer moves Loyal by only
   1.98 pp, so response to an identical offer ranges over
   22.63 pp across the base.
2. **Significance and economics disagree.** 3 of
   7 segments show an interval that excludes zero yet fail the 15% return hurdle, so a
   p-value-only rule would have funded losses.
3. **Acquisition cost varies 7x across segments.**
   Among the 6 segments whose uplift interval excludes zero, buying one incremental
   retained customer costs between ₹76 and
   ₹499. That spread is what makes targeting worth
   the effort at all.

## Three actions

1. **Fund** At risk, New and Promising at the current offer value: 39.8% return on ₹100,805 of cashback.
2. **Reprice** Active, Dormant and High value at a lower cashback value. Each shows a lift whose interval excludes zero, so the response is real - the price is wrong.
3. **Stop** targeting Loyal: no credible lift, so the spend buys nothing.

## Forecast

The selected model is **7-day seasonal naive**, chosen from 3 transparent
candidates on a strictly chronological 30-day holdout
(2025-12-02 to 2025-12-31). Holdout MAE is 127.0 daily transactions
and MAPE 7.8% against a holdout mean of 1,711.

## Controls

All 16 automated data-quality checks pass. Observed results are measured from
randomized synthetic data; scenario and simulator figures are projections built on an assumed
8% contribution margin and 2.93 incremental transactions per incremental retained
customer. Conclusions demonstrate method and should be revalidated in a real randomized pilot.
