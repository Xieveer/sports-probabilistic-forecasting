# Model registry: promotion и rollback

Для legacy deployment `ModelRegistryRepository.promote()` сохраняет v1 путь.
Managed deployment активируется только через
`sports_forecast.deploy.managed_model.activate_managed_model()`: до смены pointer
проверяются v2 manifest, checksums, пара, feature contract, app version и фактическая
загрузка entrypoint. В одной транзакции сохраняются `bundle_id` и путь внутри
разрешённого bundle root. Вызов требует уже одобренный immutable bundle и ссылку
на candidate report; создание модели или отчёта указатель не меняет.

У пары `model_pool/market_spec` может быть не более одной active deployment.
DB constraint запрещает active managed запись без bundle binding. Старые строки
после migration `0022_managed_model_pointer` остаются `is_managed=false` без
придуманного bundle ID; их нужно явно bind-ить перед managed serving.

Worker и canonical refresh для managed deployment разрешают DB pointer на
bundle и передают материализатору один pinned contract. Значение
`runtime_root/current` для такого запуска не читается. Legacy deployment
сохраняет явный v1 путь. Перед DB publication materializer блокирует active
deployment и сравнивает её identity и bundle с pin; если указатель изменился,
текущая витрина остаётся прежней.

Rollback выполняется явным вызовом `rollback(model_pool, market_spec,
model_identity)`. Он переключает pointer на уже сохранённую версию и не удаляет
ни запись registry, ни файлы артефакта. Перед rollback следует проверить
`candidate_report_ref` и `artifact_ref` выбранной версии.

Для исторического NHL используется
`conf/legacy/nhl-model-manifest.yaml`. `load_legacy_manifest()` читает его
только при существующем локальном артефакте и запрещает небезопасные пути; он не
запускает переобучение и не меняет pointer. Значения `legacy-unpinned` означают,
что для прежнего артефакта полные refs недоступны: до ручного promotion это
остаточный риск, а не допустимая новая production версия.

Immutable bundle собирается и проверяется через [model-bundle.md](model-bundle.md).
Production pointer EPIC-028 этим TASK не менялся.
