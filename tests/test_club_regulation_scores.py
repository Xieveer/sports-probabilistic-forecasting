"""Проверка допуска кубковых результатов основного времени."""

import pandas as pd
from omegaconf import OmegaConf

from sports_forecast.data import ingest
from sports_forecast.validation.club_regulation_scores import audit_regulation_scores


def _match(match_id: int, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "match_id": match_id,
        "competition_code": "UCL",
        "match_status": "Матч окончен",
        "match_is_end": 1,
        "home_score_ft": 2,
        "away_score_ft": 2,
        "home_goals_all": 2,
        "away_goals_all": 2,
        "home_goals_1h": 1,
        "away_goals_1h": 0,
        "home_goals_2h": 1,
        "away_goals_2h": 2,
    }
    row.update(overrides)
    return row


def test_audit_accepts_regulation_draw_and_quarantines_uncertain_scores() -> None:
    frame = pd.DataFrame(
        [
            _match(1),
            _match(2, home_goals_2h=None),
            _match(3, match_status="matches.status.is-walkover"),
            _match(4, home_score_ft=3),
            _match(5, home_goals_1h=1.5),
        ]
    )
    accepted, rejected = audit_regulation_scores(frame)
    assert accepted.match_id.tolist() == [1]
    assert rejected.match_id.tolist() == [2, 3, 4, 5]
    assert rejected.reason.tolist() == [
        "missing_period_score",
        "not_played",
        "score_mismatch",
        "invalid_score",
    ]


def test_audit_rejects_missing_contract_column() -> None:
    frame = pd.DataFrame([_match(1)]).drop(columns="away_goals_2h")
    try:
        audit_regulation_scores(frame)
    except ValueError as exc:
        assert "away_goals_2h" in str(exc)
    else:
        raise AssertionError("Неполная схема должна останавливать аудит")


def test_club_ingest_excludes_quarantined_cup_match(tmp_path, monkeypatch) -> None:
    """Карантин применяется до записи raw parquet для обучения."""
    source_dir = tmp_path / "football_top_leagues"
    source_dir.mkdir()
    source = source_dir / "source.csv"
    pd.DataFrame(
        [
            _match(1),
            _match(2, home_goals_2h=None),
            _match(3, competition_code="ENG1"),
            _match(
                4,
                match_is_end=0,
                match_status="Не начался",
                home_score_ft=None,
                away_score_ft=None,
                home_goals_all=None,
                away_goals_all=None,
                home_goals_1h=None,
                away_goals_1h=None,
                home_goals_2h=None,
                away_goals_2h=None,
            ),
        ]
    ).to_csv(source, index=False)

    class LocalProvider:
        def fetch(self, _name: str):
            return source

    monkeypatch.setattr(ingest, "load_source_config", lambda _name: None)
    monkeypatch.setattr(ingest, "get_provider", lambda *_args: LocalProvider())
    monkeypatch.setattr(
        "sports_forecast.identity.data_provenance.identity_mode_for_tournament",
        lambda *_args: False,
    )
    raw_root = tmp_path / "raw"
    ingest.process_tournament(source_dir, raw_root, OmegaConf.create({}))
    raw = pd.read_parquet(raw_root / "football_top_leagues" / "matches.parquet")
    assert raw.match_id.tolist() == ["1", "3", "4"]
