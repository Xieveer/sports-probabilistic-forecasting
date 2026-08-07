"""Контракт initial digest для notification-профиля."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from sports_forecast.orchestration.initial_notification import run_initial_digest
from sports_forecast.orchestration.notification_profiles import NotificationProfile
from sports_forecast.orchestration.notification_state import NotificationStateService, QuoteSnapshot
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import NotificationStateRepository


def test_initial_digest_fans_out_to_all_allowlist_recipients_without_odds(monkeypatch) -> None:
    """Начальный digest рассылается всем получателям и не ждёт коэффициентов."""
    import sports_forecast.orchestration.initial_notification as subject

    now = datetime(2026, 8, 7, 7, 0, tzinfo=UTC)
    sent: list[tuple[str, str]] = []

    def send(*, token: str, chat_id: str, text: str) -> dict[str, bool]:
        sent.append((chat_id, text))
        return {"ok": True}

    monkeypatch.setattr(
        subject,
        "telegram_send_message",
        send,
    )
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    prediction = Prediction(
        id=1,
        match_id="match-1",
        tournament="demo_league",
        market="winner",
        market_spec="winner",
        home_player="Дом",
        away_player="Гости",
        match_datetime=now + timedelta(hours=2),
        model_version="test",
        algorithm="test",
        featureset="test",
        predictions_json='{"home_win": 0.6}',
        proba_home=0.6,
        proba_away=0.4,
    )
    profile = NotificationProfile(
        profile_id="demo-hockey",
        tournament="demo_league",
        market="winner",
        market_spec="winner",
        window_hours=48,
        timezone="Europe/Moscow",
        heavy_schedule="0 10 * * *",
        max_active_runs=1,
        max_active_tasks=1,
        refresh_pool="sf_refresh_pool",
        lock_file="/tmp/demo.lock",
        lock_wait_seconds=300,
        enabled=True,
    )
    try:
        with get_session(engine=engine) as session:
            result = run_initial_digest(
                profile=profile,
                now=now,
                predictions=[prediction],
                quote_snapshots=[],
                allowed_chat_ids=("101", "202"),
                token="test-token",
                state_repository=NotificationStateRepository(session),
            )
    finally:
        engine.dispose()
        reset_engine()

    assert result.status == "notification_created"
    assert [chat_id for chat_id, _ in sent] == ["101", "202"]
    assert len({text for _, text in sent}) == 1


def test_initial_digest_records_baseline_for_unchanged_follow_up(monkeypatch) -> None:
    """Начальный сценарий сохраняет линию, чтобы poll не повторил её без изменения."""
    import sports_forecast.orchestration.initial_notification as subject

    now = datetime(2026, 8, 7, 7, 0, tzinfo=UTC)
    monkeypatch.setattr(subject, "telegram_send_message", lambda **_: {"ok": True})
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    profile = NotificationProfile(
        profile_id="demo-hockey",
        tournament="demo_league",
        market="winner",
        market_spec="winner",
        window_hours=48,
        timezone="Europe/Moscow",
        heavy_schedule="0 10 * * *",
        max_active_runs=1,
        max_active_tasks=1,
        refresh_pool="pool",
        lock_file="/tmp/demo.lock",
        lock_wait_seconds=0,
        enabled=True,
    )
    try:
        with get_session(engine=engine) as session:
            repository = NotificationStateRepository(session)
            snapshot = QuoteSnapshot(
                "match-1", now + timedelta(hours=2), {"home": 1.8, "away": 2.2}
            )
            run_initial_digest(
                profile=profile,
                now=now,
                predictions=[],
                quote_snapshots=[snapshot],
                allowed_chat_ids=("101",),
                token="test-token",
                state_repository=repository,
            )
            follow_up = NotificationStateService(repository).plan_poll(
                profile.profile_id,
                "2026-08-07T07:15:00Z",
                [snapshot],
                now,
            )
    finally:
        engine.dispose()
        reset_engine()

    assert follow_up.status == "no_change"


def test_notify_administrators_fails_closed_for_empty_recipients() -> None:
    """Сбой сценария остаётся наблюдаемым, когда admin allowlist не задан."""
    from sports_forecast.orchestration.initial_notification import (
        NotificationDeliveryError,
        notify_administrators,
    )

    with pytest.raises(NotificationDeliveryError, match="Список администраторов Telegram пуст"):
        notify_administrators(admin_chat_ids=(), token="test-token", failure_kind="poll")


def test_notify_administrators_continues_after_one_delivery_failure(monkeypatch) -> None:
    """Ошибка одного администратора не лишает остальных уведомления."""
    import sports_forecast.orchestration.initial_notification as subject

    sent: list[str] = []

    def send(*, token: str, chat_id: str, text: str) -> dict[str, bool]:
        sent.append(chat_id)
        if chat_id == "101":
            raise OSError("network unavailable")
        return {"ok": True}

    monkeypatch.setattr(subject, "telegram_send_message", send)

    with pytest.raises(subject.NotificationDeliveryError):
        subject.notify_administrators(
            admin_chat_ids=("101", "202"), token="test-token", failure_kind="poll"
        )

    assert sent == ["101", "202"]


def test_notification_logs_mask_chat_id(monkeypatch, caplog) -> None:
    """Лог доставки не раскрывает полный Telegram chat ID."""
    import sports_forecast.orchestration.initial_notification as subject

    monkeypatch.setattr(subject, "telegram_send_message", lambda **_: {"ok": False})
    with caplog.at_level("WARNING"), pytest.raises(subject.NotificationDeliveryError):
        subject.notify_administrators(
            admin_chat_ids=("123456789",), token="test-token", failure_kind="poll"
        )

    assert "123456789" not in caplog.text


def test_initial_cli_fetches_batch_quotes_for_baseline(monkeypatch) -> None:
    """Production initial CLI передаёт прогнозы batch adapter-у коэффициентов."""
    import sports_forecast.orchestration.initial_digest_cli as subject

    profile = NotificationProfile(
        profile_id="demo-hockey",
        tournament="demo_league",
        market="winner",
        market_spec="winner",
        window_hours=48,
        timezone="Europe/Moscow",
        heavy_schedule="0 10 * * *",
        max_active_runs=1,
        max_active_tasks=1,
        refresh_pool="pool",
        lock_file="/tmp/demo.lock",
        lock_wait_seconds=0,
        enabled=True,
    )
    predictions = [object()]
    expected = [QuoteSnapshot("match-1", datetime(2026, 8, 7, tzinfo=UTC), None)]
    monkeypatch.setattr(
        subject,
        "fetch_profile_snapshots",
        lambda received_profile, received: expected,
    )

    assert subject._quote_snapshots(profile, predictions) == expected  # type: ignore[arg-type]


def test_initial_digest_retry_does_not_repeat_successful_recipient(monkeypatch, tmp_path) -> None:
    """Retry initial digest продолжает с неотправленного получателя."""
    import sports_forecast.orchestration.initial_notification as subject

    now = datetime(2026, 8, 7, 7, 0, tzinfo=UTC)
    profile = NotificationProfile(
        profile_id="demo-hockey",
        tournament="demo_league",
        market="winner",
        market_spec="winner",
        window_hours=48,
        timezone="Europe/Moscow",
        heavy_schedule="0 10 * * *",
        max_active_runs=1,
        max_active_tasks=1,
        refresh_pool="pool",
        lock_file="/tmp/demo.lock",
        lock_wait_seconds=0,
        enabled=True,
    )
    sent: list[str] = []
    failed_once = True

    def send(*, token: str, chat_id: str, text: str) -> dict[str, bool]:
        nonlocal failed_once
        sent.append(chat_id)
        if chat_id == "202" and failed_once:
            failed_once = False
            raise OSError("network unavailable")
        return {"ok": True}

    monkeypatch.setattr(subject, "telegram_send_message", send)
    reset_engine()
    engine = create_engine(f"sqlite:///{tmp_path / 'notification.db'}")
    init_db(engine)
    try:
        with (
            get_session(engine=engine) as session,
            pytest.raises(subject.NotificationDeliveryError),
        ):
            subject.run_initial_digest(
                profile=profile,
                now=now,
                predictions=[],
                quote_snapshots=[],
                allowed_chat_ids=("101", "202"),
                token="test-token",
                state_repository=NotificationStateRepository(session),
            )
        with get_session(engine=engine) as session:
            result = subject.run_initial_digest(
                profile=profile,
                now=now,
                predictions=[],
                quote_snapshots=[],
                allowed_chat_ids=("101", "202"),
                token="test-token",
                state_repository=NotificationStateRepository(session),
            )
    finally:
        engine.dispose()
        reset_engine()

    assert result.recipient_count == 1
    assert sent == ["101", "202", "202"]
