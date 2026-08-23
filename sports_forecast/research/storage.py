"""Файловое durable-хранилище Research Mode v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from sports_forecast.research.contracts import DataSourceRecord, ResearchState


class ResearchRepository:
    """Хранит состояние и Data Source Catalog одного локального research workspace.

    Args:
        root: Корневая директория workspace Research Mode.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def create(self, state: ResearchState) -> None:
        """Создать новый run и его initial state."""
        self.save(state)

    def load(self, run_id: str) -> ResearchState:
        """Загрузить и валидировать durable state по идентификатору run."""
        path = self._state_path(run_id)
        return cast(
            ResearchState,
            ResearchState.model_validate_json(path.read_text(encoding="utf-8")),
        )

    def save(self, state: ResearchState) -> None:
        """Атомарно сохранить состояние после валидированного перехода."""
        path = self._state_path(state.run_id)
        self._write_json(path, state.model_dump(mode="json"))

    def save_source(self, source: DataSourceRecord) -> None:
        """Обновить каноническую карточку Data Source Catalog."""
        path = self.root / "data-sources" / f"{source.source_id}.json"
        self._write_json(path, source.model_dump(mode="json"))

    def _state_path(self, run_id: str) -> Path:
        return self.root / "runs" / run_id / "state.json"

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
