-- Business question 1: Are primary keys unique and required fields populated?
SELECT COUNT(*) AS rows, COUNT(DISTINCT customer_id) AS unique_ids,
       SUM(customer_id IS NULL OR signup_date IS NULL) AS critical_nulls
FROM customers;

-- Business question 2: Are transaction foreign keys and values valid?
SELECT SUM(c.customer_id IS NULL) AS orphan_transactions,
       SUM(t.amount < 0) AS negative_amounts,
       SUM(t.transaction_date < c.signup_date) AS transactions_before_signup
FROM transactions t LEFT JOIN customers c USING (customer_id);

