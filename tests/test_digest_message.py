"""Unit tests for ``sports_forecast.orchestration.digest_message``."""

from __future__ import annotations

from sports_forecast.orchestration.digest_message import (
    DigestMatchLine,
    build_post_refresh_digest_text,
)


def test_build_post_refresh_digest_text_golden_three_matches() -> None:
    matches = [
        DigestMatchLine(
            "Alpha",
            "Beta",
            "2026-01-01T12:00:00",
            0.05,
            "value_home",
            "ok",
        ),
        DigestMatchLine(
            "Gamma",
            "Delta",
            "2026-01-02T12:00:00",
            None,
            None,
            "no_key",
        ),
        DigestMatchLine(
            "Echo",
            "Foxtrot",
            "2026-01-03T12:00:00",
            -0.12,
            None,
            "",
        ),
    ]
    got = build_post_refresh_digest_text(
        matches=matches,
        provenance_line="test-run v1",
    )
    expected = (
        "Всего матчей: 3\n"
        "\n"
        "**Модель (provenance):**\n"
        "test-run v1\n"
        "\n"
        "**Топ по |edge|** (до 8):\n"
        "• Echo — Foxtrot @ 2026-01-03T12:00:00 edge=-0.120\n"
        "• Alpha — Beta @ 2026-01-01T12:00:00 live=ok edge=+0.050 bet=value_home\n"
        "\n"
        "**Все матчи (кратко):**\n"
        "• Alpha — Beta @ 2026-01-01T12:00:00 live=ok edge=+0.050 bet=value_home\n"
        "• Gamma — Delta @ 2026-01-02T12:00:00 live=no_key\n"
        "• Echo — Foxtrot @ 2026-01-03T12:00:00 edge=-0.120"
    )
    assert got == expected


def test_build_post_refresh_digest_text_missing_api_key_empty_matches() -> None:
    got = build_post_refresh_digest_text(
        matches=[],
        provenance_line="",
        odds_warning="missing_api_key",
    )
    expected = (
        "⚠️ **Предупреждение:** не задан ключ Odds API (`missing_api_key`).\n"
        "Live-котировки Pinnacle и расчёт edge в этом прогоне могут отсутствовать.\n"
        "Всего матчей: 0\n"
        "\n"
        "**Модель (provenance):**\n"
        "—\n"
        "\n"
        "**Топ по |edge|** (до 8):\n"
        "— (нет строк с рассчитанным edge)\n"
        "\n"
        "**Все матчи (кратко):**"
    )
    assert got == expected


def test_build_post_refresh_digest_text_truncation_suffix_and_max_len() -> None:
    max_chars = 120
    got = build_post_refresh_digest_text(
        matches=[],
        provenance_line="Z" * 200,
        max_chars=max_chars,
    )
    assert len(got) == max_chars
    assert got.endswith(f"\n… [обрезано до {max_chars} символов]")
