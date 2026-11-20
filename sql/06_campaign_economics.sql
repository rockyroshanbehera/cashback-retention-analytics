-- Business question 9: What are conversion and observed cashback cost by campaign?
SELECT c.campaign_id,c.campaign_name,
 COUNT(DISTINCT a.customer_id) assigned,
 COUNT(DISTINCT CASE WHEN a.treatment_group='Treatment' THEN a.customer_id END) treated,
 COUNT(DISTINCT r.customer_id) redeemers,
 COUNT(DISTINCT r.customer_id)*1.0/COUNT(DISTINCT CASE WHEN a.treatment_group='Treatment' THEN a.customer_id END) redemption_rate,
 COALESCE(SUM(r.cashback_cost),0) cashback_cost
FROM campaigns c JOIN campaign_assignments a USING(campaign_id)
LEFT JOIN cashback_redemptions r ON r.campaign_id=a.campaign_id AND r.customer_id=a.customer_id
GROUP BY 1,2;

-- Business question 10: What is incremental post-period transaction volume?
WITH post AS (
 SELECT a.campaign_id,a.customer_id,a.treatment_group,COUNT(t.transaction_id) post_txns
 FROM campaign_assignments a JOIN campaigns c USING(campaign_id)
 LEFT JOIN transactions t ON t.customer_id=a.customer_id AND t.transaction_status='Success'
  AND julianday(t.transaction_date)-julianday(c.start_date) BETWEEN 0 AND 29
 GROUP BY 1,2,3
), summary AS (
 SELECT campaign_id,treatment_group,COUNT(*) n,AVG(post_txns) avg_post FROM post GROUP BY 1,2
)
SELECT t.campaign_id,(t.avg_post-c.avg_post)*t.n incremental_transactions
FROM summary t JOIN summary c USING(campaign_id)
WHERE t.treatment_group='Treatment' AND c.treatment_group='Control';

