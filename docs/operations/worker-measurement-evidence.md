# Evidence full-history canonical refresh

Измерение выполнено 2026-08-16 на локальном production-like NHL fixture. Оно
не является свидетельством production deployment, published image или доступа
к Object Storage.

## Входные артефакты

| Поле | Фактическое значение |
|---|---|
| Dataset identity | `source.csv` SHA-256 `bb8f3ac446e9599a8b24b96eeb279a0fc540af3e86b4e089900761ab5e1effb1` |
| Canonical bootstrap artifact | `sha256:bb8f3ac446e9599a8b24b96eeb279a0fc540af3e86b4e089900761ab5e1effb1` |
| Bootstrap (migration → bundle → import) | exit 0; 26.86 сек.; max RSS 1 096 276 KiB (≈1.05 GiB); temporary disk 459 MiB |
| Model bundle ID | `sha256:b8a3658027c512c4c55eb396bb4f517c2e0df15d94da682fc0b7e241ab155522` |
| Model identity | `nhl:winner_withOT:canonical-measurement` |
| Application image digest | Не создавался: локальный `uv run` без image. |
| Commit / release | `50b8d7b` / `1.1.0-measurement` |
| Canonical events / completed matches | 22 218 / 20 597 |
| Inference rows | 0: source не содержит пригодных для витрины upcoming матчей после фильтрации live state. |

## Команда и результат

```bash
/usr/bin/time -f 'elapsed=%E max_rss_kb=%M exit=%x' \
  timeout 45m uv run python -m sports_forecast.orchestration.canonical_full_refresh_cli \
    tournament=nhl market=winner_withOT market_spec=winner_withOT \
    algorithm=catboost features=advanced
```

| Показатель | Результат |
|---|---|
| UTC start/finish | 2026-08-16 09:38:14–09:39:56 |
| Exit code | 1 |
| Elapsed | 1:42.02 |
| Max RSS | 2 422 428 KiB (≈2.31 GiB) |
| Temporary disk growth | 464 MiB (SQLite, bootstrap, model bundle и archive staging) |
| Feature pipeline | 75.39 сек.; 489 features; 41 194 long rows / 20 597 wide rows |
| `worker_executions` safe outcome | `nhl-full-history-measurement-20260816T093814Z / failed / materialization_failed` |
| Publication | Не выполнена: `inference_long.parquet` отсутствует при нулевом inference input. |

## Подтверждение публикации на future fixture

Первоначальный full-history source не содержал пригодных upcoming матчей. Для
проверки ветки inference/materialization владелец разрешил временный локальный
fixture с одним будущим событием `sf-test-future-20260816` и командами с
суффиксом `_test`. Он не был импортирован в production и не заменяет проверку
на реальном provider snapshot.

| Поле | Фактическое значение |
|---|---|
| Future fixture | 22 219 canonical events; одно synthetic future event |
| Canonical bootstrap artifact | `sha256:0e0c0bc5b3cbb7f15db35a73b1979c3afd05dabd512b3cd79eb2236099cd99f3` |
| Model bundle ID | `sha256:f624e9988e1a170e160f07282c549413d1aad4dcd76cbdeb786c786bd1347ab9` |
| Successful run | `nhl-future-fixture-rerun-20260816T102847Z` |
| UTC start/finish | 2026-08-16 10:28:49–10:30:33 |
| Exit code / elapsed | `0` / 1:44.10 |
| Feature pipeline | 77.99 сек.; 489 features |
| Inference / materialization | 3 242 long rows / 1 621 predictions опубликовано атомарно |
| Operational archive | `sha256:9949f3d8884864dd32a69a143a0cee240a164d353b14b1c9bf4e0fca130cd7da` |

Перед повторным запуском исправлена нормализация пустых score-полей canonical
payload: они больше не переводят будущий матч в `live` status. Регрессионный
тест покрывает этот случай.

## Решение

Full-history rebuild укладывается в scheduler timeout `45m`. Измеренный peak
RAM ≈2.31 GiB требует worker budget не менее 3 GiB; `docker-compose.prod.yml`
уже задаёт `3g`. Локально подтверждены как rebuild, так и атомарная публикация
витрины. До production release остаются external gates: immutable GHCR
digest/provenance и image scans, production DB/S3 access, backup RPO/RTO,
успешный refresh на актуальном provider snapshot и явное разрешение владельца.
Это evidence не заменяет ни один из этих external checks.
