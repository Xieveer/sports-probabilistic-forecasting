# TASK-025-27 — Исправление цикла синхронизации archive manifest

> **Состояние:** реализация готова; независимый review и новый production-like
> wrapper остаются release gates.

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
не запускался. Новая версия production-like wrapper после исправления ещё не
запускалась; независимый review ожидается.

## Границы и риски

Изменены только systemd runner/helper, их адресные тесты и документы TASK/done.
Формат архивов, source-state, БД и production данные не менялись. Production
не затрагивался. Проверка наличия manifest теперь обязательна после успешного
Worker, поэтому ошибочно пустой каталог завершит цикл неуспешно и потребует
обычного восстановления/повторного запуска.
