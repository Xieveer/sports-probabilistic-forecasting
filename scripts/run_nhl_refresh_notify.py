#!/usr/bin/env python3
"""Legacy dev-smoke: пауза по МСК → NHL refresh (как утренний DAG) → validate → digest.

**Канонический prod/ops путь:** DAG Airflow ``nhl_morning_refresh``, задача ``post_refresh_digest``
(после ``validate``), плюс ручной CLI ``python -m sports_forecast.orchestration.post_refresh_digest``
(R39.4). Этот скрипт **не** единственный способ получить Telegram digest: он остаётся
legacy-смоуком для локальной проверки тайминга (MSK), контура ``cron_refresh`` + ``validate``
и вызова того же digest-модуля, что и в проде.

По умолчанию ждёт до **следующей целой минуты по Europe/Moscow** + ``--offset-seconds``, затем
выполняет тот же контур, что ``cron_refresh`` без ``--dry-run`` для ``nhl`` / ``winner_withOT``
/ ``advanced``, затем ``python -m sports_forecast.validation.run_validation`` (как во втором task
DAG). Сводка в Telegram — через **``post_refresh_digest``** (как DAG), а не через HTTP
``/predict/upcoming`` (кроме флага ``--legacy-api-summary``).

Секреты: ``BOT_TOKEN``, ``BOT_ALLOWED_USER_IDS`` (первый id — чат для лички), опционально
``BOT_API_BASE_URL`` или ``--api-base`` (для ``--legacy-api-summary`` только; по умолчанию
``http://127.0.0.1:8000``).

Пример::

    uv run python scripts/run_nhl_refresh_notify.py
    uv run python scripts/run_nhl_refresh_notify.py --delay-seconds 30 --skip-validate
    uv run python scripts/run_nhl_refresh_notify.py --skip-pipeline --skip-telegram

**Коды выхода (ветка по умолчанию, без ``--legacy-api-summary``):** при ``--skip-telegram``
используется код процесса digest с ``--dry-run``, но если ``cron_refresh`` упал — всегда
``1``. Если запрошена отправка в Telegram и пайплайн/validate в порядке — код **только** из
digest без ``--dry-run``. Если digest не отправляли из-за упавшего refresh/validate — ``1``,
при этом для отладки печатается digest с ``--dry-run`` в stdout.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zoneinfo
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]

logger = logging.getLogger(__name__)


def _delay_until_next_msk_minute_plus_offset(*, offset_seconds: float) -> float:
    """Секунды сна до начала следующей минуты по МСК + offset (не меньше 5 с)."""
    tz = zoneinfo.ZoneInfo("Europe/Moscow")
    now = datetime.now(tz)
    next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    target = next_minute + timedelta(seconds=offset_seconds)
    return max(5.0, (target - now).total_seconds())


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def _telegram_send(*, token: str, chat_id: str, text: str) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4090]}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))


def _fetch_upcoming_summary(api_base: str) -> str:
    base = api_base.rstrip("/")
    params = {
        "live_pinnacle": "true",
        "market": "winner_withOT",
        "market_spec": "winner_withOT",
    }
    try:
        r = httpx.get(f"{base}/predict/upcoming/nhl", params=params, timeout=120.0)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return f"API /predict/upcoming/nhl: ошибка {type(exc).__name__}: {exc}"
    n = int(data.get("count", 0))
    preds = data.get("predictions") or []
    lines = [f"count={n}"]
    for item in preds[:8]:
        hp = item.get("home_player", "?")
        ap = item.get("away_player", "?")
        dt = item.get("match_datetime", "")
        st = item.get("live_odds_status", "")
        edge = item.get("edge_home")
        bet = item.get("bet_decision_home")
        edge_a = item.get("edge_away")
        bet_a = item.get("bet_decision_away")
        tail = f" live={st}" if st else ""
        if edge is not None:
            tail += f" edge={float(edge):+.3f}"
        if bet:
            tail += f" bet={bet}"
        if edge_a is not None:
            tail += f" edge_a={float(edge_a):+.3f}"
        if bet_a:
            tail += f" bet_a={bet_a}"
        lines.append(f"• {hp} — {ap} @ {dt}{tail}")
    if n > 8:
        lines.append(f"… ещё {n - 8} матч(ей)")
    return "\n".join(lines)


def _digest_argv(*, project_root: Path, dry_run: bool) -> list[str]:
    """Полная argv для ``subprocess.run``: interpreter + ``-m post_refresh_digest`` + флаги."""
    cmd = [
        sys.executable,
        "-m",
        "sports_forecast.orchestration.post_refresh_digest",
        "--project-root",
        str(project_root),
        "--tournament",
        "nhl",
        "--market",
        "winner_withOT",
        "--market-spec",
        "winner_withOT",
    ]
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def _run_post_refresh_digest(
    *, project_root: Path, dry_run: bool
) -> subprocess.CompletedProcess[str]:
    """Запускает digest CLI; stdout/stderr захватываются для печати/логов."""
    cmd = _digest_argv(project_root=project_root, dry_run=dry_run)
    logger.info("Запуск post_refresh_digest: %s %s", cmd[0], " ".join(cmd[1:]))
    return subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_refresh(project_dir: Path) -> None:
    cmd = [
        sys.executable,
        "-m",
        "sports_forecast.orchestration.cron_refresh",
        "--tournaments",
        "nhl",
        "--features",
        "advanced",
        "--market",
        "winner_withOT",
        "--market-spec",
        "winner_withOT",
        "--project-dir",
        str(project_dir),
    ]
    logger.info("Запуск cron_refresh: %s", " ".join(cmd))
    subprocess.run(cmd, cwd=project_dir, check=True)


def _run_validate(project_dir: Path) -> None:
    cmd = [sys.executable, "-m", "sports_forecast.validation.run_validation"]
    logger.info("Запуск run_validation")
    subprocess.run(cmd, cwd=project_dir, check=True)


def _val_line(
    *,
    skip_validate: bool,
    skip_pipeline: bool,
    validate_ok: bool | None,
    validate_err: str,
) -> str:
    if skip_validate:
        return "validate: skipped"
    if skip_pipeline:
        return "validate: skipped (no pipeline)"
    if validate_ok is True:
        return "validate: OK"
    if validate_ok is False:
        return "validate: FAIL " + validate_err
    return "validate: skipped (refresh failed)"


def _run_legacy_api_telegram_flow(
    *,
    args: argparse.Namespace,
    pipeline_ok: bool,
    pipeline_err: str,
    validate_ok: bool | None,
    validate_err: str,
) -> int:
    """Прежнее поведение: тело сообщения из HTTP ``/predict/upcoming/nhl`` + Telegram."""
    api_base = (
        args.api_base or os.getenv("BOT_API_BASE_URL") or ""
    ).strip() or "http://127.0.0.1:8000"
    summary = _fetch_upcoming_summary(api_base)

    val_line = _val_line(
        skip_validate=bool(args.skip_validate),
        skip_pipeline=bool(args.skip_pipeline),
        validate_ok=validate_ok,
        validate_err=validate_err,
    )
    header = (
        "NHL тест-пайплайн\n"
        f"refresh: {'OK' if pipeline_ok else 'FAIL ' + pipeline_err}\n"
        f"{val_line}\n"
    )
    body = header + "\n" + summary

    if args.skip_telegram:
        print(body)
        return 0 if pipeline_ok else 1

    token = (os.getenv("BOT_TOKEN") or "").strip()
    raw_ids = (os.getenv("BOT_ALLOWED_USER_IDS") or "").strip()
    chat = raw_ids.split(",")[0].strip() if raw_ids else ""
    if not token or not chat:
        logger.error("Нет BOT_TOKEN или BOT_ALLOWED_USER_IDS — печатаю сводку в stdout")
        print(body)
        return 1 if not pipeline_ok else 0

    try:
        resp = _telegram_send(token=token, chat_id=chat, text=body)
        ok = bool(resp.get("ok"))
        logger.info("Telegram sendMessage ok=%s", ok)
    except urllib.error.HTTPError:
        logger.exception("Telegram HTTP error")
        print(body)
        return 1

    overall_ok = pipeline_ok and (validate_ok is not False)
    return 0 if overall_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=None,
        help="Фиксированная задержка перед пайплайном (сек). Если не задано — следующая минута МСК + offset.",
    )
    parser.add_argument(
        "--offset-seconds",
        type=float,
        default=15.0,
        help="Смещение после следующей целой минуты МСК (если не задан --delay-seconds).",
    )
    parser.add_argument(
        "--api-base",
        default="",
        help="Базовый URL API для --legacy-api-summary (иначе BOT_API_BASE_URL или http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Не вызывать run_validation после refresh.",
    )
    parser.add_argument(
        "--skip-pipeline",
        action="store_true",
        help="Пропустить cron_refresh (digest / legacy-сводка без refresh).",
    )
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="Не отправлять сообщение в Telegram (digest с --dry-run).",
    )
    parser.add_argument(
        "--legacy-api-summary",
        action="store_true",
        help=(
            "[deprecated] Собрать тело сообщения через GET /predict/upcoming/nhl (httpx) "
            "вместо post_refresh_digest. Сохранено для отладки старого пути; по умолчанию "
            "используйте digest CLI (R39.8)."
        ),
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    _load_env()

    delay = (
        float(args.delay_seconds)
        if args.delay_seconds is not None
        else _delay_until_next_msk_minute_plus_offset(offset_seconds=args.offset_seconds)
    )
    logger.info(
        "План: пауза %.1f с (МСК сейчас %s), затем пайплайн NHL",
        delay,
        datetime.now(zoneinfo.ZoneInfo("Europe/Moscow")).strftime("%H:%M:%S"),
    )
    time.sleep(delay)

    pipeline_ok = True
    pipeline_err = ""
    validate_ok: bool | None = None
    validate_err = ""
    if not args.skip_pipeline:
        try:
            _run_refresh(PROJECT_ROOT)
        except subprocess.CalledProcessError as exc:
            pipeline_ok = False
            pipeline_err = f"{type(exc).__name__} returncode={exc.returncode}"
            logger.error("cron_refresh завершился с ошибкой: %s", pipeline_err)
        else:
            if not args.skip_validate:
                try:
                    _run_validate(PROJECT_ROOT)
                    validate_ok = True
                except subprocess.CalledProcessError as exc:
                    validate_ok = False
                    validate_err = f"{type(exc).__name__} returncode={exc.returncode}"

    if args.legacy_api_summary:
        return _run_legacy_api_telegram_flow(
            args=args,
            pipeline_ok=pipeline_ok,
            pipeline_err=pipeline_err,
            validate_ok=validate_ok,
            validate_err=validate_err,
        )

    val_line = _val_line(
        skip_validate=bool(args.skip_validate),
        skip_pipeline=bool(args.skip_pipeline),
        validate_ok=validate_ok,
        validate_err=validate_err,
    )
    header_text = (
        "NHL тест-пайплайн\n"
        f"refresh: {'OK' if pipeline_ok else 'FAIL ' + pipeline_err}\n"
        f"{val_line}\n"
    )

    if args.skip_telegram:
        proc = _run_post_refresh_digest(project_root=PROJECT_ROOT, dry_run=True)
        if proc.stderr:
            logger.info("post_refresh_digest stderr: %s", proc.stderr.strip())
        print(header_text, end="")
        sys.stdout.write(proc.stdout)
        digest_rc = int(proc.returncode)
        return digest_rc if pipeline_ok else 1

    safe_to_send_digest = pipeline_ok and (validate_ok is not False)
    if not safe_to_send_digest:
        logger.error(
            "post_refresh_digest (Telegram) пропущен: refresh/validate не успешны — см. dry-run ниже"
        )
        print(header_text, end="")
        proc = _run_post_refresh_digest(project_root=PROJECT_ROOT, dry_run=True)
        if proc.stderr:
            logger.info("post_refresh_digest stderr: %s", proc.stderr.strip())
        sys.stdout.write(proc.stdout)
        return 1

    proc = _run_post_refresh_digest(project_root=PROJECT_ROOT, dry_run=False)
    if proc.stdout:
        logger.info("post_refresh_digest stdout: %s", proc.stdout.strip()[:2000])
    if proc.stderr:
        logger.info("post_refresh_digest stderr: %s", proc.stderr.strip())
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
