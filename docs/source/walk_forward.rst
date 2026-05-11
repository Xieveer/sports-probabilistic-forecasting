Walk-forward simulation during training
=======================================

When ``walk_forward.enabled`` is ``true``, the holdout (or trailing test split) is
evaluated in **calendar-month** steps instead of a single static cut. After the usual
initialization phase (Optuna only on the inner train, TSCV, optional calibration,
feature selection), the trainer:

#. fixes hyperparameters from that init phase;
#. for each month in the OOS window, retrains on an **expanding** training set
   (core train plus all prior OOS months), predicts the current month, logs ML and
   optional betting metrics;
#. aggregates OOS predictions and (if betting is enabled) concatenates per-step bet
   traces, then computes cumulative ROI / Sharpe / drawdown via :class:`BettingSimulator`.

Configuration (Hydra group ``walk_forward``) lives in ``conf/walk_forward.yaml`` and is
included from the root ``conf/config.yaml`` defaults. Defaults keep
``enabled: false`` so existing runs are unchanged.

Key options
-----------

- ``enabled`` — master switch.
- ``frequency`` — only ``month`` is implemented (UTC-style month boundaries on the
  configured time column; naive datetimes follow calendar months).
- ``init_train_end`` — optional inclusive end timestamp for the core train window;
  if null, the trainer uses ``max(datetime)`` over the train split.
- ``reuse_optuna_params`` — if true (default), every refit uses the merged Optuna /
  config params from init; if false, only base config params apply.

MLflow
------

Runs log tags ``walk_forward``, ``wf_n_steps``, ``wf_frequency``, ``wf_init_train_end``,
per-step metrics (``wf_step_logloss``, ``wf_step_auc``, … with ``step`` index),
aggregates ``wf_agg_*``, artifact ``wf_per_step_metrics.csv``, and
``cumulative_bet_trace.csv`` when betting traces are produced.

See also :doc:`feature_selection_workflow` for the broader training phases.

When ``feature_selection.apply_selected_to_fit`` is ``true`` together with walk-forward,
the trainer still **re-fits** shadow (TSCV, calibration) on the selected column subset before
the WF phase. A pre-WF holdout snapshot ``metrics_full`` (``test_full_*``, ``full_betting_*``,
etc.) is **not** logged, because the static holdout evaluation is skipped while WF is on;
MLflow tags ``primary_feature_set=selected`` and ``fs_fit_applied=true`` still reflect that the
primary model uses the reduced feature set.
