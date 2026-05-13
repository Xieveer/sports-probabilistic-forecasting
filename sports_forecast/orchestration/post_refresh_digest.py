"""CLI: сводка после refresh — чтение витрины, live Pinnacle, одно Telegram-сообщение.

Пример::

    uv run python -m sports_forecast.orchestration.post_refresh_digest --dry-run

Переменные окружения:

* ``SF_TELEGRAM_DIGEST_ENABLE`` — значения ``0``, ``false``, ``no``, ``off``
  (регистр не важен) отключают **отправку** и любую работу с БД, если **не** передан
  ``--dry-run`` (в лог пишется INFO, код выхода ``0``). С ``--dry-run`` отключение **не**
  применяется: выполняется чтение БД и печать текста в stdout — удобно проверять
  витрину без Telegram.
* ``ODDS_API_KEY`` — при включённом ``--live-pinnacle`` и пустом ключе в текст
  добавляется предупреждение ``missing_api_key`` (как в HTTP-слое).
* ``BOT_TOKEN``, ``BOT_ALLOWED_USER_IDS`` — для реальной отправки (берётся первый
  id из списка через запятую).

**Airflow и повторные запуски:** в DAG ``nhl_morning_refresh`` в ``default_args`` задано
``retries=2``. Если задача digest упала **после** успешной отправки в Telegram, повторный
запуск пришлёт **второе** сообщение, пока не включена защита ниже. Опционально:

* ``SF_TELEGRAM_DIGEST_DEDUP`` — при истинных значениях ``1``, ``true``, ``yes`` (регистр
  не важен) **и** одновременно заданных ``AIRFLOW_CTX_DAG_RUN_ID`` и
  ``AIRFLOW_CTX_TASK_ID`` (как у Airflow в task-процессе): перед ``sendMessage`` проверяется
  маркер ``<project_root>/.cache/digest_telegram_sent/<dag_run_id>_<task_id>.lock``; если файл
  есть — в лог пишется пропуск дубликата, код ``0``. После успешной отправки создаётся
  каталог и записывается маркер (одна строка UTC ISO). Значения токенов и ключей в лог **не**
  попадают.

Коды выхода: ``0`` — успех; при отключённом digest без ``--dry-run`` — тоже ``0``.
``1`` — ошибка БД, недоступный или битый ``deploy.yaml`` при отправке, нет секретов
при отправке, сбой HTTP Telegram.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from sports_forecast.betting.live_moneyline_extras import proba_home_from_prediction
from sports_forecast.orchestration.digest_message import (
    DigestMatchLine,
    OddsWarning,
    build_post_refresh_digest_text,
    format_provenance_from_deploy_dict,
)
from sports_forecast.orchestration.telegram_http import telegram_send_message
from sports_forecast.service.db.engine import get_engine, get_session, init_db
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import PredictionRepository
from sports_forecast.service.live_odds_enrichment import batch_live_response_extras
from sports_forecast.service.service_api_settings import load_edge_decision_params
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_MAX_LIVE_ODDS_STATUS_KEYS_IN_LOG = 16


def _digest_sending_suppressed() -> bool:
    raw = os.environ.get("SF_TELEGRAM_DIGEST_ENABLE")
    if raw is None:
        return False
    return raw.strip().lower() in ("0", "false", "no", "off")


def _digest_dedup_env_truthy() -> bool:
    raw = os.environ.get("SF_TELEGRAM_DIGEST_DEDUP")
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes")


def _digest_telegram_marker_path(project_root: Path) -> Path | None:
    """Путь к маркеру «digest уже отправлен» для пары Airflow run/task, или ``None``."""
    if not _digest_dedup_env_truthy():
        return None
    dag_run_id = (os.environ.get("AIRFLOW_CTX_DAG_RUN_ID") or "").strip()
    task_id = (os.environ.get("AIRFLOW_CTX_TASK_ID") or "").strip()
    if not dag_run_id or not task_id:
        return None
    name = f"{dag_run_id}_{task_id}.lock"
    return project_root / ".cache" / "digest_telegram_sent" / name


def _summarize_live_odds_status_counts(
    extras_map: dict[int, dict[str, Any]],
    *,
    max_distinct_keys: int = _MAX_LIVE_ODDS_STATUS_KEYS_IN_LOG,
) -> str:
    """Компактная сводка числа предиктов по строке ``live_odds_status`` (для INFO-логов)."""
    counts: Counter[str] = Counter()
    for payload in extras_map.values():
        st = payload.get("live_odds_status")
        label = "(none)" if st is None else str(st)
        counts[label] += 1
    if not counts:
        return "empty"
    items = counts.most_common()
    if len(items) <= max_distinct_keys:
        return ",".join(f"{k}={v}" for k, v in items)
    shown = items[:max_distinct_keys]
    tail = sum(v for _, v in items[max_distinct_keys:])
    omitted = len(items) - max_distinct_keys
    head = ",".join(f"{k}={v}" for k, v in shown)
    return f"{head},...(+{omitted}_more_distinct_keys,sum_remaining={tail})"


def _deploy_yaml_path(project_root: Path, tournament: str, market_spec: str) -> Path:
    return project_root / "models" / tournament / market_spec / "best" / "deploy.yaml"


def _load_provenance_line(path: Path, *, dry_run: bool) -> tuple[str, int | None]:
    """Прочитать provenance из deploy.yaml.

    Returns:
        (строка для блока «Модель», опциональный ненулевой код выхода при ошибке).
    """
    if not path.is_file():
        msg = f"deploy.yaml не найден: {path}"
        logger.warning("%s", msg)
        if dry_run:
            print(msg, file=sys.stderr)
            return "deploy.yaml не найден", None
        return "", 1

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        msg = f"deploy.yaml: ошибка YAML ({path}): {exc}"
        logger.error("%s", msg)
        if dry_run:
            print(msg, file=sys.stderr)
            return "ошибка чтения deploy.yaml", None
        return "", 1

    model_obj = raw.get("model", {}) if isinstance(raw, dict) else {}
    if not isinstance(model_obj, dict):
        model_obj = {}
    line = format_provenance_from_deploy_dict(model_obj)
    return (line if line.strip() else "—"), None


def _predictions_to_match_lines(
    preds: list[Prediction],
    extras_map: dict[int, dict[str, Any]],
) -> list[DigestMatchLine]:
    out: list[DigestMatchLine] = []
    for p in preds:
        ex = extras_map.get(int(p.id)) or {}
        eh_raw = ex.get("edge_home")
        edge_home = float(eh_raw) if eh_raw is not None else None
        ea_raw = ex.get("edge_away")
        edge_away = float(ea_raw) if ea_raw is not None else None
        bet = ex.get("bet_decision_home")
        bet_s = str(bet) if bet else None
        bet_a = ex.get("bet_decision_away")
        bet_away_s = str(bet_a) if bet_a else None
        ph = proba_home_from_prediction(p)
        kh = ex.get("pinnacle_home_decimal")
        ka = ex.get("pinnacle_away_decimal")
        k_home = float(kh) if kh is not None else None
        k_away = float(ka) if ka is not None else None

        commence = p.match_datetime
        if commence is not None and commence.tzinfo is None:
            commence = commence.replace(tzinfo=timezone.utc)
        elif commence is not None:
            commence = commence.astimezone(timezone.utc)

        out.append(
            DigestMatchLine(
                home_player=str(p.home_player or "?"),
                away_player=str(p.away_player or "?"),
                commence_utc=commence,
                proba_home=ph,
                pinnacle_home_decimal=k_home,
                pinnacle_away_decimal=k_away,
                edge_home=edge_home,
                edge_away=edge_away,
                bet_decision_home=bet_s,
                bet_decision_away=bet_away_s,
            )
        )
    return out


def _pipeline_odds_warning(*, live_pinnacle: bool) -> OddsWarning:
    if live_pinnacle and not os.environ.get("ODDS_API_KEY", "").strip():
        return "missing_api_key"
    return "none"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Сборка и отправка одного post-refresh digest (витрина + live Pinnacle, R39.4)."
        )
    )
    p.add_argument("--tournament", default="nhl", help="Турнир (как в БД).")
    p.add_argument(
        "--market",
        default="winner_withOT",
        help="Рынок (по умолчанию как утренний NHL).",
    )
    p.add_argument(
        "--market-spec",
        default="winner_withOT",
        help="Спецификация рынка и папка под models/<tournament>/...",
    )
    p.add_argument(
        "--hours",
        type=int,
        default=48,
        help="Окно в часах вперёд от текущего UTC (как у get_upcoming_predictions).",
    )
    p.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Корень репозитория (для models/.../deploy.yaml).",
    )
    p.add_argument(
        "--live-pinnacle",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Запрашивать live Pinnacle (The Odds API) для NHL moneyline.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Печать текста в stdout, без Telegram.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.project_root).resolve()

    if _digest_sending_suppressed() and not args.dry_run:
        logger.info("SF_TELEGRAM_DIGEST_ENABLE отключает digest — пропуск (без БД и Telegram).")
        return 0

    deploy_path = _deploy_yaml_path(root, args.tournament, args.market_spec)
    provenance_line, fatal = _load_provenance_line(deploy_path, dry_run=args.dry_run)
    if fatal is not None:
        return fatal

    try:
        eng = get_engine()
        init_db(eng)
        with get_session(eng) as session:
            repo = PredictionRepository(session)
            preds = repo.get_upcoming_predictions(
                tournament=args.tournament,
                market=args.market,
                market_spec=args.market_spec,
                hours=int(args.hours),
            )
        extras_map = batch_live_response_extras(
            preds,
            live_pinnacle=bool(args.live_pinnacle),
        )
    except Exception:
        logger.exception("Ошибка при чтении БД или обогащении live odds")
        return 1

    status_summary = _summarize_live_odds_status_counts(extras_map)
    logger.info(
        "post_refresh_digest: DB and live odds enrich done "
        "tournament=%s market=%s market_spec=%s hours=%s pred_count=%s live_odds_status=%s",
        args.tournament,
        args.market,
        args.market_spec,
        int(args.hours),
        len(preds),
        status_summary,
    )

    match_lines = _predictions_to_match_lines(preds, extras_map)
    odds_w = _pipeline_odds_warning(live_pinnacle=bool(args.live_pinnacle))
    edge_params = load_edge_decision_params()

    text = build_post_refresh_digest_text(
        matches=match_lines,
        provenance_line=provenance_line,
        odds_warning=odds_w,
        edge_threshold=edge_params.edge_threshold,
    )

    if args.dry_run:
        print(text)
        return 0

    token = (os.environ.get("BOT_TOKEN") or "").strip()
    raw_ids = (os.environ.get("BOT_ALLOWED_USER_IDS") or "").strip()
    chat_id = raw_ids.split(",")[0].strip() if raw_ids else ""
    if not token or not chat_id:
        logger.error("Нет BOT_TOKEN или BOT_ALLOWED_USER_IDS — отправка невозможна")
        return 1

    marker_path = _digest_telegram_marker_path(root)
    logger.info(
        "post_refresh_digest: telegram send attempt live_pinnacle=%s odds_warning=%s text_len=%s live_odds_status=%s",
        bool(args.live_pinnacle),
        odds_w,
        len(text),
        status_summary,
    )
    if marker_path is not None and marker_path.is_file():
        logger.info(
            "post_refresh_digest: skip duplicate telegram (dedup marker present) "
            "AIRFLOW_CTX_DAG_RUN_ID=%s AIRFLOW_CTX_TASK_ID=%s",
            os.environ.get("AIRFLOW_CTX_DAG_RUN_ID"),
            os.environ.get("AIRFLOW_CTX_TASK_ID"),
        )
        return 0

    try:
        resp = telegram_send_message(token=token, chat_id=chat_id, text=text)
    except json.JSONDecodeError:
        logger.exception("Telegram: некорректный JSON в ответе")
        return 1
    except urllib.error.HTTPError:
        logger.exception("Telegram HTTP error")
        return 1
    except urllib.error.URLError:
        logger.exception("Telegram network error")
        return 1

    if not resp.get("ok"):
        logger.error("Telegram sendMessage ok=false: %s", resp)
        return 1

    if marker_path is not None:
        try:
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(
                datetime.now(timezone.utc).isoformat(timespec="seconds") + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(
                "post_refresh_digest: sent OK but dedup marker not written (%s)",
                exc,
            )

    logger.info(
        "Digest отправлен (matches=%s, chars=%s, tournament=%s, market=%s, market_spec=%s, "
        "hours=%s, pred_count=%s, live_odds_status=%s, live_pinnacle=%s, odds_warning=%s).",
        len(match_lines),
        len(text),
        args.tournament,
        args.market,
        args.market_spec,
        int(args.hours),
        len(preds),
        status_summary,
        bool(args.live_pinnacle),
        odds_w,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
