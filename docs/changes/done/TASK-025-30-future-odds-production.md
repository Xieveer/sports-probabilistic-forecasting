# TASK-025-30 — Будущие коэффициенты в production

> **Статус:** независимое review кода и документации без блокирующих findings; интеграционные gates открыты.

## Причина

API в v1.2.10 не получал file-backed ключи Odds API, поэтому
`live_pinnacle=true` возвращал `missing_api_key`. Production profile отключал
`data_odds`. Runner связывал тот же флаг с историческим backfill, хотя
REQ-025 требует отдельного сбора будущих коэффициентов.

## Исправление

- API получает тот же file-backed набор Odds API keys, что Worker, без передачи
  значений через Compose environment.
- Runner всегда собирает NHL source без исторического OddsStore post-step;
  Worker использует `SF_DATA_ODDS_ENABLED` только для будущего batch.
- Production Compose validator и контрактные тесты проверяют API secret mounts
  и разделение шагов.

## Проверки

- Red: тест Compose credentials упал с отсутствием четырёх `*_FILE` в API;
  тест runner упал, потому что source-acquirer получал общий odds flag.
- Green: адресные тесты Compose и runner прошли с cgroup `MemoryMax=768M`,
  `MemorySwapMax=0` и timeout 40 секунд.
- Смежный набор из 111 тестов выявил несовпадение production Compose
  validator с новым допустимым API contract; validator и тест исправлены.
- Совокупный адресный набор после исправления validator и документации:
  `144 passed` под cgroup `MemoryMax=1536M`, `MemorySwapMax=0`, timeout 100 секунд.
- `make lint`, `make type-check`, `make production-check`, Ruff для изменённых
  scripts и `git diff --check` прошли под ограничениями ресурсов.
- Production evidence и release CI открыты.

В локальном изолированном контуре исторический backfill и полный pytest не
запускались. Production профиль пока не изменялся.
