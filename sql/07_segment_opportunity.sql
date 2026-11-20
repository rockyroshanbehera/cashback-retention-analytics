-- Business question 11: Which segments show the largest D30 retention opportunity?
WITH outcome AS (
 SELECT a.campaign_id,a.customer_id,a.treatment_group,r.segment,
  MAX(CASE WHEN julianday(t.transaction_date)-julianday(c.start_date) BETWEEN 0 AND 29 THEN 1 ELSE 0 END) retained
 FROM campaign_assignments a JOIN campaigns c USING(campaign_id)
 JOIN rfm_snapshots r ON r.campaign_id=a.campaign_id AND r.customer_id=a.customer_id
 LEFT JOIN transactions t ON t.customer_id=a.customer_id AND t.transaction_status='Success'
 GROUP BY 1,2,3,4
), rates AS (
 SELECT segment,treatment_group,AVG(retained) rate,COUNT(*) n FROM outcome GROUP BY 1,2
), uplift AS (
 SELECT t.segment,t.rate-c.rate uplift,t.n treated_n,
        (t.rate-c.rate)*t.n incremental_retained
 FROM rates t JOIN rates c USING(segment)
 WHERE t.treatment_group='Treatment' AND c.treatment_group='Control'
)
SELECT *,RANK() OVER(ORDER BY incremental_retained DESC) opportunity_rank
FROM uplift ORDER BY opportunity_rank;

