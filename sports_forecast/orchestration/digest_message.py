"""Контракт текста post-refresh Telegram digest (одно сообщение, без HTTP/Telegram).

Контракт сообщения (порядок блоков, сверху вниз):

1. **Предупреждение пайплайна** — только если ``odds_warning`` не ``\"none\"``:
   ``missing_api_key`` или ``fetch_failed``; 2–4 строки на русском, без секретов.
2. **Заголовок** — если передан непустой ``header``, одна строка (как есть).
3. **Сводка по матчам** — строка вида «Всего матчей: N»; N = ``len(matches)``
   (включая строки без ``edge_home``).
4. **Модель (provenance)** — блок из одной строки ``provenance_line`` (задаёт
   вызывающий код; типично run_name / run_id / algorithm из ``deploy.yaml``).
5. **Топ по |edge|** — до ``top_n_edges`` строк; участвуют **только** матчи, у
   которых ``edge_home is not None``; сортировка по убыванию ``abs(edge_home)``;
   при равном |edge| сохраняется относительный порядок как в отфильтрованном
   списке (тот же порядок, что среди матчей с edge в исходном ``matches``).
   Матчи без edge в этот список **не** попадают, но учитываются в N.
6. **Все матчи (кратко)** — все матчи в **исходном** порядке ``matches``;
   для каждой строки: дата/время, команды, короткий хвост (``live=`` / ``edge=`` /
   ``bet=``) в том же стиле, что ``scripts/run_nhl_refresh_notify.py`` (сначала
   ``live``, затем ``edge``, затем ``bet``). Если матчей больше **5**, показываются
   только **первые 5** строк этого блока и отдельная строка «… ещё K матч(ей)»
   (K = всего − 5), чтобы уложиться в лимит Telegram.

**Обрезка:** если длина текста превышает ``max_chars``, тело обрезается и в конец
добавляется одна строка ``… [обрезано до N символов]``, где N = ``max_chars``;
итоговая длина не превышает ``max_chars``.

Модуль **только** собирает строку; отправка и сетевые вызовы вне ответственности.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal


__all__ = [
    "DigestMatchLine",
    "build_post_refresh_digest_text",
    "format_provenance_from_deploy_dict",
]

OddsWarning = Literal["none", "missing_api_key", "fetch_failed"]


@dataclass(frozen=True, slots=True)
class DigestMatchLine:
    """Одна строка сводки по матчу для digest (без сырья API/BД)."""

    home_player: str
    away_player: str
    match_datetime: str
    edge_home: float | None
    bet_decision_home: str | None
    live_odds_status: str | None


def format_provenance_from_deploy_dict(model: dict[str, Any]) -> str:
    """Собрать одну строку provenance из словаря ``model`` (например из YAML).

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


def _match_tail(
    edge_home: float | None,
    bet_decision_home: str | None,
    live_odds_status: str | None,
) -> str:
    tail = ""
    st = (live_odds_status or "").strip()
    if st:
        tail += f" live={st}"
    if edge_home is not None:
        tail += f" edge={float(edge_home):+.3f}"
    if bet_decision_home:
        tail += f" bet={bet_decision_home}"
    return tail


def _lines_for_odds_warning(warning: OddsWarning) -> list[str]:
    if warning == "missing_api_key":
        return [
            "⚠️ **Предупреждение:** не задан ключ Odds API (`missing_api_key`).",
            "Live-котировки Pinnacle и расчёт edge в этом прогоне могут отсутствовать.",
        ]
    if warning == "fetch_failed":
        return [
            "⚠️ **Предупреждение:** не удалось получить котировки (`fetch_failed`).",
            "Сводка ниже может быть без актуальных коэффициентов и edge.",
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


def build_post_refresh_digest_text(
    *,
    matches: Sequence[DigestMatchLine],
    provenance_line: str,
    odds_warning: OddsWarning = "none",
    top_n_edges: int = 8,
    max_chars: int = 4096,
    header: str | None = None,
) -> str:
    """Собрать одно русскоязычное сообщение для Telegram (лимит ``max_chars``).

    Args:
        matches: Список матчей в порядке «краткого» перечисления.
        provenance_line: Одна строка про модель/прогон (caller-defined).
        odds_warning: Уровень предупреждения по котировкам на уровне пайплайна.
        top_n_edges: Сколько строк максимум в блоке топа по |edge|.
        max_chars: Жёсткий потолок длины (типично 4096 для Telegram).
        header: Опциональная первая строка контента после предупреждений.

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
    chunks.append("**Модель (provenance):**")
    chunks.append(provenance_line.strip() if provenance_line else "—")
    chunks.append("")

    rankable = [m for m in matches if m.edge_home is not None]
    ranked = sorted(rankable, key=lambda m: abs(m.edge_home or 0.0), reverse=True)[
        : max(0, top_n_edges)
    ]
    chunks.append(f"**Топ по |edge|** (до {top_n_edges}):")
    if ranked:
        for m in ranked:
            tail = _match_tail(m.edge_home, m.bet_decision_home, m.live_odds_status)
            chunks.append(f"• {m.home_player} — {m.away_player} @ {m.match_datetime}{tail}")
    else:
        chunks.append("— (нет строк с рассчитанным edge)")
    chunks.append("")

    chunks.append("**Все матчи (кратко):**")
    brief_limit = 5
    brief_matches = list(matches[:brief_limit])
    for m in brief_matches:
        tail = _match_tail(m.edge_home, m.bet_decision_home, m.live_odds_status)
        chunks.append(f"• {m.home_player} — {m.away_player} @ {m.match_datetime}{tail}")
    if n_total > brief_limit:
        chunks.append(f"… ещё {n_total - brief_limit} матч(ей)")

    body = "\n".join(chunks).rstrip()
    return _truncate(body, max_chars)
