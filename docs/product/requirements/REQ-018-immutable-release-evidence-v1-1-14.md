# REQ-018 — Immutable evidence для release v1.1.14

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-09-08

## Результат и ценность

Operations получает проверяемый candidate contract, не смешивая статический
application source и факты, которые возникают только после публикации образов.

## Scope

- Application tag `v1.1.14` фиксирует package version и статический rollout contract.
- После зелёного tag pipeline отдельный evidence commit/tag `v1.1.14-evidence.1`
  фиксирует source binding, пять digest references, candidate handoff и run evidence.
- Automated gate проверяет manifest и rendered private Compose до evidence tag.

## Non-scope

- Production deployment, migrations, bootstrap import, scheduler и Telegram delivery.
- Изменение VPS, SSH, firewall, DNS, TLS, Caddy или выдача Docker/sudo прав.

## Сценарии

1. Release owner создаёт immutable application tag; tag CI публикует и проверяет образы.
2. После успешных runs release owner формирует evidence commit, запускает gate и только затем
   создаёт annotated evidence tag.
3. Любой отсутствующий/лишний digest, credential-like value, public port или неверный source
   binding останавливает evidence gate.

## Критерии приёмки

- [ ] `v1.1.14` совпадает с package version и не содержит dynamic evidence.
- [ ] Evidence bundle ссылается на exact source tag/40-hex commit и содержит ровно пять images.
- [ ] Gate проверяет digest schema, Compose mapping, ports, UID/GID и migration boundary.
- [ ] Candidate handoff не содержит historical readiness conclusion `v1.1.12`.

## Ограничения, зависимости и риски

- Final image digest/provenance/run URL возникают после application tag; их нельзя помещать в
  этот tag без self-reference.
- Защита от force-update/delete tags настраивается владельцем репозитория вне Git tree.

## Подтверждение

Владелец 2026-09-08 выбрал отдельный immutable evidence commit/tag
`v1.1.14-evidence.1` после зелёного pipeline.
