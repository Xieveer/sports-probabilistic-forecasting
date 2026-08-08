# Передача сервиса в эксплуатацию

Этот документ — контракт между командой приложения и DevOps Operations Agent. Команда
приложения заполняет его до запроса на production-развёртывание. Operations Agent использует
его как входные данные, но самостоятельно проверяет сервер, секреты, Compose, мониторинг,
rollout и rollback в репозитории управления инфраструктурой.

- Статус подготовки: `candidate`

`draft` означает, что контракт ещё заполняется и развёртывание не разрешено. Перед передачей
в эксплуатацию установите `candidate`, замените все шаблонные пометки и выполните
`make production-check`.

## Идентификация и ответственность

- Название сервиса: Sports Probabilistic Forecasting 1.0.0.
- Репозиторий и основной branch: SportsProbabilisticForecasting, `main`.
- Владелец приложения: пользователь.
- Владелец решения о production-развёртывании: пользователь.
- DevOps Operations Agent получает право только на подготовку PR; само развёртывание требует
  отдельного явного одобрения владельца.

## Runtime и конфигурация

- Команда запуска контейнера: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
- Требуемая версия Python и системные зависимости: Python 3.12; curl и libpq-dev в Dockerfile.
- Переменные окружения: перечислить имена и назначение по `.env.example`, без значений.
- Внешние зависимости, адреса и ожидаемые таймауты: PostgreSQL, MLflow, Telegram, NHL API и The Odds API; timeout Odds API 120 секунд.
- Порты и исходящие сетевые соединения: API 8000; Caddy 80/443; исходящий HTTPS к внешним API.

## Healthcheck и smoke-проверка

- Команда или endpoint liveness: `curl -sf http://127.0.0.1:8000/health`.
- Команда или endpoint readiness, проверяющий значимые зависимости: `/health` проверяет БД.
- Безопасная smoke-проверка после запуска: GET `/health` и `/docs` без пользовательских данных.
- Ожидаемый результат и максимальное время ожидания: HTTP 200 за 90 секунд.

## Данные и совместимость

- Постоянные данные и тома: PostgreSQL, MLflow artifacts, `data/`, `models/` и monitoring volumes; фактические пути проверяет Operations Agent.
- Миграции и порядок их выполнения: additive DB schema и `init_db()` до API; Operations Agent подтверждает backup и порядок на VPS.
- Совместимость новой версии с предыдущей: rollback выполняется immutable предыдущим образом; миграции не удаляют данные в этом выпуске.
- Требования к резервному копированию и восстановлению: Operations Agent делает backup PostgreSQL и persistent volumes до rollout и проверяет restore.

## Наблюдаемость

- Структурированные события запуска, остановки, heartbeat и ошибок: приложение пишет структурированные логи; container lifecycle собирает Operations Agent.
- Поля для корреляции: `service`, `environment`, `version` и прикладные идентификаторы.
- Метрики доступности, ошибок, ресурсов и результата работы: `/metrics`, healthcheck, container/host metrics; dashboards и alerts настраивает Operations Agent.
- Данные, которые необходимо маскировать до отправки логов: все env secrets, Telegram token, пароли, Odds API keys и HTTP query с ключами.
- Предлагаемые пороги оповещений и ссылки на runbook: недоступность `/health`, restart loop, ошибка refresh; runbook — `docs/source/nhl_local_operations.rst`.

## Артефакт и откат

- Registry и неизменяемый идентификатор image (`digest` или commit): GHCR image `:1.0.0` плюс digest, который передаётся после publish.
- Способ доказать происхождение артефакта: Git tag `v1.0.0`, совпадающий с `pyproject.toml`, и SHA-tag CI image.
- Предыдущая исправная версия: определяется Operations Agent из последнего работоспособного immutable image.
- Процедура и допустимое время отката: вернуть Compose на предыдущий immutable image и проверить `/health`; целевое время определяет Operations Agent.
- Критерии остановки rollout: health не 200, DB недоступна, crash loop или рост ошибок refresh.

## Нерешённые вопросы

- До отдельного разрешения не созданы Git tag, immutable images и deployment; Operations Agent должен заполнить digest и VPS evidence перед rollout.

## Граница ответственности

Агент приложения отвечает за код, тесты, Dockerfile, healthcheck, безопасные логи,
CI-проверки, неизменяемый артефакт и этот документ. DevOps Operations Agent отвечает за
проверку фактического production-окружения, секреты, Compose/systemd, доступы, наблюдаемость,
rollout, rollback и эксплуатационную документацию. Ни одна из сторон не подменяет явное
одобрение владельца на production-развёртывание.
