"""The committed SQL must reproduce the metrics the Python pipeline reports.

Each test runs SQL against the generated SQLite database and compares the answer with the
corresponding figure in the pipeline's CSV outputs. If the two ever disagree, one of them
is wrong and the dashboard cannot be trusted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TOL = 1e-6


def test_sql_files_are_present_and_documented(project_root):
    sql_dir = project_root / "sql"
    files = sorted(sql_dir.glob("*.sql"))
    assert len(files) == 8, f"expected 8 SQL files, found {len(files)}"
    questions = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert text.strip(), f"{path.name} is empty"
        questions += text.count("-- Business question")
    assert questions >= 13, f"expected at least 13 documented business questions, found {questions}"


def test_sql_row_counts_match_python(db, customers, transactions, assignments):
    assert db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == len(customers)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == len(transactions)
    assert db.execute("SELECT COUNT(*) FROM campaign_assignments").fetchone()[0] == len(assignments)


def test_sql_d30_retention_matches_python(db, campaign_results):
    """sql/05_experiment_analysis.sql, business question 7."""
    query = """
    WITH outcomes AS (
      SELECT a.campaign_id, a.customer_id, a.treatment_group,
             MAX(CASE WHEN julianday(t.transaction_date) - julianday(c.start_date)
                      BETWEEN 0 AND 29 THEN 1 ELSE 0 END) d30
      FROM campaign_assignments a
      JOIN campaigns c USING (campaign_id)
      LEFT JOIN transactions t ON t.customer_id = a.customer_id
        AND t.transaction_status = 'Success'
      GROUP BY 1, 2, 3
    )
    SELECT campaign_id, treatment_group, COUNT(*) n, AVG(d30) d30_rate
    FROM outcomes GROUP BY 1, 2
    """
    sql = pd.read_sql_query(query, db).set_index(["campaign_id", "treatment_group"])
    for row in campaign_results.itertuples(index=False):
        assert abs(sql.loc[(row.campaign_id, "Treatment"), "d30_rate"] - row.treatment_d30_retention) < TOL
        assert abs(sql.loc[(row.campaign_id, "Control"), "d30_rate"] - row.control_d30_retention) < TOL
        assert sql.loc[(row.campaign_id, "Treatment"), "n"] == row.treatment_size
        assert sql.loc[(row.campaign_id, "Control"), "n"] == row.control_size


def test_sql_incremental_transactions_match_python(db, campaign_results):
    """sql/06_campaign_economics.sql, business question 10."""
    query = """
    WITH post AS (
      SELECT a.campaign_id, a.customer_id, a.treatment_group, COUNT(t.transaction_id) post_txns
      FROM campaign_assignments a
      JOIN campaigns c USING (campaign_id)
      LEFT JOIN transactions t ON t.customer_id = a.customer_id
        AND t.transaction_status = 'Success'
        AND julianday(t.transaction_date) - julianday(c.start_date) BETWEEN 0 AND 29
      GROUP BY 1, 2, 3
    ), summary AS (
      SELECT campaign_id, treatment_group, COUNT(*) n, AVG(post_txns) avg_post
      FROM post GROUP BY 1, 2
    )
    SELECT t.campaign_id, (t.avg_post - c.avg_post) * t.n incremental_transactions
    FROM summary t JOIN summary c USING (campaign_id)
    WHERE t.treatment_group = 'Treatment' AND c.treatment_group = 'Control'
    """
    sql = pd.read_sql_query(query, db).set_index("campaign_id")
    for row in campaign_results.itertuples(index=False):
        expected = sql.loc[row.campaign_id, "incremental_transactions"]
        assert abs(expected - row.incremental_transactions) < 1e-6


def test_sql_cashback_cost_matches_python(db, campaign_results):
    """sql/06_campaign_economics.sql, business question 9."""
    query = """
    SELECT a.campaign_id,
           COUNT(DISTINCT r.customer_id) redeemers,
           COALESCE(SUM(r.cashback_cost), 0) cashback_cost
    FROM campaign_assignments a
    LEFT JOIN cashback_redemptions r
      ON r.campaign_id = a.campaign_id AND r.customer_id = a.customer_id
    WHERE a.treatment_group = 'Treatment'
    GROUP BY 1
    """
    sql = pd.read_sql_query(query, db).set_index("campaign_id")
    for row in campaign_results.itertuples(index=False):
        assert abs(sql.loc[row.campaign_id, "cashback_cost"] - row.cashback_cost) < TOL


def test_sql_segment_uplift_matches_python(db, segment_results):
    """sql/07_segment_opportunity.sql, business question 11."""
    query = """
    WITH outcome AS (
      SELECT a.campaign_id, a.customer_id, a.treatment_group, r.segment,
             MAX(CASE WHEN julianday(t.transaction_date) - julianday(c.start_date)
                      BETWEEN 0 AND 29 THEN 1 ELSE 0 END) retained
      FROM campaign_assignments a
      JOIN campaigns c USING (campaign_id)
      JOIN rfm_snapshots r ON r.campaign_id = a.campaign_id AND r.customer_id = a.customer_id
      LEFT JOIN transactions t ON t.customer_id = a.customer_id
        AND t.transaction_status = 'Success'
      GROUP BY 1, 2, 3, 4
    ), rates AS (
      SELECT segment, treatment_group, AVG(retained) rate, COUNT(*) n
      FROM outcome GROUP BY 1, 2
    )
    SELECT t.segment, t.rate - c.rate uplift, t.n treated_n,
           (t.rate - c.rate) * t.n incremental_retained
    FROM rates t JOIN rates c USING (segment)
    WHERE t.treatment_group = 'Treatment' AND c.treatment_group = 'Control'
    """
    sql = pd.read_sql_query(query, db).set_index("segment")
    for row in segment_results.itertuples(index=False):
        assert sql.loc[row.segment, "treated_n"] == row.treatment_size
        assert abs(sql.loc[row.segment, "uplift"] - row.absolute_uplift) < TOL
        assert abs(sql.loc[row.segment, "incremental_retained"] -
                   row.incremental_retained_customers) < 1e-6


def test_sql_cohort_retention_matches_python(db, cohort):
    """sql/04_cohort_retention.sql, business question 6."""
    query = """
    WITH cohort AS (
      SELECT customer_id, substr(signup_date, 1, 7) cohort_month FROM customers
    ), activity AS (
      SELECT DISTINCT customer_id, substr(transaction_date, 1, 7) activity_month
      FROM transactions WHERE transaction_status = 'Success'
    ), grid AS (
      SELECT c.cohort_month, c.customer_id,
             (CAST(substr(a.activity_month, 1, 4) AS INT) -
              CAST(substr(c.cohort_month, 1, 4) AS INT)) * 12 +
              CAST(substr(a.activity_month, 6, 2) AS INT) -
              CAST(substr(c.cohort_month, 6, 2) AS INT) month_number
      FROM cohort c JOIN activity a USING (customer_id)
    ), sizes AS (SELECT cohort_month, COUNT(*) cohort_size FROM cohort GROUP BY 1)
    SELECT g.cohort_month, g.month_number,
           COUNT(DISTINCT g.customer_id) retained_customers, s.cohort_size
    FROM grid g JOIN sizes s USING (cohort_month)
    WHERE month_number BETWEEN 0 AND 11
    GROUP BY 1, 2
    """
    sql = pd.read_sql_query(query, db)
    sql["cohort_month"] = pd.to_datetime(sql.cohort_month + "-01")
    merged = cohort.merge(sql, on=["cohort_month", "month_number"], how="outer",
                          suffixes=("_py", "_sql"))
    assert merged.retained_customers_py.notna().all(), "Python is missing cohort cells SQL found"
    assert merged.retained_customers_sql.notna().all(), "SQL is missing cohort cells Python found"
    assert (merged.retained_customers_py == merged.retained_customers_sql).all()
    assert (merged.cohort_size_py == merged.cohort_size_sql).all()


def test_sql_forecast_split_matches_python(db, forecast_summary):
    """sql/08_forecast_inputs.sql, business question 12."""
    query = """
    WITH daily AS (
      SELECT date(transaction_date) d, COUNT(*) transactions
      FROM transactions WHERE transaction_status = 'Success' GROUP BY 1
    )
    SELECT CASE WHEN d >= date((SELECT MAX(date(transaction_date)) FROM transactions), '-29 day')
                THEN 'holdout' ELSE 'train' END split,
           COUNT(*) days, MIN(d) first_day, MAX(d) last_day
    FROM daily GROUP BY 1
    """
    sql = pd.read_sql_query(query, db).set_index("split")
    assert sql.loc["holdout", "days"] == forecast_summary["holdout_days"]
    assert sql.loc["holdout", "first_day"] == forecast_summary["holdout_start"]
    assert sql.loc["holdout", "last_day"] == forecast_summary["holdout_end"]
    assert sql.loc["train", "last_day"] == forecast_summary["train_end"]


def test_sql_rfm_segment_sizes_match_python(db, project_root):
    """sql/03_rfm_segmentation.sql, business question 5."""
    profile = pd.read_csv(project_root / "outputs" / "segment_profile.csv").set_index("segment")
    latest = db.execute("SELECT MAX(campaign_id) FROM rfm_snapshots").fetchone()[0]
    sql = pd.read_sql_query(
        "SELECT segment, COUNT(*) customers, AVG(recency) avg_recency, AVG(frequency) avg_frequency "
        f"FROM rfm_snapshots WHERE campaign_id = {latest} GROUP BY 1", db).set_index("segment")
    for segment in profile.index:
        assert sql.loc[segment, "customers"] == profile.loc[segment, "customers"]
        assert abs(sql.loc[segment, "avg_recency"] - profile.loc[segment, "avg_recency_days"]) < 1e-6
        assert abs(sql.loc[segment, "avg_frequency"] - profile.loc[segment, "avg_frequency"]) < 1e-6


def test_sql_pre_campaign_balance_matches_python(db, campaign_results):
    """sql/05_experiment_analysis.sql, business question 8."""
    query = """
    WITH pre AS (
      SELECT a.campaign_id, a.customer_id, a.treatment_group, COUNT(t.transaction_id) pre_txns
      FROM campaign_assignments a
      JOIN campaigns c USING (campaign_id)
      LEFT JOIN transactions t ON t.customer_id = a.customer_id
        AND t.transaction_status = 'Success'
        AND date(t.transaction_date) >= date(c.start_date, '-30 day')
        AND date(t.transaction_date) < date(c.start_date)
      GROUP BY 1, 2, 3
    )
    SELECT campaign_id, treatment_group, AVG(pre_txns) avg_pre_txns FROM pre GROUP BY 1, 2
    """
    sql = pd.read_sql_query(query, db).set_index(["campaign_id", "treatment_group"])
    for row in campaign_results.itertuples(index=False):
        assert abs(sql.loc[(row.campaign_id, "Treatment"), "avg_pre_txns"] -
                   row.treatment_pre_frequency) < TOL
        assert abs(sql.loc[(row.campaign_id, "Control"), "avg_pre_txns"] -
                   row.control_pre_frequency) < TOL
