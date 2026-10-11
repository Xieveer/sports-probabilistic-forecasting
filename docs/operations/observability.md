# Production observability mapping

Grafana Alloy собирает container logs и внутренние HTTP signals; Caddy не
публикует `/metrics`. В публичный ingress доступны только API routes, а
`/health`/`/ready` используются отдельными probes.

| Signal | Источник | Alert condition |
|---|---|---|
| API liveness/readiness | `/health`, `/ready` | non-200 или DB unavailable |
| Bot | `/tmp/sf-bot-heartbeat.json` healthcheck | старше 120 сек. или Telegram/internal API false |
| Data Cycle | `data_cycle_runs`, `data_cycle_stage_results` и container exit | failed, незавершённый run или отсутствие daily terminal run |
| Worker | `worker_executions` | failed или `materialization_failed` |
| Prediction freshness | `predictions.prediction_ts` | старше daily SLA |
| Resources/restarts | container/host metrics Alloy | memory/CPU limit, restart loop |

Для canonical full-history NHL alert memory должен срабатывать до `3 GiB` hard
limit: локальное evidence зафиксировало ≈2.31 GiB peak RSS. `materialization_failed`
при нулевом upcoming inference input — безопасный failed run, а не основание
выдавать предыдущую витрину публично.

Heartbeat и execution state содержат только timestamps, boolean flags,
allow-listed code и count. Нельзя передавать в Alloy token, user/chat ID,
username, текст сообщения, query secrets или ответы Telegram API.

## Расследование сбоя Data Cycle

1. Получить `run_id` из админ-команды бота `/cycle_history` или истории
   `GET /admin/pipelines/nhl/runs` через существующий закрытый Control API.
   Открыть `GET /admin/runs/{run_id}`: сверить `status`, `current_stage`,
   `failure_code`, результаты и timestamps этапов. Это источник истины о
   завершении цикла; сообщения логов сами по себе не означают публикацию.
2. На хосте проверить unit данного UUID и его журнал:

   ```bash
   systemctl status "sports-forecast-data-cycle@${run_id}.service"
   journalctl -u "sports-forecast-data-cycle@${run_id}.service" --no-pager -o short-iso
   ```

   Искать `run_id`, `stage` и безопасный `code` ошибки. Для долгоживущих API
   и бота использовать собранные Alloy container logs либо
   `docker compose -f docker-compose.prod.yml logs --since 1h api telegram-bot`.
   Одноразовые контейнеры запускаются с `--rm`; их прошлый вывод искать в
   журнале unit/собранных логах, а не по имени уже удалённого контейнера.

   Коды слоёв отличаются: CLI сообщает причину внутри Worker, а DTO этапа
   хранит безопасный код Data Cycle. Для двух известных случаев соответствие
   такое:

   | CLI `code` | Этап | DTO этапа `failure_code` |
   |---|---|---|
   | `canonical_freshness_failed` | `quality` | `quality_failed` |
   | `materialization_failed` | `publication` | `publication_failed` |

   Для других причин сверять этап и категорию отказа по исходному сообщению и
   DTO; буквальное совпадение кодов между слоями не требуется. `failure_code`
   всего run может появиться только после terminal-завершения.
3. Сопоставить версию с release evidence в
   [production handoff](production-handoff.md) и image digest в активной
   конфигурации Compose. Если текущая версия расходится с ожидаемой, сообщить
   точный `run_id`, этап, код и image digest при эскалации. Не копировать в
   отчёт секреты, Telegram ID и полные ответы внешних API.

Проверка инструкции после выпуска: взять один известный `failed` run, открыть
его DTO, найти хотя бы одну запись журнала по `run_id`, подтвердить этап и
согласованность причины с учётом таблицы выше, сверить image digest с release
evidence. Зафиксировать время от получения
`run_id` до определения причины; целевой ориентир — до пяти минут без просмотра
всех контейнеров. Если запись не находится, отдельно проверить доставку Alloy
и срок хранения Docker-логов. Тестовый сбой не создаёт новый production run.
