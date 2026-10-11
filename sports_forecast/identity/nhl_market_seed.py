"""Идемпотентный seed NHL/Pinnacle winner market."""

from __future__ import annotations

from datetime import UTC, datetime

from sports_forecast.identity.registry import EntityRegistry, _normalize


NHL_PINNACLE_MARKET_SEED = "trusted:nhl-pinnacle-h2h:v1"


def seed_nhl_pinnacle_market(registry: EntityRegistry, *, tournament_id: str) -> str:
    """Создать справочные ID и правила NHL/Pinnacle h2h без перезаписи owner changes."""
    if not tournament_id:
        raise ValueError("Подтверждённый tournament ID обязателен")
    scope = {
        "sport": "ice_hockey",
        "tournament": tournament_id,
        "bookmaker": "pinnacle",
    }
    with registry._connect() as connection:
        tournament = connection.execute(
            "SELECT kind,sport,state FROM entities WHERE id=?", (tournament_id,)
        ).fetchone()
        if (
            tournament is None
            or tournament["kind"] != "tournament"
            or tournament["sport"] != "ice_hockey"
            or tournament["state"] != "active"
        ):
            raise ValueError("tournament ID должен быть активной сущностью NHL")
        market = registry._seed_entity_in_transaction(
            connection,
            "market",
            "winner_withOT",
            "ice_hockey",
            NHL_PINNACLE_MARKET_SEED,
            stable_key="market:winner_withOT",
        )
        market_id = market.id
        outcomes = tuple(
            registry._seed_entity_in_transaction(
                connection,
                "outcome",
                label,
                "ice_hockey",
                NHL_PINNACLE_MARKET_SEED,
                stable_key=f"outcome:{key}",
            )
            for key, label in (("home_win", "Победа хозяев"), ("away_win", "Победа гостей"))
        )
        existing_rows = connection.execute(
            "SELECT id FROM designations WHERE source='the_odds_api' AND kind='market' AND scope_json=? AND value_kind='name' AND normalized_value=? ORDER BY id",
            (registry._scope_json(scope), _normalize("h2h", "name")),
        ).fetchall()
        if not existing_rows:
            registry._insert_designation(
                connection,
                entity_id=market.id,
                source="the_odds_api",
                kind="market",
                scope=scope,
                value_kind="name",
                raw_value="h2h",
                state="confirmed",
                valid_from=None,
                valid_until=None,
                seed_key=NHL_PINNACLE_MARKET_SEED,
            )
        else:
            resolution = registry.resolve(
                "the_odds_api",
                "market",
                scope,
                "name",
                "h2h",
                at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            if resolution.status != "resolved" or resolution.entity_id is None:
                raise ValueError(f"h2h alias unresolved or conflicting: {resolution.status}")
            if resolution.entity_id != market.id:
                raise ValueError("owner mapping points h2h to another market; seed skipped")
            market_id = resolution.entity_id
        rule = connection.execute(
            "SELECT 1 FROM market_rules WHERE market_id=?", (market_id,)
        ).fetchone()
    if rule is None:
        registry.set_market_rule(
            market_id,
            period="game",
            overtime=True,
            shootout=True,
            draw=False,
            valid_outcome_ids=tuple(item.id for item in outcomes),
            valid_outcome_keys={
                outcomes[0].id: "home_win",
                outcomes[1].id: "away_win",
            },
            actor="trusted-seed",
            reason="Подтверждённый NHL/Pinnacle h2h: победитель с учётом ОТ и буллитов",
            expected_revision=0,
        )
    return market_id
