"""Pytest hooks: default ``unit`` marker for tests without slow/integration scope."""

from __future__ import annotations

import pytest


_NON_UNIT_MARKERS = frozenset(
    {"integration", "orchestration", "slow", "requires_data", "requires_model"},
)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Attach ``unit`` to tests that are not explicitly slow or integration-scoped."""
    for item in items:
        names = {m.name for m in item.iter_markers()}
        if names & _NON_UNIT_MARKERS:
            continue
        item.add_marker(pytest.mark.unit)
