# TASK-025-28 — Acceptance для HTML `/docs`

> **Статус:** независимое review кода и документации без блокирующих findings; release gate открыт.

`/docs` теперь проверяется по HTTP 200 и HTML content type. Отдельный
`/openapi.json` подтверждает JSON и версию API. Ответы не печатаются.

Red: реалистичный HTML mock дал `docs: недоступен`; после добавления проверки
OpenAPI старый код ошибочно трактовал её ответ как prediction. Green: адресный
`tests/test_acceptance_check.py` — `4 passed` под cgroup `MemoryMax=768M`,
`MemorySwapMax=0` и timeout 35 секунд. Production ещё не проверялся.
