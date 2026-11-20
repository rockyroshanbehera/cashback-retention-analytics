-- Business question 7: What are treatment/control D7 and D30 retention rates?
WITH outcomes AS (
 SELECT a.campaign_id,a.customer_id,a.treatment_group,
  MAX(CASE WHEN julianday(t.transaction_date)-julianday(c.start_date) BETWEEN 0 AND 6 THEN 1 ELSE 0 END) d7,
  MAX(CASE WHEN julianday(t.transaction_date)-julianday(c.start_date) BETWEEN 0 AND 29 THEN 1 ELSE 0 END) d30
 FROM campaign_assignments a JOIN campaigns c USING(campaign_id)
 LEFT JOIN transactions t ON t.customer_id=a.customer_id AND t.transaction_status='Success'
 GROUP BY 1,2,3
)
SELECT campaign_id,treatment_group,COUNT(*) customers,AVG(d7) d7_rate,AVG(d30) d30_rate
FROM outcomes GROUP BY 1,2 ORDER BY 1,2;

-- Business question 8: Is randomized assignment balanced on pre-campaign frequency?
WITH pre AS (
 SELECT a.campaign_id,a.customer_id,a.treatment_group,COUNT(t.transaction_id) pre_txns
 FROM campaign_assignments a JOIN campaigns c USING(campaign_id)
 LEFT JOIN transactions t ON t.customer_id=a.customer_id AND t.transaction_status='Success'
  AND date(t.transaction_date)>=date(c.start_date,'-30 day') AND date(t.transaction_date)<date(c.start_date)
 GROUP BY 1,2,3
)
SELECT campaign_id,treatment_group,COUNT(*) n,AVG(pre_txns) avg_pre_txns
FROM pre GROUP BY 1,2 ORDER BY 1,2;

