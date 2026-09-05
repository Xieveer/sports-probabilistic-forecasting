# Immutable model bundle: promotion и rollback

Production model bundle создаётся локально после ручного approval в Model
Registry. Bundle содержит только файлы модели и `manifest.json`: immutable ID,
`model_identity`, checksum каждого файла, версию приложения, source commit и
release. В состав не входят training data, secrets или MLflow state.

`build_model_bundle()` создаёт content-addressed каталог. Повторное создание
того же состава не меняет уже существующий bundle. Перед любой активацией
`verify_model_bundle()` проверяет manifest, identity, compatibility и checksum.
Проверка выполняется до записи `current` или `previous` symbolic pointer.

## Явная активация

Только локальный release manager с write-доступом к runtime-каталогу выполняет
явную команду promotion:

```bash
uv run python -m sports_forecast.deploy.model_bundle install \
  --bundle /srv/sports-forecast/runtime_models/bundles/sha256:<bundle-id> \
  --runtime-root /srv/sports-forecast/runtime_models \
  --app-version 1.1.6
```

Команда не обучает модель и не получает artifact из MLflow/DVC. VPS Worker/API
пользуются только `load_current_model_bundle()` и при checksum или compatibility
mismatch завершаются до inference и записи predictions. Read-only доступ VPS к
approved bundles остаётся обязательным согласно ADR-005. Production Worker
получает exact host root только как `${SF_MODEL_RUNTIME_ROOT}:/app/models:ro`;
`/app/models` внутри контейнера не меняется. Первый install не обязан создавать
`previous`.

## Откат

После успешной следующей promotion прежний `current` становится `previous`.
Откат проверяет `previous` и переключает pointer без обучения и удаления
артефактов:

```bash
uv run python -m sports_forecast.deploy.model_bundle rollback \
  --runtime-root /srv/sports-forecast/runtime_models \
  --app-version 1.1.6
```

При отсутствующем, повреждённом или несовместимом bundle команда завершается с
ошибкой и не изменяет `current`. Интеграция loader в bounded Worker выполняется
в TASK-005-4; этот контракт является его обязательным входом.
