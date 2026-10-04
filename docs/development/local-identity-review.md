# Локальная очередь связей сущностей

Review UI запускается отдельным приложением и слушает только `127.0.0.1:8765`.
Он не входит в `sports_forecast.service.app` и публичный production API.

## Подготовка и запуск

Явно создать или обновить локальную schema registry:

```bash
uv run python -c 'from pathlib import Path; from sports_forecast.identity import EntityRegistry; EntityRegistry(Path("data/entity-registry.sqlite3")).initialize()'
```

Создать локальный секрет с ограниченными правами:

```bash
umask 077
python -c 'import secrets; print(secrets.token_urlsafe(48))' > data/identity-review.secret
chmod 600 data/identity-review.secret
```

Запустить из корня репозитория:

```bash
uv run python -m sports_forecast.identity.review_server --registry data/entity-registry.sqlite3 --secret-file data/identity-review.secret --actor owner
```

Открыть `http://127.0.0.1:8765/login` и ввести секрет. Остановить сервер: `Ctrl+C` в
терминале запуска. Сервер намеренно привязан к loopback и не предназначен для
проксирования или доступа из локальной сети.
