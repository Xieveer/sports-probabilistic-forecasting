# TASK-036-4 — Переключаемый strict reader в production runtime

> **Статус:** done — ожидает независимый review и terminal CI
> **Эпик:** [EPIC-036](../EPIC-036-registry-rollout.md)
> **Тип:** исправление дефекта релизного gate
> **Ветка:** `initiative/epic-036-v1-3-3-release`

## Проблема

Тег `v1.3.3` содержит `conf/identity_event.yaml` со значением
`registry_event_reader_enabled: false`. Образы копируют этот файл внутрь,
а production Compose не передаёт способ включить strict reader. Следовательно,
критерий EPIC-026 на сервере недостижим на immutable образах v1.3.3.
Проверка обнаружила это до переключения production; Docker run
`38177105034` отменён после NO-GO.

## Результат и критерии

- Runtime читает явный `SF_REGISTRY_EVENT_READER_ENABLED=true|false`; неверное
  значение завершает чтение ошибкой. При отсутствии переменной действует
  прежний `conf/identity_event.yaml` и значение `false`.
- Production Compose передаёт один и тот же флаг во все процессы, которые
  разрешают события: API, Telegram bot, source-acquirer и Worker. По умолчанию
  флаг выключен, чтобы установить новый образ и snapshot до strict switch.
  На VPS значение явно указано и сверяется в актуальном production Compose
  profile `/etc/sports-forecast/refresh/nhl.env`, используемом всеми четырьмя
  процессами.
- Тесты проверяют обе ветки, неверный ввод и rendered Compose. Сначала
  фиксируется падающий тест, затем минимальная правка и зелёная проверка.
- Production процедура включает switch только после server sync v2 и smoke;
  rollback снова выключает флаг до возврата прежних образов.

## Gate

Независимый review, terminal CI/security, новый source tag `v1.3.4`, exact
image/model evidence и повторный production smoke обязательны. Старый тег
`v1.3.3` не изменять.

## Передача

Developer завершил минимальную правку и передал
[отчёт done](../../changes/done/TASK-036-4-runtime-strict-switch.md)
независимому Reviewer. Его P1 о втором systemd profile исправлен
повторным red/green циклом; re-review не выявил новых P0–P2. Полный unit,
lint, mypy, pre-commit, документация,
AI validation, production-check и offline lock check прошли. Локальный
`make security` не дошёл до audit из-за DNS/PyPI; terminal CI/security
обязателен. Production switch остаётся NO-GO до release gates.
