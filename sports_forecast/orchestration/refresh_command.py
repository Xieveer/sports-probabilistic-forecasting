"""Builders for tournament-scoped refresh orchestration commands."""

# R41.5 — optional skip of ``features_build`` (not implemented): design notes
# ---------------------------------------------------------------------------
# A fingerprint could short-circuit heavy feature generation when inputs are
# bitwise unchanged (hashes or mtimes of tracked raw/interim artefacts + odds merge
# manifests). Decision point belongs *before* emitting the ``features_build`` CLI chunk
# in :func:`build_refresh_per_tournament_command` or in a wrapper used by Airflow/Makefile.
#
# Edge cases requiring **forced** rebuild:
# - NHL API retrospective boxscore/stats corrections (historical rows change silently).
# - Odds incremental merge that alters parquet without bumping naive file mtimes you track.
# - Any manual edit under ``data/source/<tournament>/`` not covered by the fingerprint set.
#
# Relation to DVC: the repo ``dvc.yaml`` still models ``features`` as a multirun across
# tournaments; tournament-scoped skips are an **operational** optimisation, not a substitute
# for ``dvc repro`` in dev/CI. See ``docs/cursor/context/service_orchestration_architecture.md``
# («Матрица operational-контракта DVC» и ограничение multirun).

from __future__ import annotations


# Source stage по умолчанию в Airflow: ``python -m sports_forecast.orchestration.source_refresh``
# (см. ``dag_data_refresh.SF_SOURCE_REFRESH_CMD``) — единая точка для file и NHL Web API.


def _render_source_stage_command(source_cmd: str) -> str:
    """Render source stage shell snippet for a tournament.

    Contract:
    - Preferred: command template contains ``{tournament}`` placeholder.
    - Legacy: plain command without placeholder receives ``"$tournament"``
      as a positional argument.
    """
    if "{tournament}" in source_cmd:
        return source_cmd.replace("{tournament}", '"$tournament"')
    return f'{source_cmd} "$tournament"'


def build_refresh_per_tournament_command(
    *,
    project_dir: str,
    uv_run: str,
    tournaments_expr: str,
    features_config: str,
    market: str,
    market_spec: str,
    source_cmd: str,
    lock_file: str,
    lock_wait_seconds: int,
    algorithm_config: str = "catboost",
) -> str:
    """Build a fail-fast shell command for tournament refresh pipeline.

    Pipeline for each tournament:
    ``source -> ingest -> clean -> features -> materialize``.

    Для ``materialize`` в CLI передаются ``algorithm`` и ``features`` (требование
    корневого Hydra ``conf/config.yaml``). При ``model_version=prod`` фактическая
    модель берётся из ``models/.../best/deploy.yaml`` (promoted contract), если он есть.
    """
    return (
        "set -e && "
        f'flock -w {lock_wait_seconds} "{lock_file}" /bin/bash -lc \''
        f"set -e && cd {project_dir} && "
        f"IFS=',' read -r -a tournaments <<< \"{tournaments_expr}\" && "
        "valid_count=0; "
        'for tournament in "${tournaments[@]}"; do '
        'tournament="${tournament// /}"; '
        '[ -n "$tournament" ] || continue; '
        "valid_count=$((valid_count + 1)); "
        f"{_render_source_stage_command(source_cmd)} && "
        f'SF_TOURNAMENT_FILTER="$tournament" {uv_run} python -m sports_forecast.data.ingest && '
        f'SF_TOURNAMENT_FILTER="$tournament" {uv_run} python -m sports_forecast.data.clean && '
        f'{uv_run} python -m sports_forecast.features.features_build tournament="$tournament" features={features_config} && '
        f'{uv_run} python -m sports_forecast.materialize tournament="$tournament" '
        f"market={market} market_spec={market_spec} algorithm={algorithm_config} "
        f"features={features_config} || exit 1; "
        "done; "
        '[ "$valid_count" -gt 0 ]'
        "'"
    )
