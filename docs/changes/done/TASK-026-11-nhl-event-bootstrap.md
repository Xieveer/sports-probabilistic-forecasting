# TASK-026-11 — Доверенное наполнение NHL events

## Результат

Добавлены `nhl_event_bootstrap` и ручной CLI для одного семидневного окна
официального NHL schedule. По умолчанию CLI выполняет dry-run; запись требует
явного `--apply`. Событие создаётся только при подтверждённых и действующих на
время матча связях турнира и команд, точном UTC времени и отсутствии конфликтов.
Повторный импорт не создаёт дубли. Неоднозначные строки идемпотентно попадают
в локальную review queue, где владелец принимает решение. В audit сохраняется
происхождение NHL game ID. The Odds API event IDs этим действием не связываются.

## Локальное evidence 2026-10-11

- Исходный master создан консистентной SQLite backup копией проверенного
  staging master v1.3.1. До изменений отдельная локальная резервная копия
  `data/registry/backups/pre-nhl-events-20261011.sqlite3` сохранена с правами
  `0600`; SHA-256
  `77e1364f436bc8abeb0a417b8fa264abdf1f7b7730f881153ce4a7383fee6eee`,
  `PRAGMA integrity_check = ok`, 0 событий.
- Официальный NHL schedule anchor `2026-10-11` вернул 51 матч с точным временем
  от `2026-10-11T21:00:00Z` до `2026-10-18T02:00:00Z`. Dry-run: 51 `planned`,
  0 `needs_review`. Применение: 51 `created`; повтор: 51 `already_present`.
  После применения: 85 entities, 51 event relations, 51 event designations,
  0 review candidates; `PRAGMA integrity_check = ok`.
- Экспортирован и установлен локально verified snapshot
  `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce`:
  85 entities, 153 designations, 51 events. Read-only parity YAML → master →
  snapshot: 100 известных team aliases, 0 различий. Строгий offline resolver
  разрешил все 51 NHL game IDs в 51 разных project events.
- После создания snapshot CLI dry-run вернул 51 `already_present`; master не
  менялся. Пакет ещё не опубликован в Object Storage и не установлен на сервер.

## Проверки

- Целевые тесты `tests/test_nhl_event_bootstrap.py` и
  `tests/test_nhl_event_bootstrap_cli.py`: 15 passed после исправлений.
- Независимое review проверило транзакцию, идемпотентность, validity intervals,
  состояния сущностей, конфликты, безопасный dry-run и отсутствие автоматического
  букмекерского mapping; новых P0–P2 нет. Его целевой прогон вместе с legacy
  cutover: 23 passed; `git diff --check` чист.
- `make lint` — passed; `make docs` — passed с одним предупреждением Sphinx.
- `make test-unit` — 1679 passed, 17 deselected.
- Итог полного unit, CI и production gates фиксируется отдельно в EPIC-026 и
  [EPIC-035](../../backlog/EPIC-035-v1-3-2-registry-rollout.md).

## Остаточные gates

Нужны новая публикация verified snapshot, сверка с текущим production горизонтом
и реальный NHL forecast cycle. Требуется также непустой кандидатный цикл с
решением владельца и проверенный rollback до включения strict reader. Старый
snapshot и compatibility код сохраняются для возврата; удаление legacy кода
отложено пользователем на отдельную инициативу.
