# TASK-032-2 — отчёт об исправлении release Compose gate

## Изменено

- В `.github/workflows/docker.yml` оба вызова `docker compose config`
  включают `registry-sync` и `registry-feedback`.
- В `.github/workflows/release-evidence.yml` оба rendered Compose включают
  те же профили.
- `tests/test_release_version_contract.py` проверяет профили в обоих
  workflow.
- `verify_release_evidence.py` проверяет оба registry сервиса с образом
  `archive_sync`, UID/GID и запретом DDL; fixture и тесты обновлены.

## Проверки

- Red: `uv run --offline pytest tests/test_release_version_contract.py -q -k tag_and_evidence_gates_render_all_registry_services` — `1 failed`, до правки.
- Green: `uv run --offline pytest tests/test_release_version_contract.py -q` — `14 passed`.
- Реальные `docker compose ... config --quiet`, `config` и
  `verify_production_compose_contract.py` с fixture `1.3.0` и всеми профилями
  завершились успешно.
- Red: `uv run --offline pytest tests/test_release_evidence.py -q` —
  `2 failed, 5 passed` после расширения fixture, до исправления verifier.
- Green: `uv run --offline pytest tests/test_release_evidence.py tests/test_release_version_contract.py -q` — `21 passed`.
- Реальный Compose render без scheduler с каноническими synthetic image
  references дал `[]` ошибок в `validate_evidence()`.
- [Tag pipeline v1.3.0](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38142671658)
  завершился `failure` именно на Compose gate; последующие build/push и
  rollout jobs пропущены.

## Ограничения

Повторный PR CI, tag pipeline, независимое review и серверный gate ещё не
выполнены. Immutable тег `v1.3.0` не перемещался. Production не менялся.
