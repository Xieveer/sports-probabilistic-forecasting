# Model registry: promotion и rollback

`ModelRegistryRepository.promote()` — единственное действие, меняющее active
production pointer пары `model_pool/market_spec`. Оно требует immutable
`model_identity`, ссылку на отчёт кандидата и ссылку на артефакт. Обучение и
создание candidate report указатель не меняют.

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

Immutable deployment bundle, его checksum и установка на runtime-хост
реализуются отдельно в TASK-005-3.
