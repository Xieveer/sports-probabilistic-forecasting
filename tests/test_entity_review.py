"""Поведенческие тесты локальной очереди связей и HTTP security boundary."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.review_app import create_review_app
from sports_forecast.identity.review_service import (
    CandidateDecision,
    CandidateObservation,
    NewProjectEntity,
    ReviewQueueService,
)


def make_registry(tmp_path: Path) -> EntityRegistry:
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()
    return registry


def make_observation(
    *,
    origin: str = "local:odds-import",
    idempotency_key: str = "batch-1/item-1",
    raw_value: str = "ALP",
    facts: dict[str, str] | None = None,
    proposed_entity_ids: tuple[str, ...] = (),
) -> CandidateObservation:
    return CandidateObservation(
        source="feed",
        kind="team",
        scope={"sport": "hockey", "tournament": "league-uuid"},
        value_kind="external_id",
        raw_value=raw_value,
        origin=origin,
        idempotency_key=idempotency_key,
        observed_at="2026-10-04T12:00:00Z",
        facts=facts or {"provider_name": "Alpine HC"},
        proposed_entity_ids=proposed_entity_ids,
        basis="Точное событие источника содержит название команды",
    )


def test_candidate_is_persisted_and_identical_reingest_does_not_reopen_closed_decision(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    team = registry.create_entity("team", "Alpine", sport="hockey")
    queue = ReviewQueueService(registry)
    observation = make_observation(proposed_entity_ids=(team.id,))

    candidate = queue.observe(observation)
    queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=candidate.id,
                expected_revision=candidate.revision,
                expected_designation_revision=candidate.designation_revision,
                action="reject",
                reason="Название не подтверждает команду",
            )
        ],
        actor="owner",
    )

    repeated = queue.observe(observation)
    later_delivery = queue.observe(
        CandidateObservation(
            source=observation.source,
            kind=observation.kind,
            scope=observation.scope,
            value_kind=observation.value_kind,
            raw_value=observation.raw_value,
            origin=observation.origin,
            idempotency_key=observation.idempotency_key,
            observed_at="2026-10-04T13:00:00Z",
            facts=observation.facts,
            proposed_entity_ids=observation.proposed_entity_ids,
            basis=observation.basis,
        )
    )

    assert repeated.id == candidate.id
    assert repeated.revision == candidate.revision
    assert repeated.status == "rejected"
    assert later_delivery.revision == candidate.revision
    assert later_delivery.status == "rejected"
    assert registry.get_designation(candidate.designation_id).state == "rejected"


def test_material_new_evidence_reopens_as_new_candidate_revision(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    team = registry.create_entity("team", "Alpine", sport="hockey")
    queue = ReviewQueueService(registry)
    observation = make_observation(proposed_entity_ids=(team.id,))
    original = queue.observe(observation)
    queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=original.id,
                expected_revision=original.revision,
                expected_designation_revision=original.designation_revision,
                action="defer",
                reason="Ожидаю второй источник",
            )
        ],
        actor="owner",
    )

    revised = queue.observe(
        make_observation(
            proposed_entity_ids=(team.id,),
            facts={"provider_name": "Alpine HC", "event_id": "ev-991"},
        )
    )

    assert revised.id == original.id
    assert revised.revision == original.revision + 1
    assert revised.status == "pending"
    assert "event_id" in revised.facts
    assert registry.get_designation(original.designation_id).state == "pending"
    assert registry.list_decisions(original.designation_id)[0].action == "defer"


def test_new_evidence_does_not_unconfirm_existing_entity_association(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    team = registry.create_entity("team", "Alpine", sport="hockey")
    queue = ReviewQueueService(registry)
    observation = make_observation(proposed_entity_ids=(team.id,))
    candidate = queue.observe(observation)
    queue.decide_batch(
        [
            CandidateDecision(
                candidate.id,
                candidate.revision,
                candidate.designation_revision,
                "confirm",
                "Связь подтверждена",
                entity_id=team.id,
            )
        ],
        actor="owner",
    )

    revised = queue.observe(
        make_observation(
            proposed_entity_ids=(team.id,), facts={"provider_name": "Alpine", "evidence": "new"}
        )
    )

    assert revised.status == "pending"
    assert registry.get_designation(candidate.designation_id).state == "confirmed"
    assert registry.get_designation(candidate.designation_id).entity_id == team.id
    assert queue.get(candidate.id).status == "pending"
    assert queue.get(candidate.id).history[0].status == "confirmed"
    assert queue.get(candidate.id).history[0].basis == observation.basis


def test_idempotency_key_rejects_scope_mismatch(tmp_path: Path) -> None:
    queue = ReviewQueueService(make_registry(tmp_path))
    observation = make_observation()
    queue.observe(observation)
    with pytest.raises(ValueError, match="scope"):
        queue.observe(
            CandidateObservation(
                source=observation.source,
                kind=observation.kind,
                scope={"sport": "hockey", "tournament": "different-league"},
                value_kind=observation.value_kind,
                raw_value=observation.raw_value,
                origin=observation.origin,
                idempotency_key=observation.idempotency_key,
                observed_at=observation.observed_at,
                facts=observation.facts,
                proposed_entity_ids=observation.proposed_entity_ids,
                basis=observation.basis,
            )
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "s" * 129),
        ("kind", "k" * 41),
        ("value_kind", "v" * 41),
        ("raw_value", "r" * 501),
        ("origin", "o" * 121),
        ("idempotency_key", "i" * 201),
        ("basis", "b" * 2001),
        ("observed_at", "t" * 41),
        ("scope", {"x" * 51: "value"}),
        ("scope", {"tournament": "t" * 201}),
        ("proposed_entity_ids", ("u" * 81,)),
    ],
)
def test_external_candidate_strings_are_bounded_before_persistence(
    tmp_path: Path, field: str, value: object
) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    fields: dict[str, object] = {
        "source": "feed",
        "kind": "team",
        "scope": {"sport": "hockey", "tournament": "league-uuid"},
        "value_kind": "external_id",
        "raw_value": "ALP",
        "origin": "local:odds-import",
        "idempotency_key": "bounded/item",
        "observed_at": "2026-10-04T12:00:00Z",
        "facts": {"name": "Alpine"},
        "proposed_entity_ids": (),
        "basis": "Проверенное основание",
    }
    fields[field] = value

    with pytest.raises(ValueError, match="длин|размер|поле|scope"):
        queue.observe(CandidateObservation(**fields))  # type: ignore[arg-type]

    assert registry.count_designations() == 0


def test_candidate_history_preview_is_bounded_and_full_history_is_paginated(
    tmp_path: Path,
) -> None:
    queue = ReviewQueueService(make_registry(tmp_path))
    candidate = queue.observe(make_observation(facts={"revision": "0"}))
    for revision in range(1, 13):
        candidate = queue.observe(
            make_observation(facts={"revision": str(revision), "change": f"evidence-{revision}"})
        )

    preview = queue.get(candidate.id)
    page_one = queue.list_history(candidate.id, limit=5)
    page_two = queue.list_history(candidate.id, limit=5, offset=5)
    page_three = queue.list_history(candidate.id, limit=5, offset=10)

    assert len(preview.history) <= 5
    assert len(page_one) == len(page_two) == 5
    assert len(page_three) == 2
    assert [entry.revision for entry in page_one + page_two + page_three] == list(range(1, 13))


def test_history_drilldown_renders_bounded_pages(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    candidate = queue.observe(make_observation(facts={"revision": "0"}))
    for revision in range(1, 22):
        candidate = queue.observe(
            make_observation(facts={"revision": str(revision), "change": f"evidence-{revision}"})
        )
    secret_path = tmp_path / "review.secret"
    secret_path.write_text("a-long-random-owner-secret-for-tests", encoding="utf-8")
    secret_path.chmod(0o600)
    client = TestClient(
        create_review_app(queue, secret_path=secret_path, actor="owner"),
        base_url="http://127.0.0.1:8765",
    )
    client.post(
        "/login",
        data={"secret": "a-long-random-owner-secret-for-tests"},
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )

    first_page = client.get(f"/review/candidates/{candidate.id}/history")
    second_page = client.get(f"/review/candidates/{candidate.id}/history?offset=20")

    assert first_page.text.count("<article>") == 20
    assert "rel='next'" in first_page.text
    assert second_page.text.count("<article>") == 1
    assert "rel='prev'" in second_page.text


def test_queue_filters_source_tournament_and_pages_forward(tmp_path: Path) -> None:
    queue = ReviewQueueService(make_registry(tmp_path))
    for index in range(3):
        queue.observe(
            CandidateObservation(
                source="feed-a" if index < 2 else "feed-b",
                kind="team",
                scope={"sport": "hockey", "tournament": "league-a" if index < 2 else "league-b"},
                value_kind="external_id",
                raw_value=f"TEAM-{index}",
                origin="local:test",
                idempotency_key=f"queue/{index}",
                facts={"name": f"Team {index}"},
                basis="Проверка очереди",
            )
        )

    first_page = queue.list_candidates(source="feed-a", tournament="league-a", limit=1)
    next_page = queue.list_candidates(source="feed-a", tournament="league-a", limit=1, offset=1)
    assert len(first_page) == len(next_page) == 1
    assert first_page[0].id != next_page[0].id
    assert queue.list_candidates(source="feed-b", tournament="league-a") == []


def test_review_http_filters_and_next_previous_links(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    for index in range(51):
        queue.observe(
            CandidateObservation(
                source="feed-a",
                kind="team",
                scope={"sport": "hockey", "tournament": "league-a"},
                value_kind="external_id",
                raw_value=f"HTTP-{index}",
                origin="local:paging",
                idempotency_key=f"paging/{index}",
                facts={"index": str(index)},
                basis="Пагинация",
            )
        )
    secret_path = tmp_path / "review.secret"
    secret_path.write_text("a-long-random-owner-secret-for-tests", encoding="utf-8")
    secret_path.chmod(0o600)
    client = TestClient(
        create_review_app(queue, secret_path=secret_path, actor="owner"),
        base_url="http://127.0.0.1:8765",
    )
    client.post(
        "/login",
        data={"secret": "a-long-random-owner-secret-for-tests"},
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )

    first = client.get("/review?source=feed-a&tournament=league-a")
    second = client.get("/review?source=feed-a&tournament=league-a&offset=50")

    assert "name='source'" in first.text and "name='tournament'" in first.text
    assert "rel='next'" in first.text and "rel='prev'" not in first.text
    assert "rel='prev'" in second.text


def test_local_data_files_are_ignored_by_git() -> None:
    repository = Path(__file__).resolve().parents[1]
    for path in (
        "data/identity-review.secret",
        "data/entity-registry.sqlite",
        "data/entity-registry.sqlite3",
    ):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", path],
            cwd=repository,
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode == 0, path


@pytest.mark.parametrize("stale_field", ["candidate", "designation"])
def test_batch_revision_conflict_rolls_back_all_candidate_decisions_and_entities(
    tmp_path: Path, stale_field: str
) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    first = queue.observe(make_observation(idempotency_key="batch-2/first", raw_value="A"))
    second = queue.observe(make_observation(idempotency_key="batch-2/second", raw_value="B"))
    stale_candidate_revision = (
        second.revision - 1 if stale_field == "candidate" else second.revision
    )
    stale_designation_revision = (
        second.designation_revision - 1
        if stale_field == "designation"
        else second.designation_revision
    )

    with pytest.raises(ValueError, match="revision"):
        queue.decide_batch(
            [
                CandidateDecision(
                    candidate_id=first.id,
                    expected_revision=first.revision,
                    expected_designation_revision=first.designation_revision,
                    action="create_entity",
                    reason="Создать новую команду",
                    new_entity=NewProjectEntity(
                        kind="team", project_name="New Team", sport="hockey"
                    ),
                ),
                CandidateDecision(
                    candidate_id=second.id,
                    expected_revision=stale_candidate_revision,
                    expected_designation_revision=stale_designation_revision,
                    action="defer",
                    reason="Устаревшая форма",
                ),
            ],
            actor="owner",
        )

    assert queue.get(first.id).status == "pending"
    assert queue.get(second.id).status == "pending"
    assert registry.list_entities(kind="team") == []
    assert registry.list_decisions(queue.get(first.id).designation_id) == []


def test_create_entity_and_confirm_candidate_are_atomic_and_audited(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    candidate = queue.observe(make_observation())

    result = queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=candidate.id,
                expected_revision=candidate.revision,
                expected_designation_revision=candidate.designation_revision,
                action="create_entity",
                reason="Владелец создаёт проектную команду",
                new_entity=NewProjectEntity(kind="team", project_name="Alpine HC", sport="hockey"),
            )
        ],
        actor="owner",
    )

    entity = registry.list_entities(kind="team")[0]
    assert result[0].status == "confirmed"
    assert (
        registry.resolve(
            "feed", "team", {"sport": "hockey", "tournament": "league-uuid"}, "external_id", "ALP"
        ).entity_id
        == entity.id
    )
    assert registry.list_entity_audit(entity.id)[0].action == "create"
    assert registry.list_entity_audit(entity.id)[0].reason == "Владелец создаёт проектную команду"


def test_server_origin_candidate_is_preserved_and_batch_decision_commits_together(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    first = queue.observe(
        make_observation(origin="server", idempotency_key="snapshot/9", raw_value="A")
    )
    second = queue.observe(
        make_observation(origin="local:history", idempotency_key="history/2", raw_value="B")
    )

    results = queue.decide_batch(
        [
            CandidateDecision(
                first.id, first.revision, first.designation_revision, "defer", "Нужна проверка"
            ),
            CandidateDecision(
                second.id,
                second.revision,
                second.designation_revision,
                "reject",
                "Нет подтверждения",
            ),
        ],
        actor="owner",
    )

    assert [item.status for item in results] == ["deferred", "rejected"]
    assert queue.get(first.id).origin == "server"
    assert len(registry.list_decisions(first.designation_id)) == 1
    assert len(registry.list_decisions(second.designation_id)) == 1


def test_local_page_submits_selected_batch_with_candidate_and_designation_revisions(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    team_a = registry.create_entity("team", "Alpine", sport="hockey")
    team_b = registry.create_entity("team", "Boreal", sport="hockey")
    first = queue.observe(
        make_observation(idempotency_key="ui/1", raw_value="A", proposed_entity_ids=(team_a.id,))
    )
    second = queue.observe(
        make_observation(idempotency_key="ui/2", raw_value="B", proposed_entity_ids=(team_b.id,))
    )
    secret_path = tmp_path / "review.secret"
    secret_path.write_text("a-long-random-owner-secret-for-tests", encoding="utf-8")
    secret_path.chmod(0o600)
    client = TestClient(
        create_review_app(queue, secret_path=secret_path, actor="owner"),
        base_url="http://127.0.0.1:8765",
    )
    client.post(
        "/login",
        data={"secret": "a-long-random-owner-secret-for-tests"},
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    page = client.get("/review?entity_q=Alp").text
    csrf = re.search(r"name='csrf' value='([^']+)'", page)
    assert csrf is not None
    assert f"name='entity_id_{first.id}'" in page
    assert f"value='{team_a.id}'>Alpine ({team_a.id})</option>" in page

    response = client.post(
        "/review/decision",
        data={
            "csrf": csrf.group(1),
            "selected_id": [first.id, second.id],
            "candidate_id": [first.id, second.id],
            f"revision_{first.id}": str(first.revision),
            f"designation_revision_{first.id}": str(first.designation_revision),
            f"revision_{second.id}": str(second.revision),
            f"designation_revision_{second.id}": str(second.designation_revision),
            f"entity_id_{first.id}": team_a.id,
            f"entity_id_{second.id}": team_b.id,
            "action": "confirm",
            "reason": "Связь проверена владельцем",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert [queue.get(first.id).status, queue.get(second.id).status] == ["confirmed", "confirmed"]
    assert registry.get_designation(first.designation_id).entity_id == team_a.id
    assert registry.get_designation(second.designation_id).entity_id == team_b.id


def test_review_http_requires_session_csrf_and_exact_loopback_origin(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    queue.observe(make_observation(raw_value="<script>alert(1)</script>"))
    secret_path = tmp_path / "review.secret"
    secret_path.write_text("a-long-random-owner-secret-for-tests", encoding="utf-8")
    secret_path.chmod(0o600)
    client = TestClient(
        create_review_app(queue, secret_path=secret_path, actor="owner"),
        base_url="http://127.0.0.1:8765",
    )

    assert client.get("/review", follow_redirects=False).status_code == 303
    login = client.get("/login")
    assert not login.url.query
    response = client.post(
        "/login",
        data={"secret": "a-long-random-owner-secret-for-tests"},
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie
    page = client.get("/review")
    assert "&lt;script&gt;" in page.text
    assert "<script>alert(1)</script>" not in page.text

    assert client.post("/review/decision", data={"candidate_id": "bad"}).status_code == 403
    assert (
        client.post(
            "/review/decision",
            data={"candidate_id": "bad"},
            headers={"Origin": "http://127.0.0.1:8765"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/review/decision",
            data={"candidate_id": "bad"},
            headers={"Origin": "http://evil.example"},
        ).status_code
        == 403
    )


def test_review_http_get_is_read_only_and_production_app_has_no_review_routes(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    candidate = queue.observe(make_observation())
    secret_path = tmp_path / "review.secret"
    secret_path.write_text("a-long-random-owner-secret-for-tests", encoding="utf-8")
    secret_path.chmod(0o600)
    client = TestClient(
        create_review_app(queue, secret_path=secret_path, actor="owner"),
        base_url="http://127.0.0.1:8765",
    )
    response = client.get("/review", follow_redirects=False)
    assert response.status_code == 303
    assert queue.get(candidate.id).status == "pending"

    from sports_forecast.service.app import app

    assert not any(getattr(route, "path", "").startswith("/review") for route in app.routes)


def test_post_bodies_are_rejected_before_form_parsing_when_oversized(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    queue = ReviewQueueService(registry)
    secret_path = tmp_path / "review.secret"
    secret_path.write_text("a-long-random-owner-secret-for-tests", encoding="utf-8")
    secret_path.chmod(0o600)
    client = TestClient(
        create_review_app(queue, secret_path=secret_path, actor="owner"),
        base_url="http://127.0.0.1:8765",
    )

    login = client.post(
        "/login",
        content=b"x" * 4097,
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    client.post(
        "/login",
        data={"secret": "a-long-random-owner-secret-for-tests"},
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    decision = client.post(
        "/review/decision",
        content=b"x" * 32769,
        headers={"Origin": "http://127.0.0.1:8765"},
    )

    assert login.status_code == 413
    assert decision.status_code == 413
