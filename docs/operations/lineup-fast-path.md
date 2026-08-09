# Fast path подтверждённого состава

Локальный adapter принимает только полный confirmed lineup. Он выполняет
single-match inference, затем в одной DB-транзакции сохраняет revision прогноза
и pending outbox. Telegram вызывается отдельным retry worker-ом после commit;
ошибка доставки увеличивает attempts, но не создаёт новую revision и не
пересчитывает прогноз.

Fingerprint события уникален. Повтор того же confirmed состава возвращает
существующую revision и не создаёт второй outbox. Реальный provider составов и
production worker не подключены в TASK-003-5.
