# Недочёты полного цикла обучения (market=winner, uel_kz_1 + lp_ru)

> Документ создан в рамках эпика R12. Сюда записываются все ошибки, предупреждения и неожиданное поведение, обнаруженные при выполнении шагов полного цикла (data pipeline → training → promote → materialize) для турниров **uel_kz_1** (киберхоккей) и **lp_ru** (настольный теннис).

---

## Формат записей

Каждая запись содержит четыре поля: **шаг**, **команда**, **ошибка/предупреждение**, **описание**.

Для каждой проблемы добавлять блок в секцию «Записи» в формате:

```markdown
### [Шаг] Краткое описание (дата или R12.X)

- **Шаг:** название этапа (Data pipeline / Training uel_kz_1 / Training lp_ru / Promote / Materialize)
- **Команда:** точная команда или make-цель
- **Ошибка/предупреждение:** полный текст сообщения (или выдержка из лога)
- **Описание:** что произошло, возможная причина, что сделать дальше
```

---

## Записи

### [Data pipeline] Успешный прогон с предупреждениями (R12.3)

- **Шаг:** Data pipeline
- **Команда:** `make dvc-repro`
- **Ошибка/предупреждение:** Пайплайн выполнен (ingest и clean пропущены — didn't change; стадия features запускалась по всем 7 турнирам). Полный вывод уложился более чем в 15 минут, стадия validate в захваченном логе не отражена. Критических ошибок нет.
- **Описание:** Для прослеживаемости: Data pipeline (make dvc-repro) отработал без падений. Ниже зафиксированы предупреждения, обнаруженные в логе.

---

### [Data pipeline] FutureWarning pandas groupby observed (R12.3)

- **Шаг:** Data pipeline
- **Команда:** `make dvc-repro`
- **Ошибка/предупреждение:**
  ```
  FutureWarning: The default of observed=False is deprecated and will be changed to True in a future version of pandas. Pass observed=False to retain current behavior or observed=True to adopt the future default and silence this warning.
  return df.groupby(group_keys, dropna=False)[metric].transform(
  ```
  Файлы: `sports_forecast/features/generators/ewm_generator.py:380`, `sports_forecast/features/generators/count_generator.py:162`.
- **Описание:** Pandas предупреждает об изменении поведения `groupby` по умолчанию. Рекомендуется явно передавать `observed=True` или `observed=False` в вызовах `groupby(..., dropna=False)` в ewm_generator и count_generator, чтобы убрать предупреждение и зафиксировать поведение.

---

### [Data pipeline] FutureWarning pandera import (R12.3)

- **Шаг:** Data pipeline
- **Команда:** `make dvc-repro`
- **Ошибка/предупреждение:**
  ```
  FutureWarning: Importing pandas-specific classes and functions from the top-level pandera module will be **removed in a future version of pandera**.
  If you're using pandera to validate pandas objects, we highly recommend updating your import:
  # old import: import pandera as pa
  # new import: import pandera.pandas as pa
  ```
  Источник: `pandera/_pandas_deprecated.py:146`.
- **Описание:** Где в коде используется `import pandera as pa` для валидации pandas-объектов, стоит перейти на `import pandera.pandas as pa` (или импорт из `pandera.pandas`) согласно документации Pandera.

---

### [Data pipeline] EWMFeatureGenerator: контексты team/h2h_team пропущены для table_tennis (R12.3)

- **Шаг:** Data pipeline
- **Команда:** `make dvc-repro`
- **Ошибка/предупреждение:**
  ```
  [WARNING] EWMFeatureGenerator: контекст 'team' (span=5) пропущен, отсутствуют колонки: ['pl_cteam']
  [WARNING] EWMFeatureGenerator: контекст 'h2h_team' (span=5) пропущен, отсутствуют колонки: ['pl_cteam', 'opp_cteam']
  ```
  (аналогично для span=25, span=100). Наблюдается для турниров с long-форматом атрибутов `['points', 'sets', 'team']` (настольный теннис: lp_ru, lp_eu и др.), где нет колонки `cteam`/`pl_cteam`.
- **Описание:** Ожидаемое поведение: для спорта table_tennis в long-формате используются атрибуты points/sets/team, а конфиг EWM ожидает контексты с `pl_cteam`/`opp_cteam`. Часть контекстов пропускается, генерируется 80 фичей вместо 92/66 по части контекстов. Для R12 это не ошибка; при желании можно документировать в конфиге фичей или добавить маппинг контекстов под table_tennis.

---

### [Training uel_kz_1] Прогон выполнен успешно (R12.4)

- **Шаг:** Training uel_kz_1
- **Команда:** `make train TOURNAMENT=uel_kz_1 MARKET=winner`
- **Ошибка/предупреждение:** Нет.
- **Описание:** Одиночный прогон обучения (algorithm=catboost, features=basic) завершён успешно. Shadow и Prod модели сохранены в `models/uel_kz_1/winner/catboost_basic/`, модель зарегистрирована в MLflow (uel_kz_1__winner__catboost_basic v3). Test LogLoss 0.6813, AUC 0.5417, ECE 0.0247; калибровка не потребовалась. Ниже зафиксированы предупреждения MLflow из того же прогона.

---

### [Training uel_kz_1] MLflow: deprecated artifact_path (R12.4)

- **Шаг:** Training uel_kz_1
- **Команда:** `make train TOURNAMENT=uel_kz_1 MARKET=winner`
- **Ошибка/предупреждение:**
  ```
  WARNING mlflow.models.model: `artifact_path` is deprecated. Please use `name` instead.
  ```
- **Описание:** MLflow предупреждает об устаревшем параметре при логировании артефактов. Рекомендуется обновить вызовы в коде обучения/логирования моделей: использовать параметр `name` вместо `artifact_path`.

---

### [Training uel_kz_1] MLflow: не удалось определить версию pip (R12.4)

- **Шаг:** Training uel_kz_1
- **Команда:** `make train TOURNAMENT=uel_kz_1 MARKET=winner`
- **Ошибка/предупреждение:**
  ```
  WARNING mlflow.utils.environment: Failed to resolve installed pip version. ``pip`` will be added to conda.yaml environment spec without a version specifier.
  ```
- **Описание:** При сборке conda.yaml для MLflow не удалось определить версию установленного pip; в спецификацию окружения pip попадёт без версии. На результат обучения не влияет; при желании можно зафиксировать версию pip в окружении или обновить MLflow.
