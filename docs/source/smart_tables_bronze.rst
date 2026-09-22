Полнота Smart Tables bronze
===========================

Для research-пула ``football_top_leagues`` bronze-кэш наблюдается на уровне одного
``match_id``. Профиль ``winner_baseline`` версии 1 требует ``card.json`` и
``stat_all.json``. Файлы ``stat_first.json``, ``stat_second.json``,
``chart_all.json``, ``chart_first.json``, ``chart_second.json`` и ``similar.json``
необязательны: их отсутствие не исключает матч из train dataset.

Отчёт coverage
--------------

После остановки backfill выполните read-only scan (сеть не вызывается и bronze не
изменяется)::

   uv run python scripts/smart_tables_bronze_coverage.py \
     --raw-root data/source/football_top_leagues/raw

В JSON-результате ``train_ready_coverage`` — доля матчей с обоими required-файлами;
``component_coverage`` показывает покрытие каждого файла. Списки
``missing_required_match_ids`` и ``optional_only_match_ids`` — соответственно план
докачки required и только optional частей.

Чтобы сохранить воспроизводимый снимок отдельно от cache, добавьте
``--write-manifest data/source/football_top_leagues/bronze-manifest.json``. Manifest
содержит только metadata файла (наличие, размер, время записи, статус и тип ошибки),
но никогда не response payload. Некорректный JSON или envelope без ``success: true``
считается incomplete.

При opt-in resume outcome сетевой попытки хранится в служебном
``.bronze_attempts.json`` рядом с match-каталогом. Для timeout/HTTP-сбоя manifest
покажет ``failed`` и ``request_failed`` без текста ответа; это отличает его от
``missing`` (компонент ещё не запрашивался).

Targeted resume
---------------

Python boundary ``fetch_match_bronze`` принимает opt-in
``profile=WINNER_BASELINE_PROFILE``. С ``include_optional=False`` он проверяет и
запрашивает только отсутствующие или повреждённые required-компоненты; валидные
``success: true`` файлы повторно не загружает. Default backfill этого параметра не
передаёт и сохраняет прежний набор запросов.

Для массового initial backfill только под winner-baseline используйте opt-in
профиль::

   SF_SMART_TABLES_BRONZE_PROFILE=winner_baseline_required \
   SF_TOURNAMENT_FILTER=football_top_leagues \
   uv run python -m sports_forecast.data.ingest

В этом режиме каждый новый матч скачивает только ``card.json`` и ``stat_all.json``.
Не указывайте ``SF_SMART_TABLES_MAX_MATCHES``, если цель — полный согласованный pool.
Без переменной ``SF_SMART_TABLES_BRONZE_PROFILE`` сохраняется прежнее поведение
``full``: загрузка всех required и optional компонентов.
