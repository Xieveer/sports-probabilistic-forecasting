"""Контракт лёгкого poll коэффициентов notification-профиля."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import create_engine

from sports_forecast.orchestration.notification_profiles import NotificationProfile
from sports_forecast.orchestration.notification_state import QuoteSnapshot
from sports_forecast.orchestration.odds_poll_notification import PredictionInput
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import NotificationStateRepository


@pytest.fixture
def profile() -> NotificationProfile:
    """Создать нейтральный профиль для проверки poll."""
    return NotificationProfile(
        profile_id="demo-hockey",
        tournament="demo_league",
        market="winner",
        market_spec="winner",
        window_hours=48,
        timezone="Europe/Moscow",
        heavy_schedule="0 10 * * *",
        max_active_runs=1,
        max_active_tasks=1,
        refresh_pool="refresh-pool",
        lock_file="/tmp/demo-heavy.lock",
        lock_wait_seconds=300,
        enabled=True,
    )


@pytest.fixture
def state_repository():
    """Создать чистое хранилище notification state."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    with get_session(engine=engine) as session:
        yield NotificationStateRepository(session)
    engine.dispose()
    reset_engine()


def test_poll_stops_without_batch_request_when_no_relevant_predictions(
    profile: NotificationProfile,
    state_repository: NotificationStateRepository,
) -> None:
    """Пустое окно не вызывает adapter и не создаёт пользовательскую доставку."""
    from sports_forecast.orchestration.odds_poll_notification import run_odds_poll

    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    calls = 0

    def fetch_quotes(_: Sequence[PredictionInput]) -> list[QuoteSnapshot]:
        nonlocal calls
        calls += 1
        return []

    result = run_odds_poll(
        profile=profile,
        now=now,
        predictions=[],
        fetch_quotes=fetch_quotes,
        allowed_chat_ids=("101",),
        token="test-token",
        state_repository=state_repository,
    )

    assert result.status == "no_relevant_matches"
    assert calls == 0


def test_poll_does_not_send_for_unchanged_line(
    monkeypatch,
    profile: NotificationProfile,
    state_repository: NotificationStateRepository,
) -> None:
    """Неизменённая известная линия завершает cycle без сообщения."""
    import sports_forecast.orchestration.odds_poll_notification as subject

    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    snapshot = QuoteSnapshot("match-1", now + timedelta(hours=2), {"home": 1.8, "away": 2.2})
    state_repository.save_line(profile.profile_id, snapshot.match_id, '{"away":2.2,"home":1.8}')
    monkeypatch.setattr(subject, "telegram_send_message", lambda **_: pytest.fail("Не отправлять"))

    result = subject.run_odds_poll(
        profile=profile,
        now=now,
        predictions=[object()],
        fetch_quotes=lambda _: [snapshot],
        allowed_chat_ids=("101",),
        token="test-token",
        state_repository=state_repository,
    )

    assert result.status == "no_change"
    assert result.recipient_count == 0


def test_poll_fans_out_one_aggregate_for_new_and_changed_lines(
    monkeypatch,
    profile: NotificationProfile,
    state_repository: NotificationStateRepository,
) -> None:
    """Один batch создаёт одно агрегированное обновление для каждого получателя."""
    import sports_forecast.orchestration.odds_poll_notification as subject

    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    state_repository.save_line(profile.profile_id, "known", '{"away":2.2,"home":1.8}')
    sent: list[tuple[str, str]] = []

    def send(*, token: str, chat_id: str, text: str) -> dict[str, bool]:
        sent.append((chat_id, text))
        return {"ok": True}

    monkeypatch.setattr(
        subject,
        "telegram_send_message",
        send,
    )

    result = subject.run_odds_poll(
        profile=profile,
        now=now,
        predictions=[object(), object()],
        fetch_quotes=lambda _: [
            QuoteSnapshot("known", now + timedelta(hours=2), {"home": 1.9, "away": 2.1}),
            QuoteSnapshot("new", now + timedelta(hours=3), {"home": 1.7, "away": 2.3}),
        ],
        allowed_chat_ids=("101", "202"),
        token="test-token",
        state_repository=state_repository,
    )

    assert result.status == "notification_created"
    assert result.recipient_count == 2
    assert [chat_id for chat_id, _ in sent] == ["101", "202"]
    assert len({text for _, text in sent}) == 1
    assert "known" in sent[0][1]
    assert "new" in sent[0][1]


def test_retry_after_later_recipient_failure_does_not_repeat_sent_recipient(
    monkeypatch,
    profile: NotificationProfile,
    tmp_path,
) -> None:
    """Доставка первому получателю переживает rollback из-за сбоя следующего."""
    import sports_forecast.orchestration.odds_poll_notification as subject

    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
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

    def fetch_quotes(_: Sequence[PredictionInput]) -> list[QuoteSnapshot]:
        return [QuoteSnapshot("match-1", now + timedelta(hours=2), {"home": 1.8, "away": 2.2})]

    try:
        with get_session(engine=engine) as session, pytest.raises(subject.OddsPollError):
            subject.run_odds_poll(
                profile=profile,
                now=now,
                predictions=[object()],
                fetch_quotes=fetch_quotes,
                allowed_chat_ids=("101", "202"),
                token="test-token",
                logical_cycle="2026-08-07T09:15:00Z",
                state_repository=NotificationStateRepository(session),
            )
        with get_session(engine=engine) as session:
            result = subject.run_odds_poll(
                profile=profile,
                now=now,
                predictions=[object()],
                fetch_quotes=fetch_quotes,
                allowed_chat_ids=("101", "202"),
                token="test-token",
                logical_cycle="2026-08-07T09:15:00Z",
                state_repository=NotificationStateRepository(session),
            )
    finally:
        engine.dispose()
        reset_engine()

    assert result.recipient_count == 1
    assert sent == ["101", "202", "202"]


def test_poll_excludes_started_quotes(
    monkeypatch,
    profile: NotificationProfile,
    state_repository: NotificationStateRepository,
) -> None:
    """Линия начавшегося матча не формирует delta или сообщение."""
    import sports_forecast.orchestration.odds_poll_notification as subject

    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    monkeypatch.setattr(subject, "telegram_send_message", lambda **_: pytest.fail("Не отправлять"))

    result = subject.run_odds_poll(
        profile=profile,
        now=now,
        predictions=[object()],
        fetch_quotes=lambda _: [QuoteSnapshot("started", now, {"home": 1.8, "away": 2.2})],
        allowed_chat_ids=("101",),
        token="test-token",
        state_repository=state_repository,
    )

    assert result.status == "no_relevant_matches"


def test_poll_exposes_batch_fetch_failure(
    profile: NotificationProfile,
    state_repository: NotificationStateRepository,
) -> None:
    """Ошибка adapter-а остаётся ошибкой task, чтобы DAG уведомил только admin list."""
    from sports_forecast.orchestration.odds_poll_notification import OddsPollError, run_odds_poll

    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)

    with pytest.raises(OddsPollError, match="Не удалось получить live коэффициенты"):
        run_odds_poll(
            profile=profile,
            now=now,
            predictions=[object()],
            fetch_quotes=lambda _: (_ for _ in ()).throw(OSError("network unavailable")),
            allowed_chat_ids=("101",),
            token="test-token",
            state_repository=state_repository,
        )


def test_direct_h2h_adapter_makes_one_batch_request(monkeypatch) -> None:
    """Прямой adapter передаёт все релевантные матчи в один batch provider-а."""
    import sports_forecast.orchestration.live_odds_adapter as subject
    from sports_forecast.data.providers.odds.live_nhl_pinnacle import PinnacleH2HQuote

    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    seen: list[list[str]] = []
    monkeypatch.setattr(subject, "load_nhl_team_name_registry", lambda: None)

    def fetch_quotes_for_refs(refs, **_):
        seen.append([ref.match_id for ref in refs])
        return {
            "match-1": PinnacleH2HQuote(
                odds_api_event_id="event-1",
                home_team="Home",
                away_team="Away",
                commence_utc=now + timedelta(hours=2),
                decimal_home=1.8,
                decimal_away=2.2,
            ),
            "match-2": None,
        }

    monkeypatch.setattr(subject, "fetch_nhl_pinnacle_quotes_for_refs", fetch_quotes_for_refs)
    predictions = [
        SimpleNamespace(
            match_id="match-1",
            home_player="Home",
            away_player="Away",
            match_datetime=now + timedelta(hours=2),
        ),
        SimpleNamespace(
            match_id="match-2",
            home_player="Other home",
            away_player="Other away",
            match_datetime=now + timedelta(hours=3),
        ),
    ]

    snapshots = subject.fetch_odds_api_h2h_snapshots(
        cast(Sequence[Prediction], predictions),
        bookmaker_config="the_odds_api",
        sport_key="icehockey_nhl",
        bookmaker_key="pinnacle",
        team_registry="nhl",
    )

    assert seen == [["match-1", "match-2"]]
    assert [(item.match_id, item.line) for item in snapshots] == [
        ("match-1", {"home": 1.8, "away": 2.2}),
        ("match-2", None),
    ]


def test_profile_adapter_runtime_contract_is_tournament_neutral(monkeypatch) -> None:
    """CLI передаёт нейтральный профиль registry без условий по tournament slug."""
    import sports_forecast.orchestration.odds_poll_cli as subject

    profile = NotificationProfile(
        profile_id="demo-baseball",
        tournament="demo_baseball",
        market="winner",
        market_spec="winner",
        window_hours=12,
        timezone="UTC",
        heavy_schedule="0 * * * *",
        max_active_runs=1,
        max_active_tasks=1,
        refresh_pool="demo-pool",
        lock_file="/tmp/demo-baseball.lock",
        lock_wait_seconds=0,
        enabled=True,
        live_odds_adapter="demo_adapter",
        live_odds_bookmaker_config="demo_bookmaker",
        live_odds_sport_key="baseball_demo",
        live_odds_bookmaker_key="demo_bookmaker_key",
        live_odds_team_registry="",
    )
    predictions = [object()]
    seen: list[tuple[str, str, str, str, list[object]]] = []

    def fetch(profile_arg, predictions_arg):
        seen.append(
            (
                profile_arg.live_odds_bookmaker_config,
                profile_arg.live_odds_sport_key,
                profile_arg.live_odds_bookmaker_key,
                profile_arg.live_odds_team_registry,
                predictions_arg,
            )
        )
        return []

    monkeypatch.setattr(subject, "fetch_profile_snapshots", fetch)

    assert subject._fetch_quotes(profile, predictions) == []  # type: ignore[arg-type]
    assert seen == [("demo_bookmaker", "baseball_demo", "demo_bookmaker_key", "", predictions)]
