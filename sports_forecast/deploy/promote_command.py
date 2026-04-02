"""Utilities for per-tournament promote commands in orchestration."""

from __future__ import annotations


def build_promote_per_tournament_command(
    project_dir: str,
    uv_run: str,
    tournaments_expr: str,
    market_spec_expr: str,
    metric: str,
    direction: str,
    top_n: int = 5,
) -> str:
    """Build bash command that promotes models per tournament.

    Args:
        project_dir: Project root directory used in DAG shell commands.
        uv_run: Command prefix for running Python with environment tools.
        tournaments_expr: Raw tournaments expression, usually Airflow params.
        market_spec_expr: Market spec expression, usually Airflow params.
        metric: Primary metric used by promoter.
        direction: Metric optimization direction (minimize/maximize).
        top_n: Number of top candidates for promoter compare/select.

    Returns:
        Bash command string that iterates tournaments and runs promoter
        separately for each tournament-specific experiment.
    """
    return (
        f"cd {project_dir} && "
        "set -e && "
        f'TOURNAMENTS_RAW="{tournaments_expr}" && '
        "IFS=',' read -r -a tournaments <<< \"$TOURNAMENTS_RAW\" && "
        "valid_count=0 && "
        'for tournament in "${tournaments[@]}"; do '
        "tournament=\"$(printf '%s' \"$tournament\" | tr -d '[:space:]')\"; "
        '[ -z "$tournament" ] && continue; '
        "valid_count=$((valid_count + 1)); "
        f"{uv_run} python -m sports_forecast.deploy.promoter "
        f'--experiment "${{tournament}}__{market_spec_expr}" '
        f"--metric {metric} "
        f"--direction {direction} "
        f"--top-n {top_n} || exit 1; "
        "done && "
        '[ "$valid_count" -gt 0 ]'
    )
