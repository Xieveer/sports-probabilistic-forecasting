# ADR-030 — Выбранный bundle и неизменяемая версия прогноза

> **Статус:** proposed
> **Дата:** 2026-10-10
> **Связанное требование:** [REQ-028](../../product/requirements/REQ-028-production-model-contract.md)
> **Инициатива:** [EPIC-028](../../backlog/EPIC-028-production-model-contract.md)

## Контекст и критерии выбора

Worker проверяет `runtime_root/current`, но materialize независимо читает
`ModelRegistryRepository.get_active()`. Manifest v1 фиксирует `model_identity`,
checksum и app version, но не модельный пул, market outcomes и feature contract.
`deploy.yaml` задаёт алгоритм; ModelFactory уже умеет загружать разные алгоритмы.
PredictionRepository перезаписывает текущий прогноз и его provenance.

Нужен один выбор модели для `model_pool / market_spec`, проверяемая связь выбора
с загружаемыми байтами и сохранение опубликованных вероятностей после rollback.
Первый контур — `nhl / winner_withOT`, CatBoost и LightGBM последовательно.
Критерии: отсутствие нового сервиса, атомарная публикация, проверяемый rollback,
совместимость legacy NHL, минимальная миграция и отсутствие алгоритмических
ветвей в Worker/API. ADR необходим: выбор источника истины и схема истории
меняют устойчивые контракты нескольких компонентов.

## Рассмотренные варианты

| Вариант | Простота, тестируемость и стоимость | Безопасность, эксплуатация и обратимость |
| --- | --- | --- |
| Status quo: два pointer + проверка совпадения | Малый guard легко проверить; пригоден как первый защитный срез. Не даёт атомарной активации между БД и ФС, не сохраняет историю. | При частичном переключении публикация блокируется; требуется ручное согласование. Прост в откате, недостаточен для полного REQ. |
| Файловый pointer на пару, registry как каталог | Сохраняет installer, позволяет проверять полностью файловый выбор. Потребует убрать смысл `is_active`, ввести layout пар и отдельную защиту от смены pointer во время DB publish. | Нет общей транзакции с витриной; нужен дополнительный lock-протокол. Переносим на одиночный хост, восстановление требует согласованного filesystem backup. |
| DB registry pointer на пару + immutable локальный bundle (выбран) | Использует существующие БД, repository и модельные пулы. Нужны аддитивная миграция, ограничения и общий resolver; проверяется DB integration tests. | Проверка актуальности выбора и публикация входят в одну DB-транзакцию; runtime уже зависит от БД. Артефакты подготавливаются до активации. Legacy можно оставить в явном режиме до миграции. |

Историю также можно хранить в JSONL рядом с parquet, но запись файла и витрины
не образует общей транзакции и усложняет стабильные ссылки. Выбрана дополнительная
таблица в существующей БД. Отдельный registry service, очередь или scheduler
не нужны для одного владельца и ручной активации.

## Решение

### Выбор и активация

Для managed-пары единственный production pointer — активная запись существующего
`model_deployments`. Она однозначно связывает `model_identity` с проверенным
`bundle_id` и immutable artifact location. Новый bundle для той же identity
не перезаписывает прежнюю связь: требуется новая deployment identity.
У пары не более одной активной записи; это обеспечивается DB constraint/index,
а не только предварительным запросом. Активная managed-запись без bundle запрещена.
Существующие записи мигрируются без придуманного bundle_id и требуют явного bind
перед включением нового managed resolver.

Installer сначала размещает и полностью проверяет candidate в разрешённом
локальном bundle root. Проверяются checksum, manifest, совместимость runtime,
пара, outcomes, признаки и возможность загрузки. Только затем ручная активация
переключает DB pointer одной транзакцией. При ошибке предыдущая запись сохраняется.
Путь из registry должен разрешаться внутри bundle root; произвольный URI/код
из manifest не исполняется. Загружаются только доверенные одобренные артефакты:
checksum сам по себе не является авторизацией pickle или другой сериализации.

Worker один раз получает pinned contract: deployment identity, bundle_id,
разрешённый immutable путь, market и feature contract. Для managed-пары
файловый `current` не участвует в выборе и не служит fallback. До DB publish
тот же deployment повторно проверяется под блокировкой активной записи;
promotion/rollback используют совместимый протокол блокировки. Если выбор
изменился во время inference, результат не публикуется, следующий run повторяет
расчёт. Проверка и publish находятся в одной короткой транзакции; блокировку
не держат на время ML inference. PostgreSQL concurrency test обязателен;
SQLite unit-тест не доказывает межпроцессную атомарность PostgreSQL.

### Bundle и алгоритмы

Manifest v2 добавляет `model_pool`, `market_spec`, явные правила рынка/outcomes,
`feature_contract_id`, ссылку на проверяемое описание признаков (порядок, типы,
версия преобразований), algorithm и точный относительный model entrypoint.
Все эти поля участвуют в content hash. `deploy.yaml` и `features.txt`, если
сохраняются для совместимости, проверяются на согласованность с manifest.
Runtime feature contract сравнивается с ожидаемым bundle contract; нельзя
подменить его ID из текущей Hydra-конфигурации. Отсутствующая фича, неизвестный
алгоритм, неправильные outcomes или неоднозначный model file блокируют publish.

Загрузка остаётся через ModelFactory и текущие адаптеры CatBoost/LightGBM.
Hydra задаёт исполняемый профиль; manifest выбирает разрешённый алгоритм и
entrypoint. Неизвестный алгоритм не получает fallback на `cfg.algorithm`.
Winner_withOT явно включает овертайм и два исхода `home_win / away_win`;
проверка finite, диапазона и суммы вероятностей выполняется до публикации.
Контракт не распространяет бинарную агрегацию на рынки с ничьей.

### Неизменяемый прогноз

Добавить `prediction_revisions`: стабильный `revision_id`, ключ события
(включая tournament и source namespace либо достоверный canonical event ID),
market/spec и outcomes, model_pool, bundle_id, model_identity,
feature_contract_id, calculation timestamp UTC, полный набор вероятностей,
run ID и доступный input snapshot reference. История записывается append-only
через repository; изменение и удаление revision не являются API операции.

Новая revision и обновление `predictions.current_revision_id` с текущими
значениями записываются одной транзакцией в `publish_showcase`. API/бот
продолжают читать витрину. Повтор того же run/event/market использует ту же
revision; несовпадение payload по тому же ключу вызывает ошибку. Новый run
создаёт новую версию, даже если вероятности совпали. Ключ витрины обязательно
включает tournament: нынешний upsert по match_id/market/spec недостаточен.
Ошибки, пустая витрина и stale-метки не меняют сохранённые revisions.
Старые строки без доказанного bundle сохраняют nullable revision reference;
история не восстанавливается догадками. Очистка runtime данных не удаляет revisions.

EPIC-027 владеет immutable odds observation ID и as-of selection. EPIC-028
владеет revision ID. Связь с odds добавляется отдельно как nullable reference
после согласования типов, namespace события, правил времени и Alembic head;
при отсутствии наблюдения прогноз остаётся валидным. Позднее найденные odds
не переписывают revision: связь оформляется отдельной записью. Не использовать
`odds_raw` как доказательство исторического observation ID.

### Legacy и rollback

Сохранить manifest v1 verifier и существующий файловый installer/rollback
для явно выбранного legacy-профиля без model_pool. Managed-профиль никогда
не переходит в legacy из-за ошибки resolver. Это временная совместимость двух
профилей, а не два источника выбора внутри одного запуска.

Одобренный NHL payload проверяется на совместимом runtime; его точный контракт
признаков/outcomes устанавливается по артефакту. При переносе в managed bundle
создаётся новый manifest без изменения исходных байтов; ссылка на исходный
артефакт сохраняется, неизвестная training provenance остаётся неизвестной.
Недостающий payload нельзя заменить переобученной моделью в evidence legacy gate.

Managed rollback — явная активация ранее одобренной deployment identity после
повторной проверки bundle и runtime. Revisions и файлы не удаляются. Если
app version несовместима, нужен согласованный откат приложения согласно
[ADR-018](ADR-018-cross-version-model-bundle-recovery.md). Production-переключение
в EPIC-028 не выполняется; новый профиль проверяется на изолированном контуре.

## Последствия

- Положительные: identity соответствует загруженным байтам; история и актуальная
  выдача согласованы; несколько пар поддерживаются общей схемой без нового сервиса.
- Цена: аддитивные миграции registry/revisions, manifest v2, общий resolver и
  concurrency tests. Бэкап БД и bundle archive должны покрывать все referenced bundles.
- Риски: старые callers promotion могут обходить verification; их нужно перевести
  на общий activation contract. Все production entrypoints materialize, включая
  refresh и Worker, должны проходить одинаковый resolver. Прямой вызов не обходит gate.
- Неизвестное: наличие одобренного NHL payload и его точный feature contract;
  схема odds observations EPIC-027 ещё не закреплена. Эти gates блокируют
  соответствующие последующие задачи, но не первый защитный срез.

## Проверка и пересмотр

Первый срез — [TASK-028-1](../../backlog/tasks/TASK-028-1-bundle-registry-guard.md).
Далее Product Owner выделяет задачи: manifest/resolver/activation; DB revisions;
интеграционный сценарий CatBoost → LightGBM → rollback и legacy payload evidence.
Первый guard сам по себе не закрывает REQ-028.

Проверить mismatch identity, повреждение, неверный runtime/рынок/features,
конкурентную активацию, rollback, повтор run и сбой между revision и витриной.
Два настоящих алгоритма должны пройти один путь до DB, а старые revisions
должны читаться по ID. Заглушки допустимы для unit-тестов, но не заменяют этот gate.
Сигнал пересмотра: несколько runtime хостов с разными доступными bundle или
потребность в независимой активации application versions. Тогда уточнить
адресацию и доставку, сохранив DB pointer и immutable IDs, если это возможно.

## Источники и неизвестное

- Внутренний код: `sports_forecast/deploy/model_bundle.py`, `worker.py`,
  `materialize.py`, `predict.py`, `service/db/models.py`, `service/db/repository.py`.
- Существующие проверки: `tests/test_model_bundle.py`, `tests/test_materialize.py`,
  `tests/test_prediction_publication.py`. Они не доказывают новый контракт.
- [SQLAlchemy 2.0: transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html):
  граница Session transaction объединяет DB changes с commit/rollback;
  она не объединяет переключение filesystem symlink с DB commit.
- [ADR-003](ADR-003-configured-multisport-portfolio.md),
  [ADR-005](ADR-005-production-serving-boundary.md): сохраняются каталог портфеля,
  ручное approval, immutable bundles и существующая serving topology.
