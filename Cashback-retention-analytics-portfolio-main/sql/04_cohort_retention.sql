-- Business question 6: What share of each signup cohort is active in subsequent months?
WITH cohort AS (
 SELECT customer_id, substr(signup_date,1,7) cohort_month FROM customers
), activity AS (
 SELECT DISTINCT customer_id, substr(transaction_date,1,7) activity_month
 FROM transactions WHERE transaction_status='Success'
), grid AS (
 SELECT c.cohort_month, a.activity_month, c.customer_id,
  (CAST(substr(a.activity_month,1,4) AS INT)-CAST(substr(c.cohort_month,1,4) AS INT))*12+
   CAST(substr(a.activity_month,6,2) AS INT)-CAST(substr(c.cohort_month,6,2) AS INT) month_number
 FROM cohort c JOIN activity a USING(customer_id)
), sizes AS (SELECT cohort_month, COUNT(*) cohort_size FROM cohort GROUP BY 1)
SELECT g.cohort_month, g.month_number, COUNT(DISTINCT g.customer_id) retained_customers,
       COUNT(DISTINCT g.customer_id)*1.0/s.cohort_size retention_rate
FROM grid g JOIN sizes s USING(cohort_month) WHERE month_number BETWEEN 0 AND 11
GROUP BY 1,2 ORDER BY 1,2;

