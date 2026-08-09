"""Контракт текста post-refresh Telegram digest (одно сообщение, без HTTP/Telegram).

Формат: plain text (без Markdown-звёздочек — в ``sendMessage`` без ``parse_mode`` они
не дают жирный шрифт). Блоки: предупреждение по Odds API (при необходимости),
заголовок, число матчей, модель + критерий bet (порог edge из ``service_api``),
расписание по времени (MSK), для каждого матча prob / kf / edge по сторонам и
две строки итога по ставке (дом и гость, симметрично :func:`decide_bet`).

Модуль **только** собирает строку; отправка и сетевые вызовы вне ответственности.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sports_forecast.betting.edge_decision import compute_edge


__all__ = [
    "DigestMatchLine",
    "OddsWarning",
    "build_post_refresh_digest_text",
    "format_provenance_from_deploy_dict",
]

OddsWarning = Literal["none", "missing_api_key", "fetch_failed"]

_MSK = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True, slots=True)
class DigestMatchLine:
    """Одна строка сводки по матчу для digest."""

    home_player: str
    away_player: str
    commence_utc: datetime | None
    proba_home: float | None = None
    pinnacle_home_decimal: float | None = None
    pinnacle_away_decimal: float | None = None
    edge_home: float | None = None
    edge_away: float | None = None
    bet_decision_home: str | None = None
    bet_decision_away: str | None = None


def format_provenance_from_deploy_dict(model: dict[str, Any]) -> str:
    """Собрать одну строку provenance из словаря ``model`` (например из YAML.

    Берутся непустые значения ключей ``run_name``, ``run_id``, ``algorithm``
    в этом порядке, склеенные через ``; ``.

    Args:
        model: Обычно поддерево ``model`` из deploy-манифеста.

    Returns:
        Строка для блока provenance или пустая строка, если нечего вывести.
    """
    parts: list[str] = []
    for key in ("run_name", "run_id", "algorithm"):
        raw = model.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            parts.append(s)
    return "; ".join(parts)


def _to_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _format_msk_line(dt_utc: datetime | None) -> str:
    if dt_utc is None:
        return "время: ?"
    aware = _to_utc_aware(dt_utc)
    if aware is None:
        return "время: ?"
    return aware.astimezone(_MSK).strftime("%Y-%m-%d %H:%M MSK")


def _fmt_pair(
    left: float | None,
    right: float | None,
    *,
    fmt: str,
    na: str = "—",
) -> str:
    def one(v: float | None) -> str:
        if v is None or not isfinite(v):
            return na
        return format(v, fmt)

    return f"{one(left)}/{one(right)}"


def _edges_from_probs(
    ph: float | None,
    kh: float | None,
    ka: float | None,
) -> tuple[float | None, float | None]:
    """Edge дома и гостя: ``p − 1/k`` для каждой стороны при валидных входах."""
    if ph is None or not isfinite(ph):
        return None, None
    pa = 1.0 - float(ph)
    eh: float | None = None
    ea: float | None = None
    if kh is not None:
        try:
            eh = float(compute_edge(float(ph), float(kh)))
        except ValueError:
            eh = None
    if ka is not None:
        try:
            ea = float(compute_edge(float(pa), float(ka)))
        except ValueError:
            ea = None
    return eh, ea


def _side_bet_outcome_line(
    *,
    side_label: str,
    player: str,
    proba_side: float | None,
    k_side: float | None,
    bet: str | None,
    edge_threshold: float,
) -> str:
    """Одна строка итога по moneyline одной стороны (согласовано с ``decide_bet``)."""
    if bet == "bet" and proba_side is not None and k_side is not None:
        try:
            ev_pct = (float(proba_side) * float(k_side) - 1.0) * 100.0
        except (TypeError, ValueError):
            return f"  Итог {side_label}: (ошибка расчёта EV)"
        return f"  Итог {side_label} ({player}): ставка @ {float(k_side):.2f}, EV={ev_pct:+.1f}%"
    if bet == "no_bet":
        return f"  Итог {side_label} ({player}): без ставки (edge < {edge_threshold:g})"
    if bet == "insufficient_data" or bet is None:
        return f"  Итог {side_label} ({player}): нет линии или данных для bet"
    return f"  Итог {side_label} ({player}): {bet}"


def _lines_for_odds_warning(warning: OddsWarning) -> list[str]:
    if warning == "missing_api_key":
        return [
            "⚠️ Предупреждение: не задан ключ Odds API (missing_api_key).",
            "Котировки и edge в этом прогоне могут отсутствовать.",
        ]
    if warning == "fetch_failed":
        return [
            "⚠️ Предупреждение: не удалось получить котировки (fetch_failed).",
            "Ниже — без актуальных kf и edge.",
        ]
    return []


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    suffix = f"\n… [обрезано до {max_chars} символов]"
    keep = max_chars - len(suffix)
    if keep < 1:
        return suffix[-max_chars:] if max_chars > 0 else ""
    return text[:keep] + suffix


def _sort_key_commence(m: DigestMatchLine) -> datetime:
    u = _to_utc_aware(m.commence_utc)
    if u is None:
        return datetime.max.replace(tzinfo=UTC)
    return u


def _format_match_block(m: DigestMatchLine, *, edge_threshold: float) -> list[str]:
    ph, pa = m.proba_home, None
    if ph is not None and isfinite(ph):
        pa = 1.0 - float(ph)

    kh, ka = m.pinnacle_home_decimal, m.pinnacle_away_decimal
    eh, ea = m.edge_home, m.edge_away
    if eh is None and ea is None and (kh is not None or ka is not None):
        eh, ea = _edges_from_probs(ph, kh, ka)

    prob_s = _fmt_pair(ph, pa, fmt=".3f")
    kf_s = _fmt_pair(kh, ka, fmt=".2f")
    edge_s = _fmt_pair(eh, ea, fmt="+.3f")

    return [
        f"• {m.home_player} — {m.away_player}",
        f"  {_format_msk_line(m.commence_utc)}",
        f"  prob={prob_s}  kf={kf_s}  edge={edge_s}",
        _side_bet_outcome_line(
            side_label="дом",
            player=m.home_player,
            proba_side=ph,
            k_side=kh,
            bet=m.bet_decision_home,
            edge_threshold=edge_threshold,
        ),
        _side_bet_outcome_line(
            side_label="гость",
            player=m.away_player,
            proba_side=pa,
            k_side=ka,
            bet=m.bet_decision_away,
            edge_threshold=edge_threshold,
        ),
    ]


def build_post_refresh_digest_text(
    *,
    matches: Sequence[DigestMatchLine],
    provenance_line: str,
    odds_warning: OddsWarning = "none",
    edge_threshold: float | None = None,
    max_chars: int = 4096,
    header: str | None = None,
) -> str:
    """Собрать одно русскоязычное сообщение для Telegram (лимит ``max_chars``).

    Args:
        matches: Матчи (порядок будет заменён на сортировку по ``commence_utc``).
        provenance_line: Строка про модель/прогон.
        odds_warning: Предупреждение по Odds API.
        edge_threshold: Порог edge для bet (дом); если ``None``, строка критерия не выводится.
        max_chars: Жёсткий потолок длины.
        header: Опциональная первая строка после предупреждений.

    Returns:
        Готовый текст одного сообщения.
    """
    chunks: list[str] = []

    chunks.extend(_lines_for_odds_warning(odds_warning))

    if header and str(header).strip():
        chunks.append(str(header).strip())
        chunks.append("")

    n_total = len(matches)
    chunks.append(f"Всего матчей: {n_total}")
    chunks.append("")
    chunks.append("Модель (provenance):")
    chunks.append(provenance_line.strip() if provenance_line else "—")
    if edge_threshold is not None and isfinite(edge_threshold):
        chunks.append(
            f"Критерий bet (каждая сторона): edge = p_model − 1/k ≥ {edge_threshold:g} "
            f"(conf/service_api.yaml, env SERVICE_API_EDGE_THRESHOLD)"
        )
    chunks.append("")

    thr = float(edge_threshold) if edge_threshold is not None and isfinite(edge_threshold) else 0.03

    chunks.append("Расписание:")
    sorted_matches = sorted(matches, key=_sort_key_commence)
    brief_limit = 15
    shown = sorted_matches[:brief_limit]
    for m in shown:
        chunks.extend(_format_match_block(m, edge_threshold=thr))
        chunks.append("")
    if n_total > brief_limit:
        chunks.append(f"… ещё {n_total - brief_limit} матч(ей)")

    body = "\n".join(chunks).rstrip()
    return _truncate(body, max_chars)
