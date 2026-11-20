"""Signup-cohort monthly retention using fixed cohort denominators."""
import pandas as pd
from config import DATA_DIR, OUTPUT_DIR


def build_cohorts():
    customers = pd.read_csv(DATA_DIR / "customers.csv", parse_dates=["signup_date"])
    tx = pd.read_csv(DATA_DIR / "transactions.csv", parse_dates=["transaction_date"])
    customers["cohort_month"] = customers.signup_date.dt.to_period("M").dt.to_timestamp()
    success = tx[tx.transaction_status.eq("Success")][["customer_id", "transaction_date"]].drop_duplicates()
    activity = success.merge(customers[["customer_id", "cohort_month"]], on="customer_id")
    activity["activity_month"] = activity.transaction_date.dt.to_period("M").dt.to_timestamp()
    activity["month_number"] = ((activity.activity_month.dt.year - activity.cohort_month.dt.year) * 12 +
                                 activity.activity_month.dt.month - activity.cohort_month.dt.month)
    activity = activity[activity.month_number.between(0, 11)]
    retained = activity.groupby(["cohort_month", "month_number"]).customer_id.nunique().rename("retained_customers")
    sizes = customers.groupby("cohort_month").customer_id.nunique().rename("cohort_size")
    cohort = retained.reset_index().merge(sizes, on="cohort_month")
    cohort["retention_rate"] = cohort.retained_customers / cohort.cohort_size
    cohort.to_csv(OUTPUT_DIR / "cohort_retention.csv", index=False)
    pivot = cohort.pivot(index="cohort_month", columns="month_number", values="retention_rate").reset_index()
    pivot.to_csv(OUTPUT_DIR / "cohort_retention_matrix.csv", index=False)
    return cohort, pivot


if __name__ == "__main__":
    build_cohorts()

