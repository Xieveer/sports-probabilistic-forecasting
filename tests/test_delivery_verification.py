"""Контракт явной однократной проверки Telegram-доставки."""

from __future__ import annotations

from pathlib import Path

from sports_forecast.orchestration import delivery_verification as subject


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_missing_send_opt_in_does_not_call_telegram(monkeypatch) -> None:
    """Без ``--send`` команда завершается до чтения секретов и сети."""
    sent: list[object] = []
    monkeypatch.setattr(subject, "telegram_send_message", lambda **kwargs: sent.append(kwargs))

    assert subject.main(["--release-image", "sha256:release", "--model-version", "model-1"]) == 2
    assert sent == []


def test_delivery_uses_one_secret_configured_recipient_and_safe_evidence(
    monkeypatch, capsys
) -> None:
    """Opt-in отправляет один запрос и не раскрывает token/recipient в evidence."""
    sent: list[dict[str, str]] = []
    monkeypatch.setenv("BOT_TOKEN", "token-that-must-not-leak")
    monkeypatch.setenv("SF_DELIVERY_VERIFICATION_CHAT_ID", "recipient-that-must-not-leak")

    def send(**kwargs: str) -> dict[str, bool]:
        sent.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(subject, "telegram_send_message", send)

    assert (
        subject.main(
            [
                "--send",
                "--release-image",
                "ghcr.io/acme/api@sha256:release",
                "--model-version",
                "model-20260809",
            ]
        )
        == 0
    )

    assert len(sent) == 1
    assert sent[0]["chat_id"] == "recipient-that-must-not-leak"
    assert sent[0]["token"] == "token-that-must-not-leak"
    assert "ghcr.io/acme/api@sha256:release" in sent[0]["text"]
    assert "model-20260809" in sent[0]["text"]
    output = capsys.readouterr().out
    assert "ghcr.io/acme/api@sha256:release" in output
    assert "model-20260809" in output
    assert "token-that-must-not-leak" not in output
    assert "recipient-that-must-not-leak" not in output


def test_failed_telegram_response_does_not_report_delivery(monkeypatch, capsys) -> None:
    """Ответ Telegram без ``ok`` оставляет оператору безопасный неуспешный статус."""
    monkeypatch.setenv("BOT_TOKEN", "token-that-must-not-leak")
    monkeypatch.setenv("SF_DELIVERY_VERIFICATION_CHAT_ID", "recipient-that-must-not-leak")
    monkeypatch.setattr(subject, "telegram_send_message", lambda **_: {"ok": False})

    assert (
        subject.main(["--send", "--release-image", "sha256:release", "--model-version", "model-1"])
        == 1
    )
    output = capsys.readouterr().out
    assert "не доставлена" in output
    assert "token-that-must-not-leak" not in output
    assert "recipient-that-must-not-leak" not in output


def test_delivery_verification_is_not_wired_into_automated_entrypoints() -> None:
    """CI, Airflow и non-mutating acceptance не могут вызвать внешнюю отправку."""
    scheduled_paths = [
        PROJECT_ROOT / "scripts" / "acceptance_check.py",
        *(PROJECT_ROOT / ".github" / "workflows").glob("*.yml"),
        *(PROJECT_ROOT / "airflow" / "dags").glob("*.py"),
    ]

    assert all(
        "delivery_verification" not in path.read_text(encoding="utf-8") for path in scheduled_paths
    )
