# Interview Talking Points

Independent portfolio project using synthetic data. Not affiliated with or based on internal data from PhonePe.

## Five STAR stories

1. **Leakage-free segmentation.**
   *Situation* - broad cashback wastes budget, but any segment built from post-offer behaviour
   flatters itself. *Task* - build targeting that cannot see the future. *Action* - froze an RFM
   snapshot per campaign using only successful transactions strictly before the assignment date,
   and kept the generator's behaviour label out of the analysis entirely. *Result* - segments that
   reproduce identically from SQL and Python, with At risk identified as the best return at
   45.9%.
2. **Experimentation.**
   *Situation* - redemption counts look like success but say nothing about incrementality.
   *Task* - measure causal lift. *Action* - randomized 27,861 customers
   50/50 within each wave, analysed intent-to-treat, and checked balance with realized treatment
   share and pre-period standardized mean differences. *Result* - At risk lift of
   24.61 pp with a 95% CI of 20.88 pp to
   28.35 pp.
3. **Economics over p-values.**
   *Situation* - a statistically clean lift can still lose money. *Task* - convert behaviour into
   rupees. *Action* - reconciled actual redemption cost against incremental contribution at an
   assumed 8% margin, then wrote a four-way action rule combining the interval and a 15%
   return hurdle. *Result* - Active was stopped despite a positive point estimate, and
   focused spend lifts programme ROI from 10.1% to 39.8%.
4. **Honest forecasting.**
   *Situation* - operations needed a next-month volume view they could defend. *Task* - forecast
   without a black box. *Action* - compared 3 transparent candidates on a
   strictly chronological 30-day holdout that never touched training.
   *Result* - 7-day seasonal naive won at 127.0 MAE (7.8% MAPE), and I
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
   At risk does clear both hurdles, but Active has a positive point estimate
   and still returns -14.7%. My rule requires the interval to exclude zero *and* the
   return to clear 15%.
4. **What is genuinely causal here?** The within-wave treatment-control difference, because
   assignment is randomized after the snapshot is frozen. Cross-segment comparisons are
   exploratory - segments were not randomized against each other, and the intervals carry no
   multiplicity adjustment.
5. **What would change with real data?** I would use the real contribution margin instead of my
   8% assumption, account for delivery and impression failures, extend the horizon past
   D30, use CUPED or pre-stratification to tighten intervals at the same sample size, and
   pre-register the segment cuts to control the false discovery rate.

## Two resume bullets

- Built a reproducible customer-retention analytics pipeline over 40,000 synthetic
  customers and 373,237 transactions in Python, SQL and SQLite, delivering RFM
  segmentation, a randomized 27,861-customer cashback experiment, and a
  formula-driven Excel decision dashboard.
- Quantified segment-level D30 retention uplift with 95% confidence intervals and full campaign
  economics, showing that focusing cashback on 3 of 7 segments moves programme
  ROI from 10.1% to 39.8%, and validated a
  7-day seasonal naive volume forecast at 7.8% MAPE on a 30-day holdout.

## 60-second explanation

I built an independent portfolio project on synthetic data to answer a question a growth team
actually faces: when you hand out cashback, who should get it? I generated a normalized year of
customer, transaction, campaign, assignment and redemption data, then froze an RFM snapshot before
each campaign so targeting could never see post-offer behaviour. Inside each wave I randomized
customers 50/50 and measured D30 retention intent-to-treat, with confidence intervals and balance
checks. Then I did the part people skip: I converted lift into rupees - actual redemption cost
against incremental contribution - so a clean p-value could not override bad economics. That
mattered, because several segments were statistically positive and financially negative. Focusing
spend on 3 of 7 segments moves programme ROI from 10.1% to
39.8%. I also compared three transparent forecasts on a chronological holdout and
packaged everything as SQL, a seeded Python pipeline and an Excel dashboard with a live offer
simulator. The takeaway I care about is that targeting decisions need causal evidence, uncertainty
and unit economics together - any two of the three will lose money.
