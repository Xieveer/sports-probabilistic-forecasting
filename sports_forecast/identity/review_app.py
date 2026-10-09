"""Изолированное локальное FastAPI-приложение для очереди registry."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import time
from pathlib import Path
from typing import Literal, cast
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from sports_forecast.identity.review_service import ReviewQueueService


COOKIE = "identity_review_session"
SESSION_SECONDS = 3600


def _secret(path: Path) -> bytes:
    """Прочитать secret file с локальными правами доступа."""
    if not path.is_file() or os.name != "nt" and path.stat().st_mode & 0o077:
        raise RuntimeError("Secret file должен быть обычным файлом с правами 0600")
    value = path.read_bytes().strip()
    if len(value) < 24:
        raise RuntimeError("Secret file должен содержать не менее 24 байт")
    return value


def _token(secret: bytes, payload: bytes) -> str:
    """Подписать payload HMAC-SHA256."""
    import base64

    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode(secret: bytes, token: str) -> dict[str, object] | None:
    """Проверить подпись, срок и формат сессии."""
    import base64

    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        value = json.loads(raw)
        if not isinstance(value, dict) or int(value.get("exp", 0)) < int(time.time()):
            return None
        if not isinstance(value.get("csrf"), str):
            return None
        return value
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _loopback_post(request: Request) -> bool:
    """Требовать точное совпадение loopback Host и Origin authority."""
    from urllib.parse import urlsplit

    host = request.headers.get("host", "")
    origin = request.headers.get("origin", "")
    parsed = urlsplit(origin)
    host_url = urlsplit("//" + host)
    return (
        host_url.hostname in {"127.0.0.1", "::1"}
        and parsed.scheme == "http"
        and parsed.netloc == host
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
    )


async def _bounded_body(request: Request, limit: int) -> bytes | None:
    """Считать тело небольшими chunks, сразу прекращая oversized POST."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit or int(content_length) < 0:
                return None
        except ValueError:
            return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def create_review_app(queue: ReviewQueueService, *, secret_path: Path, actor: str) -> FastAPI:
    """Создать отдельное приложение, предназначенное только для loopback."""
    secret_file = Path(secret_path)
    if not actor.strip():
        raise ValueError("Actor обязателен")
    _secret(secret_file)
    app = FastAPI(title="Локальная очередь подтверждения связей", docs_url=None, redoc_url=None)

    @app.get("/login", response_class=HTMLResponse)
    def login_page() -> str:
        return '<!doctype html><meta charset="utf-8"><title>Вход</title><form method="post" action="/login"><label>Локальный секрет <input type="password" name="secret" required></label><button>Войти</button></form>'

    @app.post("/login")
    async def login(request: Request) -> Response:
        if not _loopback_post(request):
            return Response(status_code=403)
        body = await _bounded_body(request, 4096)
        if body is None:
            return Response(status_code=413)
        form = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        supplied = form.get("secret", [""])[0].encode()
        try:
            actual = _secret(secret_file)
        except RuntimeError:
            return Response(status_code=503)
        if not hmac.compare_digest(supplied, actual):
            return Response(status_code=403)
        csrf = secrets.token_urlsafe(24)
        token = _token(
            actual, json.dumps({"exp": int(time.time()) + SESSION_SECONDS, "csrf": csrf}).encode()
        )
        response = RedirectResponse("/review", status_code=303)
        response.set_cookie(
            COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict", path="/"
        )
        return response

    @app.get("/review", response_class=HTMLResponse)
    def review_page(
        request: Request,
        q: str = "",
        status: str = "pending",
        source: str = "",
        tournament: str = "",
        entity_q: str = "",
        event_tournament_q: str = "",
        event_team_q: str = "",
        offset: int = 0,
    ) -> Response:
        try:
            secret = _secret(secret_file)
        except RuntimeError:
            return Response("Secret недоступен", status_code=503)
        session = _decode(secret, request.cookies.get(COOKIE, ""))
        if session is None:
            return RedirectResponse("/login", status_code=303)
        page_size = 50
        page_offset = min(max(offset, 0), 100_000)
        candidates = queue.list_candidates(
            status=status,
            query=q[:100],
            source=source[:100],
            tournament=tournament[:100],
            limit=page_size + 1,
            offset=page_offset,
        )
        has_next = len(candidates) > page_size
        candidates = candidates[:page_size]

        def page_url(next_offset: int) -> str:
            params = urlencode(
                {
                    "q": q,
                    "status": status,
                    "source": source,
                    "tournament": tournament,
                    "entity_q": entity_q,
                    "event_tournament_q": event_tournament_q,
                    "event_team_q": event_team_q,
                    "offset": next_offset,
                }
            )
            return "/review?" + html.escape(params, quote=True)

        csrf = html.escape(str(session["csrf"]), quote=True)

        def relation_options(kind: Literal["team", "tournament"], query: str) -> str:
            entities = queue.search_entities(kind=kind, query=query[:100], limit=100)
            return "<option value=''>Выберите...</option>" + "".join(
                "<option value='"
                + html.escape(entity.id, quote=True)
                + "'>"
                + html.escape(f"{entity.project_name} ({entity.id})")
                + "</option>"
                for entity in entities
            )

        event_fields = (
            "<fieldset><legend>Связи нового события</legend>"
            "<label>Турнир <select name='new_event_tournament_id'>"
            + relation_options("tournament", event_tournament_q)
            + "</select></label><label>Хозяева <select name='new_event_home_team_id'>"
            + relation_options("team", event_team_q)
            + "</select></label><label>Гости <select name='new_event_away_team_id'>"
            + relation_options("team", event_team_q)
            + "</select></label><label>Начало (UTC, ISO 8601) <input name='new_event_scheduled_at' placeholder='2026-10-05T17:30:00Z'></label></fieldset>"
        )
        items: list[str] = []
        for item in candidates:
            suggestion_entities = {}
            for entity_id in item.proposed_entity_ids:
                try:
                    entity = queue.registry.get_entity(entity_id)
                except KeyError:
                    continue
                suggestion_entities[entity.id] = entity
            for entity in queue.search_entities(kind=item.kind, query=entity_q[:100]):
                suggestion_entities[entity.id] = entity
            options = ["<option value=''>Выберите project entity</option>"]
            for entity in suggestion_entities.values():
                entity_value = entity.id
                if entity.kind == "event":
                    try:
                        relation_revision = queue.registry.get_event_relation(entity.id).revision
                    except KeyError:
                        relation_revision = None
                    if relation_revision is not None:
                        entity_value = f"{entity.id}|{relation_revision}"
                options.append(
                    "<option value='"
                    + html.escape(entity_value, quote=True)
                    + "'>"
                    + html.escape(f"{entity.project_name} ({entity.id})")
                    + "</option>"
                )
            history_html = ""
            if item.history:
                history_html = (
                    "<details><summary>Предыдущие версии evidence</summary>"
                    + "".join(
                        "<p>Revision "
                        + str(previous.revision)
                        + " · "
                        + html.escape(previous.status)
                        + " · "
                        + html.escape(previous.basis)
                        + " · "
                        + html.escape(json.dumps(previous.facts, ensure_ascii=False))
                        + "</p>"
                        for previous in item.history
                    )
                    + "</details>"
                )
            if item.history_count:
                history_html += (
                    f"<a href='/review/candidates/{html.escape(item.id, quote=True)}/history'>"
                    f"Полная история ({item.history_count})</a>"
                )
            items.append(
                "<article><label><input type='checkbox' name='selected_id' value='"
                + html.escape(item.id, quote=True)
                + "'> выбрать</label><h2>"
                + html.escape(item.raw_value)
                + "</h2><p>Источник: "
                + html.escape(item.source)
                + " · "
                + html.escape(item.origin)
                + "</p><p>Scope: "
                + html.escape(json.dumps(item.scope, ensure_ascii=False))
                + "</p><p>Текущая связь: "
                + html.escape(
                    (item.designation_state + " · " + item.confirmed_entity_id)
                    if item.confirmed_entity_id
                    else item.designation_state
                )
                + "</p><p>Варианты: "
                + html.escape(
                    "; ".join(entity.project_name for entity in suggestion_entities.values())
                )
                + "</p><p>Основание: "
                + html.escape(item.basis)
                + "</p>"
                + history_html
                + f"<label>Связать с сущностью <select name='entity_id_{html.escape(item.id, quote=True)}'>"
                + "".join(options)
                + f"</select></label><input type='hidden' name='candidate_id' value='{html.escape(item.id, quote=True)}'><input type='hidden' name='revision_{html.escape(item.id, quote=True)}' value='{item.revision}'><input type='hidden' name='designation_revision_{html.escape(item.id, quote=True)}' value='{item.designation_revision}'></article>"
            )
        body = (
            "<!doctype html><meta charset='utf-8'><title>Очередь</title><form method='get'><input name='q' placeholder='Поиск обозначения' value='"
            + html.escape(q, quote=True)
            + "'><input name='source' placeholder='Источник' value='"
            + html.escape(source, quote=True)
            + "'><input name='tournament' placeholder='Tournament UUID' value='"
            + html.escape(tournament, quote=True)
            + "'><input name='entity_q' placeholder='Поиск проектной сущности' value='"
            + html.escape(entity_q, quote=True)
            + "'><input name='event_tournament_q' placeholder='Поиск турнира для события' value='"
            + html.escape(event_tournament_q, quote=True)
            + "'><input name='event_team_q' placeholder='Поиск команды для события' value='"
            + html.escape(event_team_q, quote=True)
            + "'><select name='status'><option value='pending'>pending</option><option value='all'>all</option><option value='confirmed'>confirmed</option><option value='rejected'>rejected</option><option value='deferred'>deferred</option></select><button>Фильтр</button></form><form method='post' action='/review/decision'><input type='hidden' name='csrf' value='"
            + csrf
            + "'>"
            + "".join(items)
            + "<input name='entity_id' placeholder='UUID сущности'><select name='new_entity_kind'><option value='team'>team</option><option value='tournament'>tournament</option><option value='event'>event</option></select><input name='new_entity_name' placeholder='Новое проектное имя'><input name='sport' placeholder='Вид спорта'><input name='reason' required placeholder='Основание решения'>"
            + event_fields
            + "<button name='action' value='confirm'>Подтвердить UUID</button><button name='action' value='create_entity'>Создать и подтвердить</button><button name='action' value='update_relation'>Обновить связи выбранного события</button><button name='action' value='reject'>Отклонить</button><button name='action' value='defer'>Отложить</button></form>"
        )
        if page_offset > 0:
            body += (
                f"<a rel='prev' href='{page_url(max(0, page_offset - page_size))}'>Предыдущая</a>"
            )
        if has_next:
            body += f"<a rel='next' href='{page_url(page_offset + page_size)}'>Следующая</a>"
        return HTMLResponse(body)

    @app.get("/review/candidates/{candidate_id}/history", response_class=HTMLResponse)
    def candidate_history(request: Request, candidate_id: str, offset: int = 0) -> Response:
        """Показать ограниченную страницу полной evidence-истории кандидата."""
        try:
            secret = _secret(secret_file)
        except RuntimeError:
            return Response("Secret недоступен", status_code=503)
        session = _decode(secret, request.cookies.get(COOKIE, ""))
        if session is None:
            return RedirectResponse("/login", status_code=303)
        try:
            candidate = queue.get(candidate_id)
            page_offset = min(max(offset, 0), 100_000)
            revisions = queue.list_history(candidate_id, limit=21, offset=page_offset)
        except KeyError:
            return Response("Кандидат не найден", status_code=404)
        has_next = len(revisions) > 20
        revisions = revisions[:20]
        rows = "".join(
            "<article><h2>Revision "
            + str(entry.revision)
            + " · "
            + html.escape(entry.status)
            + " · "
            + html.escape(entry.observed_at)
            + "</h2><p>Основание: "
            + html.escape(entry.basis)
            + "</p><pre>"
            + html.escape(json.dumps(entry.facts, ensure_ascii=False, indent=2))
            + "</pre></article>"
            for entry in revisions
        )
        body = (
            "<!doctype html><meta charset='utf-8'><title>История evidence</title><h1>История: "
            + html.escape(candidate.raw_value)
            + "</h1><a href='/review'>К очереди</a>"
            + rows
        )
        if page_offset > 0:
            body += f"<a rel='prev' href='/review/candidates/{html.escape(candidate_id, quote=True)}/history?offset={max(0, page_offset - 20)}'>Предыдущая</a>"
        if has_next:
            body += f"<a rel='next' href='/review/candidates/{html.escape(candidate_id, quote=True)}/history?offset={page_offset + 20}'>Следующая</a>"
        return HTMLResponse(body)

    @app.post("/review/decision")
    async def decide(request: Request) -> Response:
        if not _loopback_post(request):
            return Response(status_code=403)
        try:
            secret = _secret(secret_file)
        except RuntimeError:
            return Response(status_code=503)
        session = _decode(secret, request.cookies.get(COOKIE, ""))
        if session is None:
            return Response(status_code=403)
        raw_body = await _bounded_body(request, 32768)
        if raw_body is None:
            return Response(status_code=413)
        form = parse_qs(raw_body.decode("utf-8", errors="replace"), keep_blank_values=True)
        if not hmac.compare_digest(form.get("csrf", [""])[0], str(session["csrf"])):
            return Response(status_code=403)
        try:
            from sports_forecast.identity.review_service import (
                CandidateDecision,
                NewEventRelation,
                NewProjectEntity,
            )

            action = form["action"][0]
            selected_ids = form.get("selected_id", [])
            if not selected_ids:
                raise ValueError("Выберите кандидата")
            if action == "create_entity" and len(selected_ids) != 1:
                raise ValueError("Создание сущности применимо к одному кандидату за раз")
            if action == "update_relation" and len(selected_ids) != 1:
                raise ValueError("Коррекция связей события применима к одному кандидату за раз")
            new_entity = None
            if action == "create_entity":
                entity_kind = cast(
                    Literal["tournament", "team", "event"], form["new_entity_kind"][0]
                )
                relation = None
                if entity_kind == "event":
                    relation = NewEventRelation(
                        tournament_id=form["new_event_tournament_id"][0],
                        home_team_id=form["new_event_home_team_id"][0],
                        away_team_id=form["new_event_away_team_id"][0],
                        scheduled_at=form["new_event_scheduled_at"][0],
                    )
                new_entity = NewProjectEntity(
                    kind=entity_kind,
                    project_name=form["new_entity_name"][0],
                    sport=form["sport"][0],
                    event_relation=relation,
                )
            updated_relation = None
            if action == "update_relation":
                updated_relation = NewEventRelation(
                    tournament_id=form["new_event_tournament_id"][0],
                    home_team_id=form["new_event_home_team_id"][0],
                    away_team_id=form["new_event_away_team_id"][0],
                    scheduled_at=form["new_event_scheduled_at"][0],
                )

            selected_targets: dict[str, tuple[str | None, int | None]] = {}
            for candidate_id in selected_ids:
                raw_entity_id = form.get(f"entity_id_{candidate_id}", [None])[0] or None
                expected_relation_revision = None
                if raw_entity_id is not None and "|" in raw_entity_id:
                    raw_entity_id, raw_revision = raw_entity_id.rsplit("|", 1)
                    expected_relation_revision = int(raw_revision)
                selected_targets[candidate_id] = (raw_entity_id, expected_relation_revision)

            decisions = [
                CandidateDecision(
                    candidate_id=candidate_id,
                    expected_revision=int(form[f"revision_{candidate_id}"][0]),
                    expected_designation_revision=int(
                        form[f"designation_revision_{candidate_id}"][0]
                    ),
                    action=cast(
                        Literal["confirm", "reject", "defer", "create_entity", "update_relation"],
                        action,
                    ),
                    reason=form["reason"][0],
                    entity_id=selected_targets[candidate_id][0],
                    new_entity=new_entity,
                    event_relation=updated_relation,
                    expected_event_relation_revision=selected_targets[candidate_id][1],
                )
                for candidate_id in selected_ids
            ]
            queue.decide_batch(decisions, actor=actor)
        except (KeyError, ValueError):
            return Response("Решение не применено: перечитайте очередь", status_code=409)
        return RedirectResponse("/review", status_code=303)

    return app
