-- Business question 4: How can customers be scored on pre-campaign recency, frequency, and value?
WITH base AS (
  SELECT a.campaign_id, a.customer_id, c.start_date,
         CAST(julianday(c.start_date)-julianday(MAX(t.transaction_date)) AS INT) recency,
         COUNT(t.transaction_id) frequency, COALESCE(SUM(t.amount),0) monetary
  FROM campaign_assignments a JOIN campaigns c USING(campaign_id)
  LEFT JOIN transactions t ON t.customer_id=a.customer_id
   AND t.transaction_status='Success' AND date(t.transaction_date)<date(c.start_date)
  GROUP BY 1,2,3
), scores AS (
  SELECT *, 6-NTILE(5) OVER(PARTITION BY campaign_id ORDER BY COALESCE(recency,999)) r_score,
         NTILE(5) OVER(PARTITION BY campaign_id ORDER BY frequency) f_score,
         NTILE(5) OVER(PARTITION BY campaign_id ORDER BY monetary) m_score
  FROM base
)
SELECT * FROM scores ORDER BY campaign_id, customer_id;

-- Business question 5: How large is each leakage-free RFM segment?
SELECT campaign_id, segment, COUNT(*) customers,
       AVG(recency) avg_recency, AVG(frequency) avg_frequency, AVG(monetary) avg_monetary
FROM rfm_snapshots GROUP BY 1,2 ORDER BY 1, customers DESC;

