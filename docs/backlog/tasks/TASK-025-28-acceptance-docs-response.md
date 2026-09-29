# TASK-025-28 — Исправить проверку `/docs` в acceptance script

> **Статус:** blocked
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Следующий кодовый релиз:** исходный tag `v1.2.10` неизменяем.

## Дефект

`scripts/acceptance_check.py` вызывает JSON parser для `GET /docs`, хотя
FastAPI отдаёт HTML с `200 text/html`. Поэтому `make acceptance-check` ложно
сообщает `docs: недоступен` на здоровом API. Текущие тесты подменяют `/docs`
JSON-ответом и не обнаруживают ошибку.

## Критерии будущего исправления

- Проверять `GET /docs` по HTTP 200 и HTML content type, а схему API — через
  `GET /openapi.json` с проверкой JSON.
- Адресный тест использует реалистичные типы ответов и сначала воспроизводит
  ложный отказ.
- Сохранить read-only характер acceptance и отсутствие вывода payload/secrets.
- Провести независимое review и ограниченные проверки перед следующим tag.

## Обход для выпуска v1.2.10

В release handoff зафиксированы эквивалентные read-only HTTP/DB/bot проверки;
их результаты сохраняются в Operations change record. Production rollout
можно оценивать по этим проверкам без изменения immutable source tag.
