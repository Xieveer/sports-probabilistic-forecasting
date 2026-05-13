"""Unit tests for ``sports_forecast.orchestration.digest_message``."""

from __future__ import annotations

from datetime import datetime, timezone

from sports_forecast.orchestration.digest_message import (
    DigestMatchLine,
    build_post_refresh_digest_text,
)


def test_build_post_refresh_digest_text_sorted_msk_and_format() -> None:
    """Сортировка по времени, MSK, prob/kf/edge, итоги дом и гость."""
    m_late = DigestMatchLine(
        home_player="Echo",
        away_player="Foxtrot",
        commence_utc=datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
        proba_home=0.4,
        pinnacle_home_decimal=2.5,
        pinnacle_away_decimal=1.55,
        edge_home=-0.12,
        edge_away=0.08,
        bet_decision_home="no_bet",
        bet_decision_away="bet",
    )
    m_early = DigestMatchLine(
        home_player="Alpha",
        away_player="Beta",
        commence_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        proba_home=0.55,
        pinnacle_home_decimal=2.0,
        pinnacle_away_decimal=1.9,
        edge_home=0.05,
        edge_away=-0.03,
        bet_decision_home="bet",
        bet_decision_away="no_bet",
    )
    m_mid = DigestMatchLine(
        home_player="Gamma",
        away_player="Delta",
        commence_utc=datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc),
        proba_home=None,
        pinnacle_home_decimal=None,
        pinnacle_away_decimal=None,
        edge_home=None,
        edge_away=None,
        bet_decision_home="insufficient_data",
        bet_decision_away="insufficient_data",
    )
    got = build_post_refresh_digest_text(
        matches=[m_late, m_early, m_mid],
        provenance_line="test-run v1",
        edge_threshold=0.03,
    )
    assert "Топ по |edge|" not in got
    assert "Модель (provenance):" in got
    assert "Критерий bet" in got and "0.03" in got
    assert "каждая сторона" in got
    assert "Расписание:" in got
    pos_a = got.index("Alpha")
    pos_g = got.index("Gamma")
    pos_e = got.index("Echo")
    assert pos_a < pos_g < pos_e
    assert "MSK" in got
    assert "prob=0.550/0.450" in got
    assert "kf=2.00/1.90" in got
    assert "Итог дом (Alpha):" in got and "ставка @" in got
    assert "Итог гость (Beta):" in got and "без ставки" in got
    assert "Итог гость (Foxtrot):" in got and "ставка @" in got
    assert "Итог дом (Echo):" in got and "без ставки" in got
    assert "Итог дом (Gamma):" in got and "нет линии" in got
    assert "Итог гость (Delta):" in got and "нет линии" in got


def test_build_post_refresh_digest_text_missing_api_key_empty_matches() -> None:
    got = build_post_refresh_digest_text(
        matches=[],
        provenance_line="",
        odds_warning="missing_api_key",
        edge_threshold=0.05,
    )
    assert "missing_api_key" in got
    assert "Всего матчей: 0" in got
    assert "0.05" in got


def test_build_post_refresh_digest_text_truncation_suffix_and_max_len() -> None:
    max_chars = 120
    got = build_post_refresh_digest_text(
        matches=[],
        provenance_line="Z" * 200,
        max_chars=max_chars,
        edge_threshold=None,
    )
    assert len(got) == max_chars
    assert got.endswith(f"\n… [обрезано до {max_chars} символов]")


def test_edges_recomputed_when_missing_but_kf_present() -> None:
    """Если edge_* в строке None, но есть prob и kf — пересчёт внутри билдера."""
    m = DigestMatchLine(
        home_player="H",
        away_player="A",
        commence_utc=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc),
        proba_home=0.5,
        pinnacle_home_decimal=2.0,
        pinnacle_away_decimal=2.0,
        edge_home=None,
        edge_away=None,
        bet_decision_home="no_bet",
        bet_decision_away="no_bet",
    )
    got = build_post_refresh_digest_text(matches=[m], provenance_line="x", edge_threshold=0.03)
    assert "edge=+0.000/+0.000" in got or "edge=+0.000" in got
