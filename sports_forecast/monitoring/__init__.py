"""Мониторинг деградации модели и data drift.

Компоненты:
    - metrics: Prometheus custom gauges для ML метрик.
    - drift / performance / ab_testing: реализованы и покрыты unit-тестами;
      в production Airflow DAG пока не подключены (см. ``dag_monitoring`` — gates в ``validation.gates``).

"""
