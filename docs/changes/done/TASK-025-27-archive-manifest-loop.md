# TASK-025-27 — Исправление цикла синхронизации archive manifest

> **Состояние:** исправление, независимый review и ограниченный локальный
> wrapper завершены; source tag, release evidence и production rollout ожидают.

## Причина

`while read` читал NUL-разделённый список manifest из stdin-файла. Первый
`docker compose run` наследовал этот же stdin и мог потребить оставшиеся записи,
из-за чего из трёх ожидаемых архивов синхронизировался только один. Отдельно
helper трактовал недоступный путь к каталогу как его отсутствие и возвращал
успешный пустой список. Для NHL такой пустой список после успешного Worker
маскировал отсутствие публикации архивов.

## Изменения

- Runner перенаправляет stdin каждого `archive-sync` Compose run из manifest
  цикла в `/dev/null`, оставляя вход цикла привязанным к NUL-списку.
- После успешного Worker runner отклоняет нулевой `artifact_count` с ненулевым
  кодом выхода. После claim EXIT handler передаёт terminal transition
  host recovery; она должна подтвердить остановку executor перед фиксацией
  неуспешного результата.
- Helper проверяет, что переданный archive root существует и доступен для
  чтения/прохода. Отсутствующий `operational-archive` внутри доступного root
  по-прежнему возвращает пустой список.
- Регрессионный тест исполняет фактическое тело цикла с Compose mock, который
  полностью читает stdin, и требует три sync-вызова для трёх manifest.

## Проверки

Red: до исправлений фактически запущены `test_inaccessible_archive_root_is_not_treated_as_an_empty_archive`
и `test_archive_manifest_loop_keeps_compose_from_consuming_the_manifest_stream`;
оба упали: первый получил `returncode=0` для недоступного root, второй не нашёл
изоляцию stdin в команде Compose. Впоследствии runtime-проверка использовала
фактическое тело цикла и mock Compose, полностью читающий stdin; она требует три
вызова на трёх manifest и теперь проходит.

Green: адресный набор прошёл:

```text
systemd-run --user --scope --quiet -p MemoryMax=768M -p MemorySwapMax=0 timeout 30s \
  /home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/.venv/bin/pytest -q \
  tests/test_archive_manifest_enumeration.py tests/test_data_cycle_runner_contract.py
17 passed in 0.29s
```

Набор был ограничен cgroup 768 MiB, swap 0 и timeout 30 секунд. Полный pytest
не запускался. Независимый Reviewer подтвердил отсутствие P0–P2 замечаний,
включая исправление неточной формулировки в документации.

Ограниченный локальный wrapper с исправленным shell `f2fdfa8` завершился
`Result=success/exit0` для run
`64cc3e85-944e-4c0b-afcb-b46e3d9dfc11`. Data Cycle получил ожидаемый
`partial_success` при выключенных odds; `archive_sync` завершился
`success/artifacts=2`. В новом пустом archive root созданы canonical и NHL
source-state manifest; оба получили `remote-verified` и локальные записи
`status=verified`. Общий cgroup имел лимит 6 GiB, swap 0; его исторический
пик, включающий предыдущие попытки, равен около 3.65 GiB. В этом прогоне
прирост `oom=0`, `oom_kill=0`, контейнеров с OOMKilled нет. Прогон использовал
опубликованные образы/модель v1.2.9 и локальную замену UID на 1000 для доступа
host shell к архивам. Это production-like проверка нового shell, но не exact
runtime identity и не проверка ещё не выпущенных образов v1.2.10.

Первый подготовительный запуск этого fixture остановлен до Worker: ошибочный
`SF_CANONICAL_SOURCE_ROOT` указывал на родительский каталог, поэтому
source-acquirer увидел пустой `source.csv` и начал исторический scan. После
исправления bind read-only probe подтвердил полный файл 181 472 859 байт и
`last_finished=2026-06-15`; второй запуск перешёл в incremental с
`date_from=2026-06-12`. В обоих запусках превышения памяти не было.

## Границы и риски

Изменены только systemd runner/helper, их адресные тесты и документы TASK/done.
Формат архивов, source-state, БД и production данные не менялись. Production
не затрагивался. Проверка наличия manifest теперь обязательна после успешного
Worker, поэтому ошибочно пустой каталог завершит цикл неуспешно и потребует
обычного восстановления/повторного запуска.
