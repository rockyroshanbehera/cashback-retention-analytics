"""Transparent baseline and Holt-Winters forecast with time-based holdout."""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

from config import DATA_DIR, FORECAST_HOLDOUT_DAYS, OUTPUT_DIR


def build_forecast():
    tx = pd.read_csv(DATA_DIR / "transactions.csv", parse_dates=["transaction_date"])
    daily = (tx[tx.transaction_status.eq("Success")].groupby("transaction_date").size()
             .reindex(pd.date_range(tx.transaction_date.min(), tx.transaction_date.max(), freq="D"), fill_value=0)
             .astype(float))
    # Strictly chronological split: the last FORECAST_HOLDOUT_DAYS days are never used to
    # fit or select a model, so holdout error is an honest out-of-sample estimate.
    train, test = daily.iloc[:-FORECAST_HOLDOUT_DAYS], daily.iloc[-FORECAST_HOLDOUT_DAYS:]
    preds = {
        "7-day seasonal naive": np.resize(train.iloc[-7:].to_numpy(), len(test)),
        "28-day moving average": np.repeat(train.iloc[-28:].mean(), len(test)),
    }
    def holt_winters_additive(values, horizon, period=7, alpha=.24, beta=.04, gamma=.18):
        values = np.asarray(values, dtype=float)
        level = values[:period].mean()
        trend = (values[period:2*period].mean() - level) / period
        season = values[:period] - level
        for i, value in enumerate(values):
            prior_level = level
            s = season[i % period]
            level = alpha * (value - s) + (1 - alpha) * (level + trend)
            trend = beta * (level - prior_level) + (1 - beta) * trend
            season[i % period] = gamma * (value - level) + (1 - gamma) * s
        return np.array([level + (h + 1) * trend + season[(len(values) + h) % period]
                         for h in range(horizon)])
    preds["Holt-Winters additive"] = holt_winters_additive(train.values, len(test))
    scores = pd.DataFrame([{"model": k, "mae": np.mean(np.abs(v - test.to_numpy())),
                            "mape": np.mean(np.abs(v - test.to_numpy()) / np.maximum(test.to_numpy(), 1))}
                           for k, v in preds.items()]).sort_values("mae")
    best = scores.iloc[0].model
    horizon = FORECAST_HOLDOUT_DAYS
    if best == "Holt-Winters additive":
        fc = holt_winters_additive(daily.values, horizon)
    elif best == "7-day seasonal naive":
        fc = np.resize(daily.iloc[-7:].to_numpy(), horizon)
    else:
        fc = np.repeat(daily.iloc[-28:].mean(), horizon)
    resid = test.to_numpy() - preds[best]
    sigma = np.std(resid, ddof=1)
    future_dates = pd.date_range(daily.index.max() + pd.Timedelta(days=1), periods=horizon)
    forecast = pd.DataFrame({"date": future_dates, "forecast_transactions": np.maximum(0, fc),
                             "lower_95": np.maximum(0, fc - 1.96 * sigma), "upper_95": fc + 1.96 * sigma})
    holdout = pd.DataFrame({"date": test.index, "actual": test.values, "prediction": preds[best]})
    scores.to_csv(OUTPUT_DIR / "forecast_model_comparison.csv", index=False)
    forecast.to_csv(OUTPUT_DIR / "forecast.csv", index=False)
    holdout.to_csv(OUTPUT_DIR / "forecast_holdout.csv", index=False)
    info = {"selected_model": best, "holdout_days": FORECAST_HOLDOUT_DAYS,
            "candidates": scores.model.tolist(),
            "train_start": str(train.index.min().date()), "train_end": str(train.index.max().date()),
            "holdout_start": str(test.index.min().date()), "holdout_end": str(test.index.max().date()),
            "forecast_start": str(future_dates.min().date()), "forecast_end": str(future_dates.max().date()),
            "mae": float(scores.iloc[0].mae), "mape": float(scores.iloc[0].mape),
            "holdout_mean_actual": float(test.mean()),
            "interval_method": "forecast +/- 1.96 x holdout residual SD"}
    (OUTPUT_DIR / "forecast_summary.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return scores, forecast, holdout


if __name__ == "__main__":
    build_forecast()
