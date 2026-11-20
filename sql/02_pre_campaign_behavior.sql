-- Business question 3: What was each assigned customer's 30-day pre-campaign behavior?
WITH pre AS (
  SELECT a.campaign_id, a.customer_id, a.treatment_group,
         COUNT(t.transaction_id) AS pre_txns,
         COALESCE(SUM(t.amount),0) AS pre_value
  FROM campaign_assignments a
  JOIN campaigns c USING (campaign_id)
  LEFT JOIN transactions t ON t.customer_id=a.customer_id
   AND t.transaction_status='Success'
   AND date(t.transaction_date)>=date(c.start_date,'-30 day')
   AND date(t.transaction_date)<date(c.start_date)
  GROUP BY 1,2,3
)
SELECT campaign_id, treatment_group, COUNT(*) customers,
       AVG(pre_txns) avg_pre_txns, AVG(pre_value) avg_pre_value
FROM pre GROUP BY 1,2 ORDER BY 1,2;

