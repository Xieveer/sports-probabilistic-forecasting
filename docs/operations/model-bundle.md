# Immutable model bundle: promotion и rollback

Production model bundle создаётся локально после ручного approval в Model
Registry. Legacy `manifest.json` schema v1 сохраняет immutable ID,
`model_identity`, checksum каждого файла, версию приложения, source commit и
release. В состав не входят training data, secrets или MLflow state.

`build_model_bundle()` создаёт content-addressed каталог. Повторное создание
того же состава не меняет уже существующий bundle. Перед любой активацией
`verify_model_bundle()` продолжает принимать schema v1 и дополнительно проверяет
managed schema v2. V2 фиксирует `model_pool`, `market_spec`, правила ничьей и
овертайма, упорядоченные outcomes, `feature_contract_id`, список признаков с
типами, версию преобразований, алгоритм, относительный `model_entrypoint`,
app version и checksums всех файлов. Все поля manifest, включая checksums,
участвуют в `bundle_id`. Verifier блокирует неизвестный алгоритм, traversal,
дублирующиеся/лишние/повреждённые файлы, несовпадающие outcomes, а также
несогласованные `deploy.yaml` и `features.txt`, если эти совместимые файлы есть.

Для рынка с ничьей контракт требует `home_win / draw / away_win`; без ничьей —
`home_win / away_win`. Правила `draw` и `overtime` указываются явно.
`build_managed_model_bundle()` создаёт schema v2 и возвращает
`VerifiedModelBundle`; прежний `build_model_bundle()` и v1 hash остаются
неизменными для legacy установщика. Проверка выполняется до записи `current` или
`previous` symbolic pointer. V2 builder/verifier — локальный контракт TASK-028-2;
DB activation и выбор managed bundle остаются за TASK-028-3.

## Явная активация

Только локальный release manager с write-доступом к runtime-каталогу выполняет
явную команду promotion:

```bash
uv run python -m sports_forecast.deploy.model_bundle install \
  --bundle /srv/sports-forecast/runtime_models/bundles/sha256:<bundle-id> \
  --runtime-root /srv/sports-forecast/runtime_models \
  --app-version 1.1.13
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
  --app-version 1.1.13
```

При отсутствующем, повреждённом или несовместимом bundle команда завершается с
ошибкой и не изменяет `current`. Интеграция loader в bounded Worker выполняется
в TASK-005-4; этот контракт является его обязательным входом.
