"""Export the latest pre-campaign RFM snapshot and a per-segment profile."""
from __future__ import annotations

import pandas as pd

from config import DATA_DIR, OUTPUT_DIR


def build_segments() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Write the most recent leakage-free RFM snapshot plus an aggregated profile."""
    rfm = pd.read_csv(DATA_DIR / "rfm_snapshots.csv")
    latest = rfm[rfm.campaign_id.eq(rfm.campaign_id.max())]
    latest.to_csv(OUTPUT_DIR / "rfm_segments.csv", index=False)
    latest.head(250).to_csv(OUTPUT_DIR / "rfm_segments_sample.csv", index=False)
    profile = (latest.groupby("segment")
               .agg(customers=("customer_id", "size"), avg_recency_days=("recency", "mean"),
                    avg_frequency=("frequency", "mean"), avg_monetary=("monetary", "mean"),
                    avg_r_score=("r_score", "mean"), avg_f_score=("f_score", "mean"),
                    avg_m_score=("m_score", "mean"))
               .reset_index().sort_values("customers", ascending=False))
    profile["share_of_base"] = profile.customers / profile.customers.sum()
    profile.to_csv(OUTPUT_DIR / "segment_profile.csv", index=False)
    return latest, profile


if __name__ == "__main__":
    build_segments()
