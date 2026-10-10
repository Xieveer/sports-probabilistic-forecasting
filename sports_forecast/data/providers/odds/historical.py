"""Локальный журнал и provider-as-of запрос исторических Pinnacle snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sports_forecast.identity.events import CanonicalEventRef, RegistryEventResolver
from sports_forecast.identity.snapshot import RegistrySnapshotReader


_MAX_FILE_BYTES = 32 * 1024 * 1024
_DATABASE_SCHEMA_VERSION = "1"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS historical_observations (
    observation_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_sport_key TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    source_home TEXT NOT NULL,
    source_away TEXT NOT NULL,
    commence_time TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    source_market TEXT NOT NULL,
    market_key TEXT NOT NULL,
    period TEXT NOT NULL,
    includes_overtime INTEGER NOT NULL,
    includes_shootout INTEGER NOT NULL,
    market_rules_version TEXT NOT NULL,
    observed_at TEXT,
    observed_at_path TEXT,
    provider_updated_at TEXT,
    provider_updated_at_path TEXT,
    prices_json TEXT NOT NULL,
    origin TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS historical_observations_source_key
ON historical_observations(source, source_sport_key, source_event_id);
CREATE TABLE IF NOT EXISTS historical_cache_files (
    file_sha256 TEXT PRIMARY KEY,
    locator TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS historical_receipts (
    receipt_id TEXT PRIMARY KEY,
    file_sha256 TEXT NOT NULL REFERENCES historical_cache_files(file_sha256),
    imported_at TEXT NOT NULL,
    retrieved_at TEXT
);
CREATE TABLE IF NOT EXISTS historical_observation_receipts (
    observation_id TEXT NOT NULL REFERENCES historical_observations(observation_id),
    receipt_id TEXT NOT NULL REFERENCES historical_receipts(receipt_id),
    PRIMARY KEY(observation_id, receipt_id)
);
CREATE TABLE IF NOT EXISTS historical_source_events (
    file_sha256 TEXT NOT NULL REFERENCES historical_cache_files(file_sha256),
    source_event_id TEXT NOT NULL,
    commence_time TEXT,
    source_home TEXT,
    source_away TEXT,
    bookmaker_keys_json TEXT NOT NULL,
    market_keys_json TEXT NOT NULL,
    target_market_status TEXT NOT NULL,
    diagnostic_code TEXT,
    PRIMARY KEY(file_sha256, source_event_id)
);
CREATE TABLE IF NOT EXISTS historical_diagnostics (
    file_sha256 TEXT NOT NULL REFERENCES historical_cache_files(file_sha256),
    diagnostic_code TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY(file_sha256, diagnostic_code)
);
"""


@dataclass(frozen=True)
class ImportSummary:
    """Числа одной пакетной операции импорта."""

    files_seen: int
    observations_seen: int
    observations_inserted: int
    diagnostics: int


@dataclass(frozen=True)
class HistoricalSelection:
    """Один полный выбранный Pinnacle h2h snapshot по provider time."""

    observation_id: str
    project_event_id: str
    registry_snapshot_id: str
    source: str
    source_event_id: str
    source_file_sha256: str
    receipt_id: str
    bookmaker: str
    market_key: str
    period: str
    includes_overtime: bool
    includes_shootout: bool
    market_rules_version: str
    prices: dict[str, str]
    observed_at: datetime
    age_seconds: float
    retrieved_at: datetime | None
    imported_at: datetime
    retrieval_status: str
    late_retrieval: bool | None
    selection_mode: str = "provider_as_of"
    locally_known_at_t: bool = False


@dataclass(frozen=True)
class ImportedSourceEvent:
    """Минимальный факт об NHL event из файла, включая отсутствие линии."""

    file_sha256: str
    source_event_id: str
    commence_time: datetime | None
    source_home: str | None
    source_away: str | None
    bookmaker_keys: tuple[str, ...]
    market_keys: tuple[str, ...]
    target_market_status: str
    diagnostic_code: str | None


class HistoricalOddsConflictError(ValueError):
    """Несколько payload претендуют на одну provider event/market/time точку."""


def _utc(value: str | datetime, *, field: str) -> datetime:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} должен содержать timezone")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _price(value: object) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Некорректная цена") from exc
    if not number.is_finite() or number <= 1:
        raise ValueError("Decimal price должен быть конечным и больше 1")
    return format(number.normalize(), "f")


def _market(event: dict[str, object]) -> tuple[str, str, dict[str, str]] | None:
    if event.get("sport_key") != "icehockey_nhl":
        return None
    raw_bookmakers = event.get("bookmakers", [])
    if not isinstance(raw_bookmakers, list) or any(
        not isinstance(item, dict) for item in raw_bookmakers
    ):
        raise ValueError("invalid_bookmakers")
    bookmakers = [item for item in raw_bookmakers if item.get("key") == "pinnacle"]
    if not bookmakers:
        return None
    if len(bookmakers) != 1:
        raise ValueError("duplicate_pinnacle_bookmaker")
    raw_markets = bookmakers[0].get("markets", [])
    if not isinstance(raw_markets, list) or any(not isinstance(item, dict) for item in raw_markets):
        raise ValueError("invalid_markets")
    markets = [item for item in raw_markets if item.get("key") == "h2h"]
    if not markets:
        return None
    if len(markets) != 1:
        raise ValueError("duplicate_h2h_market")
    market = markets[0]
    outcomes = market.get("outcomes", [])
    home, away = str(event.get("home_team", "")), str(event.get("away_team", ""))
    if not isinstance(outcomes, list) or any(not isinstance(item, dict) for item in outcomes):
        raise ValueError("invalid_h2h_outcomes")
    if not home or not away or home == away:
        raise ValueError("invalid_h2h_participants")
    if len(outcomes) != 2 or {item.get("name") for item in outcomes} != {home, away}:
        raise ValueError("invalid_h2h_outcomes")
    prices = {"home_win": "", "away_win": ""}
    for outcome in outcomes:
        key = "home_win" if outcome["name"] == home else "away_win"
        prices[key] = _price(outcome.get("price"))
    return "h2h", "winner_withOT", prices


def _target_market_status(event: dict[str, object]) -> tuple[str, str | None]:
    """Классифицировать наличие именно Pinnacle h2h без ценового fallback."""
    bookmakers = event.get("bookmakers", [])
    if not isinstance(bookmakers, list):
        return "invalid_target_market", "invalid_bookmakers"
    pinnacle = [
        item for item in bookmakers if isinstance(item, dict) and item.get("key") == "pinnacle"
    ]
    if not pinnacle:
        return "no_pinnacle", None
    if len(pinnacle) > 1:
        return "invalid_target_market", "duplicate_pinnacle_bookmaker"
    markets = pinnacle[0].get("markets", [])
    if not isinstance(markets, list):
        return "invalid_target_market", "invalid_markets"
    h2h = [item for item in markets if isinstance(item, dict) and item.get("key") == "h2h"]
    if not h2h:
        return "no_h2h", None
    if len(h2h) > 1:
        return "invalid_target_market", "duplicate_h2h_market"
    try:
        if _market(event) is None:
            return "no_h2h", None
    except (KeyError, TypeError, ValueError) as exc:
        code = str(exc)
        if not code.startswith(("duplicate_", "invalid_")):
            code = "invalid_target_market"
        return "invalid_target_market", code
    return "target_market", None


def _connect(database_path: Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(_SCHEMA)
    connection.execute(
        "INSERT OR IGNORE INTO historical_meta VALUES ('schema_version', ?)",
        (_DATABASE_SCHEMA_VERSION,),
    )
    schema_version = connection.execute(
        "SELECT value FROM historical_meta WHERE key='schema_version'"
    ).fetchone()[0]
    if schema_version != _DATABASE_SCHEMA_VERSION:
        connection.close()
        raise ValueError(f"Неподдерживаемая версия historical odds schema: {schema_version}")
    connection.commit()
    return connection


def import_historical_cache(
    files: tuple[Path, ...] | list[Path],
    database_path: Path,
    *,
    retrieved_at: datetime | None = None,
) -> ImportSummary:
    """Импортировать cache JSON атомарно по одному файлу без сетевого обращения.

    ``retrieved_at`` следует задавать только при наличии отдельного доказательства
    времени получения файлов; значение применяется ко всему вызову, поэтому batch
    с разными временами получения нужно разделить. Отсутствие не восстанавливается
    из mtime.
    """
    known_retrieval = _iso(_utc(retrieved_at, field="retrieved_at")) if retrieved_at else None
    observations_seen = observations_inserted = diagnostics_count = 0
    imported_at = _iso(datetime.now(UTC))
    connection = _connect(Path(database_path))
    try:
        for source_path in files:
            path = Path(source_path)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
                raise ValueError("Источник должен быть обычным JSON-файлом допустимого размера")
            content = path.read_bytes()
            file_digest = hashlib.sha256(content).hexdigest()
            try:
                payload = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Некорректный cache JSON") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Historical cache должен содержать data array")
            raw_timestamp = payload.get("timestamp")
            observed: str | None = None
            diagnostic_codes: list[str] = []
            try:
                if raw_timestamp is None:
                    diagnostic_codes.append("missing_envelope_timestamp")
                else:
                    observed = _iso(_utc(str(raw_timestamp), field="timestamp"))
            except ValueError:
                diagnostic_codes.append("invalid_envelope_timestamp")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO historical_cache_files VALUES (?, ?)",
                (file_digest, f"sha256:{file_digest}"),
            )
            receipt_identity = json.dumps(
                {"file_sha256": file_digest, "retrieved_at": known_retrieval},
                sort_keys=True,
                separators=(",", ":"),
            )
            receipt_id = "hr1:" + hashlib.sha256(receipt_identity.encode()).hexdigest()
            connection.execute(
                "INSERT OR IGNORE INTO historical_receipts VALUES (?, ?, ?, ?)",
                (receipt_id, file_digest, imported_at, known_retrieval),
            )
            for event in payload["data"]:
                observations_seen += 1
                try:
                    if not isinstance(event, dict):
                        raise ValueError("invalid_event")
                    if event.get("sport_key") != "icehockey_nhl":
                        continue
                    source_event_id = str(event.get("id", ""))
                    if not source_event_id:
                        diagnostic_codes.append("missing_source_event_id")
                        continue
                    diagnostic_code: str | None = None
                    try:
                        commence = _iso(_utc(str(event["commence_time"]), field="commence_time"))
                    except (KeyError, TypeError, ValueError):
                        commence = None
                        diagnostic_code = "invalid_commence_time"
                    status, market_diagnostic = _target_market_status(event)
                    diagnostic_code = diagnostic_code or market_diagnostic
                    if observed is None:
                        diagnostic_code = diagnostic_code or "invalid_envelope_timestamp"
                    bookmakers = event.get("bookmakers", [])
                    bookmaker_keys = (
                        sorted(
                            str(item.get("key"))
                            for item in bookmakers
                            if isinstance(item, dict) and item.get("key")
                        )
                        if isinstance(bookmakers, list)
                        else []
                    )
                    market_keys = (
                        sorted(
                            {
                                str(market["key"])
                                for item in bookmakers
                                if isinstance(item, dict) and isinstance(item.get("markets"), list)
                                for market in item["markets"]
                                if isinstance(market, dict) and market.get("key")
                            }
                        )
                        if isinstance(bookmakers, list)
                        else []
                    )
                    connection.execute(
                        """INSERT OR IGNORE INTO historical_source_events VALUES
                           (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            file_digest,
                            source_event_id,
                            commence,
                            event.get("home_team"),
                            event.get("away_team"),
                            json.dumps(bookmaker_keys, separators=(",", ":")),
                            json.dumps(market_keys, separators=(",", ":")),
                            status,
                            diagnostic_code,
                        ),
                    )
                    if diagnostic_code:
                        diagnostic_codes.append(diagnostic_code)
                    if status != "target_market" or commence is None:
                        continue
                    parsed = _market(event)
                    if parsed is None:
                        continue
                    source_market, market_key, prices = parsed
                    if observed is None:
                        diagnostic_codes.append("invalid_envelope_timestamp")
                        continue
                    bookmaker = next(
                        item for item in event["bookmakers"] if item.get("key") == "pinnacle"
                    )
                    market = next(item for item in bookmaker["markets"] if item.get("key") == "h2h")
                    market_updated = market.get("last_update")
                    if market_updated:
                        updated = market_updated
                        updated_path = "markets[h2h].last_update"
                    elif len(bookmaker.get("markets", [])) == 1:
                        updated = bookmaker.get("last_update")
                        updated_path = "bookmakers[pinnacle].last_update" if updated else None
                    else:
                        updated = None
                        updated_path = None
                    if updated:
                        updated = _iso(_utc(str(updated), field="last_update"))
                    facts = {
                        "schema_version": 1,
                        "source": "the_odds_api",
                        "source_sport_key": "icehockey_nhl",
                        "source_event_id": source_event_id,
                        "source_home": str(event["home_team"]),
                        "source_away": str(event["away_team"]),
                        "commence_time": commence,
                        "bookmaker": "pinnacle",
                        "source_market": source_market,
                        "market_key": market_key,
                        "period": "full_game",
                        "includes_overtime": True,
                        "includes_shootout": True,
                        "market_rules_version": "nhl-pinnacle-h2h-v1",
                        "observed_at": observed,
                        "observed_at_path": "timestamp",
                        "provider_updated_at": updated,
                        "provider_updated_at_path": updated_path,
                        "prices": prices,
                        "origin": "provider_history",
                    }
                    normalized = json.dumps(facts, sort_keys=True, separators=(",", ":"))
                    observation_id = "ho1:" + hashlib.sha256(normalized.encode()).hexdigest()
                    cursor = connection.execute(
                        """INSERT OR IGNORE INTO historical_observations VALUES
                        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            observation_id,
                            facts["schema_version"],
                            facts["source"],
                            facts["source_sport_key"],
                            facts["source_event_id"],
                            facts["source_home"],
                            facts["source_away"],
                            facts["commence_time"],
                            facts["bookmaker"],
                            facts["source_market"],
                            facts["market_key"],
                            facts["period"],
                            int(facts["includes_overtime"]),
                            int(facts["includes_shootout"]),
                            facts["market_rules_version"],
                            observed,
                            facts["observed_at_path"],
                            updated,
                            updated_path,
                            json.dumps(prices, sort_keys=True, separators=(",", ":")),
                            facts["origin"],
                        ),
                    )
                    observations_inserted += cursor.rowcount
                    connection.execute(
                        "INSERT OR IGNORE INTO historical_observation_receipts VALUES (?, ?)",
                        (observation_id, receipt_id),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    diagnostic_codes.append(
                        str(exc)
                        if str(exc).startswith(("duplicate_", "invalid_"))
                        else "invalid_event"
                    )
            counts: dict[str, int] = {}
            for code in diagnostic_codes:
                counts[code] = counts.get(code, 0) + 1
            for code, count in counts.items():
                connection.execute(
                    "INSERT INTO historical_diagnostics VALUES (?, ?, ?) "
                    "ON CONFLICT(file_sha256, diagnostic_code) DO UPDATE SET count=excluded.count",
                    (file_digest, code, count),
                )
            diagnostics_count += sum(counts.values())
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return ImportSummary(len(files), observations_seen, observations_inserted, diagnostics_count)


def list_imported_source_events(database_path: Path) -> tuple[ImportedSourceEvent, ...]:
    """Прочитать компактные NHL event facts, включая явно отсутствующий target market."""
    connection = _connect(Path(database_path))
    try:
        rows = connection.execute(
            "SELECT * FROM historical_source_events ORDER BY commence_time, source_event_id, file_sha256"
        ).fetchall()
        return tuple(
            ImportedSourceEvent(
                file_sha256=row["file_sha256"],
                source_event_id=row["source_event_id"],
                commence_time=(
                    _utc(row["commence_time"], field="commence_time")
                    if row["commence_time"]
                    else None
                ),
                source_home=row["source_home"],
                source_away=row["source_away"],
                bookmaker_keys=tuple(json.loads(row["bookmaker_keys_json"])),
                market_keys=tuple(json.loads(row["market_keys_json"])),
                target_market_status=row["target_market_status"],
                diagnostic_code=row["diagnostic_code"],
            )
            for row in rows
        )
    finally:
        connection.close()


def query_provider_as_of(
    database_path: Path,
    registry_reader: RegistrySnapshotReader,
    *,
    project_event_id: str,
    at: datetime,
) -> HistoricalSelection | None:
    """Выбрать последний подтверждённый Pinnacle h2h snapshot не позже T."""
    instant = _utc(at, field="T")
    connection = _connect(Path(database_path))
    try:
        rows = connection.execute(
            "SELECT * FROM historical_observations WHERE observed_at IS NOT NULL ORDER BY observed_at, source_event_id"
        ).fetchall()
        refs = tuple(
            CanonicalEventRef(
                canonical_event_id=index,
                sport="ice_hockey",
                tournament="icehockey_nhl",
                source=row["source"],
                source_event_id=row["source_event_id"],
                scheduled_at=_utc(row["commence_time"], field="commence_time"),
                home_participant=row["source_home"],
                away_participant=row["source_away"],
            )
            for index, row in enumerate(rows)
        )
        resolutions = RegistryEventResolver(registry_reader.snapshot.event_snapshot).resolve_many(
            refs
        )
        eligible = []
        for row, resolution in zip(rows, resolutions, strict=True):
            if (
                resolution.status != "resolved"
                or resolution.project_event_id != project_event_id
                or _utc(row["observed_at"], field="observed_at") > instant
            ):
                continue
            tournament = registry_reader.resolve_designation(
                source=row["source"],
                kind="tournament",
                scope={"sport": "ice_hockey"},
                value_kind="external_id",
                raw_value=row["source_sport_key"],
                at=row["commence_time"],
            )
            if tournament.status != "resolved" or tournament.entity_id is None:
                continue
            event = registry_reader.resolve_designation(
                source=row["source"],
                kind="event",
                scope={"sport": "ice_hockey", "tournament": tournament.entity_id},
                value_kind="external_id",
                raw_value=row["source_event_id"],
                at=row["commence_time"],
            )
            if event.status == "resolved" and event.entity_id == resolution.project_event_id:
                eligible.append(row)
        if not eligible:
            return None
        latest_at = max(row["observed_at"] for row in eligible)
        latest = [row for row in eligible if row["observed_at"] == latest_at]
        if len({row["observation_id"] for row in latest}) > 1:
            raise HistoricalOddsConflictError("Конфликт фактов одной provider timestamp")
        row = latest[0]
        receipt = connection.execute(
            """SELECT r.receipt_id, r.file_sha256, r.imported_at, r.retrieved_at FROM historical_receipts r
               JOIN historical_observation_receipts x USING(receipt_id)
               WHERE x.observation_id=? ORDER BY r.retrieved_at IS NULL, r.retrieved_at, r.imported_at LIMIT 1""",
            (row["observation_id"],),
        ).fetchone()
        retrieved = (
            _utc(receipt["retrieved_at"], field="retrieved_at")
            if receipt and receipt["retrieved_at"]
            else None
        )
        return HistoricalSelection(
            observation_id=row["observation_id"],
            project_event_id=project_event_id,
            registry_snapshot_id=registry_reader.snapshot_id,
            source=row["source"],
            source_event_id=row["source_event_id"],
            source_file_sha256=receipt["file_sha256"],
            receipt_id=receipt["receipt_id"],
            bookmaker=row["bookmaker"],
            market_key=row["market_key"],
            period=row["period"],
            includes_overtime=bool(row["includes_overtime"]),
            includes_shootout=bool(row["includes_shootout"]),
            market_rules_version=row["market_rules_version"],
            prices=json.loads(row["prices_json"]),
            observed_at=_utc(row["observed_at"], field="observed_at"),
            age_seconds=(instant - _utc(row["observed_at"], field="observed_at")).total_seconds(),
            retrieved_at=retrieved,
            imported_at=_utc(receipt["imported_at"], field="imported_at"),
            retrieval_status="known" if retrieved else "unknown",
            late_retrieval=(retrieved > instant) if retrieved else None,
        )
    finally:
        connection.close()
