# NHL: единый slug турнира `nhl` (R38)

## Решение

Канонический идентификатор турнира для данных, пайплайна, моделей, API и Telegram — **`nhl`**.

Исторический Hydra-групп `tournament=nhl_train` больше не задаёт отдельное `name`: файл `conf/tournament/nhl_train.yaml` только подключает `nhl` (deprecated-алиас). Новые команды и расписание используют **`nhl`**.

## Миграция уже развёрнутого окружения

### 1. Каталоги моделей

Promoted-артефакты ожидаются в **`models/nhl/<market_spec>/…`** (как в `materialize` и `deploy.yaml`).

Если модели лежат только под `models/nhl_train/`:

```bash
# Пример: перенос дерева (проверьте market_spec и алгоритм в пути)
mv models/nhl_train models/nhl
# или симлинк на переходный период:
# mv models/nhl_train models/nhl_train.bak && ln -s nhl_train.bak models/nhl
```

После переноса обновите пути в документации promote / `deploy.yaml` внутри `best/`.

### 2. База предсказаний (Prediction Store)

Старые строки могли иметь `tournament = 'nhl_train'`. Для единообразия в API и боте:

```sql
-- PostgreSQL / SQLite: один раз после бэкапа
UPDATE predictions SET tournament = 'nhl' WHERE tournament = 'nhl_train';
```

### 3. MLflow

Исторические эксперименты с префиксом `nhl_train__` **не переименовываются**. Новые прогоны дают имена вида `nhl__winner_withOT__…`.

### 4. Источник данных

Один конфиг: **`conf/source/nhl.yaml`**, каталог **`data/source/nhl/`**. Файл `conf/source/nhl_train.yaml` удалён.

## Операционная одна команда

- Утро + validate + (опционально) TG: `make nhl-morning-test-notify` или DAG `nhl_morning_refresh` с `SF_NHL_MORNING_TOURNAMENT=nhl` (дефолт в коде — `nhl`).
- Полный refresh без TG: `make nhl-morning-refresh`.

## Связанные файлы

- `conf/tournament/nhl.yaml` — `train_eval_split` и комментарии для обучения OT.
- `conf/tournament/nhl_train.yaml` — только `defaults: [nhl]` (deprecated).
- `docs/cursor/refactor/done_task/R38.md` — итог эпика и критерии.
