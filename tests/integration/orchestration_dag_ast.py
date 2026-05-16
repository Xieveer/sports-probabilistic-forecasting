"""AST helpers for Airflow DAG source files (no apache-airflow runtime required)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DagSourceInfo:
    """Structured metadata parsed from a DAG Python file."""

    dag_id: str | None
    task_ids: tuple[str, ...]


def _dag_call_keywords(
    call: ast.Call,
) -> dict[str, ast.expr]:
    """Return keyword arguments as a mapping for a Call node."""
    out: dict[str, ast.expr] = {}
    for kw in call.keywords:
        if kw.arg is not None:
            out[kw.arg] = kw.value
    return out


def _const_str_value(node: ast.expr) -> str | None:
    """Extract a string from a Constant or joined str if trivial."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def parse_dag_source_info(path: Path) -> DagSourceInfo:
    """Parse ``dag_id`` and operator ``task_id`` values from a DAG module on disk.

    Args:
        path: Path to a ``dag_*.py`` file under ``airflow/dags/``.

    Returns:
        Parsed ``dag_id`` (if found) and all ``task_id`` arguments on supported operators.

    Note:
        Intended for smoke tests only; does not execute the DAG or import Airflow.
        Recognises ``bash_*`` task factories from ``sf_scheduled_refresh_ops`` (R41.3).
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    dag_id: str | None = None
    task_ids: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                ctx = item.context_expr
                if not isinstance(ctx, ast.Call):
                    continue
                func = ctx.func
                if not (isinstance(func, ast.Name) and func.id == "DAG"):
                    continue
                keywords = _dag_call_keywords(ctx)
                if "dag_id" in keywords:
                    dag_id = _const_str_value(keywords["dag_id"])
        if isinstance(node, ast.Call):
            func = node.func
            op_name: str | None = None
            if isinstance(func, ast.Name):
                op_name = func.id
            elif isinstance(func, ast.Attribute):
                op_name = func.attr
            factory_ops = frozenset(
                {
                    "bash_refresh_per_tournament",
                    "bash_run_validation",
                    "bash_post_refresh_digest",
                    "BashOperator",
                    "BranchPythonOperator",
                }
            )
            if op_name in factory_ops:
                keywords = _dag_call_keywords(node)
                tid = keywords.get("task_id")
                if tid is not None:
                    s = _const_str_value(tid)
                    if s is not None:
                        task_ids.append(s)

    return DagSourceInfo(dag_id=dag_id, task_ids=tuple(task_ids))


def normalized_source_lines(path: Path) -> str:
    """Return source with runs of whitespace removed (for robust substring checks)."""
    text = path.read_text(encoding="utf-8")
    return "".join(text.split())
