# Секреты и окружение: GitHub, CI, VPS

Кратко: **в GitHub Actions** хранятся только учётные данные для сборки/деплоя; **на сервере** — рабочий `.env` с паролями БД, токенами бота и API ключами. Не дублируйте production-секреты в репозиторий.

Workflow **Deploy** после успешного **Docker** на `main` запускается автоматически (`workflow_run`) или вручную (`workflow_dispatch`). При необходимости ограничьтесь ручным деплоем (отключите триггер в `.github/workflows/deploy.yml`).

## GitHub Actions

### Реестр образов (R23.2)

- Для push в `ghcr.io` достаточно встроенного `GITHUB_TOKEN` (в workflow задано `packages: write`).
- Отдельный `GHCR_TOKEN` **не обязателен**, если пушите в пакеты того же репозитория от имени `GITHUB_TOKEN`.

### Деплой по SSH (R23.4)

| Имя | Тип | Назначение |
|-----|-----|------------|
| `DEPLOY_HOST` | Secret | IP или hostname VPS |
| `DEPLOY_USER` | Secret | SSH пользователь |
| `DEPLOY_SSH_KEY` | Secret | Приватный ключ (PEM), **без** пароля для unattended |

Опционально **Variables** (не секреты):

| Имя | Назначение |
|-----|-------------|
| `DEPLOY_PROJECT_DIR` | Каталог с клоном репозитория и compose на сервере; если пусто, в workflow используется `/opt/sports-forecast` |

На сервере пользователь должен иметь право запускать `docker compose` (часто через группу `docker`).

## Сервер (VPS)

1. Клон репозитория и файл `.env` по шаблону [.env.example](../../.env.example).
2. Значения `SF_*_IMAGE` должны совпадать с пакетами, которые публикует
   `.github/workflows/docker.yml` (owner и имя пакета в нижнем регистре, как
   правило) и использовать SemVer-тег конкретного release, например `1.0.0`,
   а не `latest`.
3. `POSTGRES_PASSWORD`, `GRAFANA_PASSWORD`, `BOT_TOKEN`, `ODDS_API_KEY_FREE`,
   `ODDS_API_KEY_20K` и `ODDS_API_KEY_100K` задаются **только** в серверном
   `.env` (или в менеджере секретов), не в GitHub, если это не нужно для CI.
   Клиент расходует ключи в этом порядке; старый `ODDS_API_KEY` допустим только
   как временный fallback для существующей конфигурации.
4. Эпик **R39** (post-refresh Telegram **digest** в Airflow): для отправки сводки и вызова Odds API из задачи digest те же значения `BOT_TOKEN`, `BOT_ALLOWED_USER_IDS` (и при необходимости все настроенные `ODDS_API_KEY_*`) должны быть доступны **процессу Airflow** (не только контейнеру `api` / `telegram-bot`). Проброс — в `environment` сервисов Airflow в compose или эквивалент на VPS; подробности — `docs/source/nhl_local_operations.rst` (раздел Prod-like E2E).

## Basic auth за Caddy (Grafana / MLflow)

1. На машине с Caddy: `caddy hash-password`.
2. Вынесите хэш в переменные окружения контейнера `caddy` (например `GRAFANA_BASIC_AUTH_USER`, `GRAFANA_BASIC_AUTH_HASH`).
3. Раскомментируйте соответствующий блок в [deploy/Caddyfile](../../deploy/Caddyfile).

## См. также

- [docker-compose.prod.yml](../../docker-compose.prod.yml) — production overrides, лимиты, Caddy, node_exporter.
- [sports_forecast/orchestration/cron_refresh.py](../../sports_forecast/orchestration/cron_refresh.py) — расписание NHL без Airflow.

## Выпуск образов

Версия задаётся только в [`pyproject.toml`](../../pyproject.toml). После успешной
предпроизводственной проверки уполномоченный оператор создаёт Git-тег
`v<version>`; workflow Docker сверяет его с package metadata и публикует
одноимённый SemVer-тег вместе с SHA-тегом каждого образа. Создание тега, push
образов и deployment требуют отдельных разрешений владельца.
