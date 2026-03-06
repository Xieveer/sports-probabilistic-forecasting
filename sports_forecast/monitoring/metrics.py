"""Prometheus custom metrics для ML мониторинга.

Определяет кастомные Gauge и Counter метрики, которые экспортируются
через ``/metrics`` endpoint FastAPI.

Метрики:
    - ``sf_model_predictions_total``: Общее кол-во предсказаний.
    - ``sf_model_prediction_latency``: Латенция предсказаний.
    - ``sf_model_auc``: AUC модели на новых данных.
    - ``sf_model_logloss``: LogLoss на новых данных.
    - ``sf_model_ece``: ECE на новых данных.
    - ``sf_model_roi``: ROI на реальных ставках.
    - ``sf_drift_score``: Score дрифта данных (PSI / KS).
    - ``sf_model_last_retrained``: Timestamp последнего переобучения.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


# ── Request / inference metrics ──────────────────────────────────────

PREDICTION_COUNT = Counter(
    "sf_model_predictions_total",
    "Total number of predictions served",
    ["tournament", "market"],
)

PREDICTION_LATENCY = Histogram(
    "sf_model_prediction_latency_seconds",
    "Prediction serving latency in seconds",
    ["tournament"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# ── Model quality metrics ────────────────────────────────────────────

MODEL_AUC = Gauge(
    "sf_model_auc",
    "AUC on recent data",
    ["tournament", "market_spec"],
)

MODEL_LOGLOSS = Gauge(
    "sf_model_logloss",
    "LogLoss on recent data",
    ["tournament", "market_spec"],
)

MODEL_ECE = Gauge(
    "sf_model_ece",
    "Expected Calibration Error on recent data",
    ["tournament", "market_spec"],
)

MODEL_BRIER = Gauge(
    "sf_model_brier",
    "Brier Score on recent data",
    ["tournament", "market_spec"],
)

# ── Business metrics ─────────────────────────────────────────────────

MODEL_ROI = Gauge(
    "sf_model_roi_pct",
    "ROI % on real bets",
    ["tournament", "market_spec"],
)

MODEL_PROFIT = Gauge(
    "sf_model_profit_units",
    "Profit in units",
    ["tournament", "market_spec"],
)

MODEL_N_BETS = Gauge(
    "sf_model_n_bets",
    "Number of bets placed",
    ["tournament", "market_spec"],
)

# ── Drift metrics ────────────────────────────────────────────────────

DRIFT_SCORE = Gauge(
    "sf_drift_score",
    "Data drift score (PSI / KS statistic)",
    ["tournament", "feature"],
)

PREDICTION_DRIFT = Gauge(
    "sf_prediction_drift",
    "Prediction distribution drift (PSI)",
    ["tournament", "market_spec"],
)

# ── System metrics ───────────────────────────────────────────────────

LAST_RETRAINED_TS = Gauge(
    "sf_model_last_retrained_timestamp",
    "Unix timestamp of last model retrain",
    ["tournament", "market_spec"],
)

LAST_MATERIALIZE_TS = Gauge(
    "sf_model_last_materialize_timestamp",
    "Unix timestamp of last prediction materialization",
    ["tournament"],
)

ACTIVE_MODELS_COUNT = Gauge(
    "sf_active_models_count",
    "Number of active models in production",
)
