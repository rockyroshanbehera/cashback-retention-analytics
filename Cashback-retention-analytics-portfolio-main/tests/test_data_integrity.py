"""Schema, key, referential-integrity and value-range checks on the generated data."""
from __future__ import annotations

import pandas as pd

EXPECTED_COLUMNS = {
    "customers": ["customer_id", "signup_date", "region", "acquisition_channel", "age_band",
                  "initial_customer_type"],
    "transactions": ["transaction_id", "customer_id", "transaction_date", "merchant_category",
                     "payment_method", "amount", "transaction_status", "is_campaign_increment"],
    "campaigns": ["campaign_id", "campaign_name", "start_date", "end_date", "target_segment",
                  "cashback_offer", "minimum_spend"],
    "campaign_assignments": ["campaign_id", "customer_id", "treatment_group", "assignment_date",
                             "offer_received"],
    "cashback_redemptions": ["campaign_id", "customer_id", "redemption_date", "cashback_cost"],
    "rfm_snapshots": ["customer_id", "signup_date", "last_txn", "frequency", "monetary", "recency",
                      "r_score", "f_score", "m_score", "segment", "campaign_id"],
}


def test_schemas_match_expected(customers, transactions, campaigns, assignments, redemptions, rfm):
    frames = {"customers": customers, "transactions": transactions, "campaigns": campaigns,
              "campaign_assignments": assignments, "cashback_redemptions": redemptions,
              "rfm_snapshots": rfm}
    for name, expected in EXPECTED_COLUMNS.items():
        assert list(frames[name].columns) == expected, f"{name} schema drifted"


def test_primary_keys_unique(customers, transactions, campaigns, assignments, rfm):
    assert customers.customer_id.is_unique
    assert transactions.transaction_id.is_unique
    assert campaigns.campaign_id.is_unique
    assert not assignments.duplicated(["campaign_id", "customer_id"]).any()
    assert not rfm.duplicated(["campaign_id", "customer_id"]).any()


def test_referential_integrity(customers, transactions, campaigns, assignments, redemptions, rfm):
    ids = set(customers.customer_id)
    cids = set(campaigns.campaign_id)
    assert set(transactions.customer_id) <= ids
    assert set(assignments.customer_id) <= ids
    assert set(assignments.campaign_id) <= cids
    assert set(redemptions.customer_id) <= ids
    assert set(redemptions.campaign_id) <= cids
    assert set(rfm.customer_id) <= ids
    # Every redemption must correspond to an actual assignment row.
    merged = redemptions.merge(assignments, on=["campaign_id", "customer_id"], how="left")
    assert merged.treatment_group.notna().all(), "redemption without an assignment"


def test_dates_are_valid(customers, transactions, campaigns, redemptions, metadata):
    start = pd.Timestamp(metadata["start_date"])
    end = pd.Timestamp(metadata["end_date"])
    assert customers.signup_date.between(start, end).all()
    assert transactions.transaction_date.between(start, end).all()
    # No transaction may predate its customer's signup.
    merged = transactions.merge(customers[["customer_id", "signup_date"]], on="customer_id")
    assert (merged.transaction_date >= merged.signup_date).all()
    # Redemptions fall inside their campaign window.
    r = redemptions.merge(campaigns[["campaign_id", "start_date", "end_date"]], on="campaign_id")
    assert (r.redemption_date >= r.start_date).all()
    assert (r.redemption_date <= r.end_date).all()


def test_amounts_are_non_negative(transactions, redemptions, campaigns):
    assert (transactions.amount >= 0).all()
    assert (redemptions.cashback_cost > 0).all()
    assert (campaigns.cashback_offer > 0).all()
    assert (campaigns.minimum_spend > 0).all()


def test_no_missing_values_in_critical_fields(customers, transactions, assignments):
    assert not customers.isna().any().any()
    critical = ["transaction_id", "customer_id", "transaction_date", "amount", "transaction_status"]
    assert not transactions[critical].isna().any().any()
    assert not assignments.isna().any().any()


def test_categorical_domains(transactions, assignments):
    assert set(transactions.transaction_status) <= {"Success", "Failed", "Reversed"}
    assert set(transactions.payment_method) <= {"UPI", "Wallet", "Card"}
    assert set(assignments.treatment_group) == {"Treatment", "Control"}


def test_sqlite_row_counts_match_csv(db, customers, transactions, campaigns, assignments,
                                     redemptions, rfm):
    expected = {"customers": len(customers), "transactions": len(transactions),
                "campaigns": len(campaigns), "campaign_assignments": len(assignments),
                "cashback_redemptions": len(redemptions), "rfm_snapshots": len(rfm)}
    for table, n in expected.items():
        actual = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert actual == n, f"{table}: database has {actual} rows, CSV has {n}"


def test_metadata_matches_generated_data(metadata, customers, transactions, assignments, redemptions):
    assert metadata["customers"] == len(customers)
    assert metadata["transactions"] == len(transactions)
    assert metadata["campaign_assignments"] == len(assignments)
    assert metadata["redemptions"] == len(redemptions)
    assert metadata["successful_transactions"] == int(transactions.transaction_status.eq("Success").sum())


def test_quality_report_all_passed(quality_report):
    failed = [k for k, v in quality_report["checks"].items() if not v]
    assert not failed, f"data-quality checks failed: {failed}"
