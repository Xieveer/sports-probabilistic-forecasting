"""Jinja shell snippet for Airflow ``BashOperator`` running :mod:`post_refresh_digest`.

The template reads Airflow Variables at **task runtime** so digest can be toggled without
redeploying DAG code (``SF_TELEGRAM_DIGEST_ENABLE``, ``SF_POST_REFRESH_DIGEST_CMD``).
"""

from __future__ import annotations

import shlex
from textwrap import dedent


def build_post_refresh_digest_bash_command(*, project_dir: str, uv_run: str) -> str:
    """Build ``bash_command`` for ``post_refresh_digest`` with conditional skip (digest Variables).

    Args:
        project_dir: Repository root inside the executor (typically ``SF_PROJECT_DIR``).
        uv_run: Prefix for invoking Python (typically ``SF_UV_RUN``, e.g. ``uv run``).

    Returns:
        Shell script body with embedded Jinja for Airflow 2 templating engine.
    """
    tmpl = dedent(
        """
        {% set _en = (var.value.get('SF_TELEGRAM_DIGEST_ENABLE', 'true') | lower | trim) %}
        {% if _en in ['0', 'false', 'no', 'off'] %}
        echo "post_refresh_digest skipped (SF_TELEGRAM_DIGEST_ENABLE)" && exit 0
        {% else %}
        {% set _cmd = (var.value.get('SF_POST_REFRESH_DIGEST_CMD', '') | default('', true) | trim) %}
        set -euo pipefail
        cd __PROJECT_DIR__ && \
        {% if _cmd %}
        bash -lc {{ _cmd | tojson }}
        {% else %}
        __UV_RUN__ python -m sports_forecast.orchestration.post_refresh_digest \
          --tournament {{ dag_run.conf.get("tournament", params.tournament) | tojson }} \
          --market {{ dag_run.conf.get("market", params.market) | tojson }} \
          --market-spec {{ dag_run.conf.get("market_spec", params.market_spec) | tojson }} \
          --project-root __PROJECT_ROOT__
        {% endif %}
        {% endif %}
        """
    ).strip()
    qdir = shlex.quote(project_dir)
    return (
        tmpl.replace("__PROJECT_DIR__", qdir)
        .replace("__PROJECT_ROOT__", qdir)
        .replace("__UV_RUN__", uv_run)
    )
