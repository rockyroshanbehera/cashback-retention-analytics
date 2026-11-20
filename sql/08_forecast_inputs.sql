-- Business question 12: What daily series should feed a leakage-free time-based forecast?
WITH RECURSIVE dates(d) AS (
 SELECT MIN(date(transaction_date)) FROM transactions
 UNION ALL SELECT date(d,'+1 day') FROM dates
 WHERE d < (SELECT MAX(date(transaction_date)) FROM transactions)
), daily AS (
 SELECT date(transaction_date) d,COUNT(*) transactions
 FROM transactions WHERE transaction_status='Success' GROUP BY 1
)
SELECT dates.d,COALESCE(daily.transactions,0) transactions,
 CASE WHEN dates.d >= date((SELECT MAX(date(transaction_date)) FROM transactions),'-29 day')
      THEN 'holdout' ELSE 'train' END split
FROM dates LEFT JOIN daily USING(d) ORDER BY dates.d;

-- Business question 13: What are monthly trend and category contributions?
SELECT substr(transaction_date,1,7) month,merchant_category,COUNT(*) transactions,
       SUM(amount) payment_value,
       RANK() OVER(PARTITION BY substr(transaction_date,1,7) ORDER BY COUNT(*) DESC) category_rank
FROM transactions WHERE transaction_status='Success'
GROUP BY 1,2 ORDER BY 1,category_rank;

