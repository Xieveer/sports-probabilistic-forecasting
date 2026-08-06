# ============================
# Управление окружением, качеством кода и запуском пайплайна
# Стек: uv + ruff + pre-commit + pytest + sphinx
# ============================

SRC := sports_forecast
TESTS := tests
DOCS_SOURCE := docs/source
DOCS_BUILD := docs/build

.PHONY: help init install lint format fix test test-unit test-cov test-watch test-file pre-commit train train-sweep train-sweep-nhl train-sweep-nhl-ot-winner train-sweep-nhl-ot-total promote clean dvc-repro
.PHONY: docs docs-serve docs-clean docs-open docs-coverage docs-linkcheck tree
.PHONY: api api-dev bot-dev bot-up materialize nhl-morning-refresh-dry-run nhl-morning-refresh nhl-morning-test-notify refresh-lock-status docker-up docker-down docker-build docker-logs db-init
.PHONY: football-catalog-refresh football-backfill football-ingest-debug football-backfill-wc football-rebuild-source
.PHONY: airflow-init airflow-up airflow-down airflow-logs
.PHONY: monitoring-up monitoring-down
.PHONY: ai-validate security production-check check

# ---------- Справка ----------

help:
	@echo "Доступные команды:"
	@echo ""
	@echo "Окружение:"
	@echo "  make init         - первичная настройка: установка зависимостей и pre-commit"
	@echo "  make install      - обновить зависимости через uv"
	@echo ""
	@echo "Качество кода:"
	@echo "  make lint         - запустить ruff (линтер)"
	@echo "  make format       - отформатировать код ruff format"
	@echo "  make fix          - автофиксить все проблемы перед коммитом"
	@echo "  make pre-commit   - прогнать все pre-commit хуки на всех файлах"
	@echo ""
	@echo "Тесты:"
	@echo "  make test         - запустить все тесты"
	@echo "  make test-unit    - запустить только юнит-тесты (быстрые)"
	@echo "  make test-cov     - запустить тесты с coverage отчетом"
	@echo "  make test-watch   - запустить тесты в watch mode"
	@echo ""
	@echo "Документация:"
	@echo "  make docs              - собрать HTML документацию"
	@echo "  make docs-serve        - запустить сервер документации с автообновлением"
	@echo "  make docs-clean        - очистить собранную документацию"
	@echo "  make docs-open         - открыть документацию в браузере"
	@echo "  make docs-coverage     - проверить покрытие кода документацией"
	@echo "  make docs-linkcheck    - проверить битые ссылки в документации"
	@echo "  make tree [DEPTH=3]    - вывести структуру проекта (с указанием глубины)"
	@echo ""
	@echo "Пайплайн:"
	@echo "  make train        - запустить training-пайплайн (одиночный эксперимент)"
	@echo "  make train-sweep  - запустить sweep через Hydra --multirun"
	@echo "  make train-sweep-nhl - NHL baseline (tournament=nhl, catboost+lgbm, advanced)"
	@echo "  make train-sweep-nhl-ot-winner - NHL winner_withOT (R22.8), catboost+lgbm+dummy, advanced"
	@echo "  make train-sweep-nhl-ot-total  - NHL total_over_withOT line=6.5 (R22.8)"
	@echo "  make promote      - сравнить модели и выбрать лучшую для продакшена"
	@echo "  make dvc-repro    - перепроизвести датасет с DVC"
	@echo ""
	@echo "Сервис:"
	@echo "  make api-dev       - запустить FastAPI локально (dev, SQLite)"
	@echo "  make bot-dev       - Telegram-бот (нужны BOT_TOKEN, BOT_ALLOWED_USER_IDS)"
	@echo "  make bot-up        - бот в docker compose (с сервисом api)"
	@echo "  make materialize   - материализовать предсказания в DB (NHL: TOURNAMENT=nhl после promote)"
	@echo "  make nhl-morning-refresh-dry-run - вывести shell-команду утреннего NHL (как DAG nhl_morning_refresh)"
	@echo "  make nhl-morning-refresh       - выполнить полный NHL refresh + validate (без Telegram)"
	@echo "  make nhl-morning-test-notify   - пауза МСК + offset, refresh + validate; TG через post_refresh_digest (R39.8)"
	@echo "  make refresh-lock-status     - диагностика flock на refresh (SF_REFRESH_LOCK_FILE): кто держит файл, см. доки NHL ops"
	@echo ""
	@echo "Football (Smart Tables, R42):"
	@echo "  make football-catalog-refresh  - обновить competition_catalog.json (slug → id)"
	@echo "  make football-backfill         - полный ingest сборных (SF_TOURNAMENT_FILTER=football_nationals)"
	@echo "  make football-backfill-wc      - backfill только WC (env SF_SMART_TABLES_COMPETITION_CODES=WC)"
	@echo "  make football-ingest-debug     - ingest max 3 матча (SF_SMART_TABLES_MAX_MATCHES=3)"
	@echo "  make football-rebuild-source   - пересборка source.csv из bronze (без API)"
	@echo "  make db-init       - инициализировать таблицы DB (SQLite)"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build  - собрать Docker образы"
	@echo "  make docker-up     - запустить все сервисы (API + DB + MLflow)"
	@echo "  make docker-down   - остановить все сервисы"
	@echo "  make docker-logs   - показать логи сервисов"
	@echo ""
	@echo "Airflow:"
	@echo "  make airflow-init  - инициализация Airflow (БД + admin user)"
	@echo "  make airflow-up    - запустить Airflow (webserver + scheduler)"
	@echo "  make airflow-down  - остановить Airflow"
	@echo "  make airflow-logs  - логи Airflow"
	@echo ""
	@echo "Валидация:"
	@echo "  make validate-data - проверить качество данных (Pandera)"
	@echo ""
	@echo "Утилиты:"
	@echo "  make clean        - удалить кеши и временные файлы"
	@echo "  make clean-all    - полная очистка (включая документацию)"

# ---------- Окружение / зависимости ----------

# Первичная инициализация проекта (один раз на машину/окружение)
init: install
	uv run pre-commit install

# Обновление / установка зависимостей из pyproject.toml
install:
	uv sync

# ---------- Качество кода ----------

# Линтер (ruff check)
lint:
	uv run ruff check $(SRC) $(TESTS)

# Форматирование кода (ruff format)
format:
	uv run ruff format $(SRC) $(TESTS)

# Автофикс всех проблем перед коммитом
fix:
	uv run ruff check --fix $(SRC) $(TESTS)
	uv run ruff format $(SRC) $(TESTS)

# Полный прогон всех pre-commit хуков
pre-commit:
	uv run pre-commit run --all-files

ai-validate:
	uv run python scripts/validate_ai_layer.py

security:
	uv export --locked --no-dev --no-emit-project --output-file requirements-audit.txt
	uvx --from pip-audit pip-audit --requirement requirements-audit.txt
	@rm -f requirements-audit.txt

production-check:
	uv run python scripts/validate_production_readiness.py

check: lint test-unit docs ai-validate production-check

# ---------- Тесты ----------

# Юнит-тесты (на будущее, когда появится папка tests/)
# ---------- Тесты ----------

test:
	@echo "🧪 Запуск всех тестов..."
	uv run pytest

test-unit:
	@echo "🧪 Запуск юнит-тестов..."
	uv run pytest -m unit -v

test-cov:
	@echo "🧪 Запуск тестов с coverage..."
	uv run pytest --cov=$(SRC) --cov-report=html --cov-report=term-missing

test-watch:
	@echo "🧪 Запуск тестов в watch mode..."
	uv run pytest-watch

test-file:
	@echo "🧪 Запуск конкретного файла: $(FILE)"
	uv run pytest $(FILE) -v

# ---------- Документация ----------

# Собрать HTML документацию
docs:
	uv run sphinx-build -b html $(DOCS_SOURCE) $(DOCS_BUILD)
	@echo ""
	@echo "✅ Документация собрана: $(DOCS_BUILD)/index.html"
	@echo "Для просмотра запустите: make docs-open"

# Запустить сервер документации с автообновлением (доступно на http://127.0.0.1:8000)
docs-serve:
	@echo "🚀 Запуск сервера документации..."
	@echo "Документация будет доступна на: http://127.0.0.1:8000"
	@echo "Нажмите Ctrl+C для остановки"
	uv run sphinx-autobuild $(DOCS_SOURCE) $(DOCS_BUILD) --open-browser

# Очистить собранную документацию
docs-clean:
	rm -rf $(DOCS_BUILD)
	@echo "🧹 Документация очищена"

# Открыть документацию в браузере (после сборки)
docs-open:
	@if [ -f "$(DOCS_BUILD)/index.html" ]; then \
		echo "🌐 Открываю документацию в браузере..."; \
		xdg-open $(DOCS_BUILD)/index.html 2>/dev/null || open $(DOCS_BUILD)/index.html 2>/dev/null || echo "❌ Откройте вручную: $(DOCS_BUILD)/index.html"; \
	else \
		echo "❌ Документация не собрана. Запустите: make docs"; \
	fi

# Проверить покрытие кода документацией
docs-coverage:
	@echo "📊 Проверка покрытия документацией..."
	uv run sphinx-build -b coverage $(DOCS_SOURCE) $(DOCS_BUILD)/coverage
	@echo ""
	@echo "Отчет сохранен в: $(DOCS_BUILD)/coverage/python.txt"
	@if [ -f "$(DOCS_BUILD)/coverage/python.txt" ]; then \
		cat $(DOCS_BUILD)/coverage/python.txt; \
	fi

# Проверить битые ссылки в документации
docs-linkcheck:
	@echo "🔗 Проверка ссылок в документации..."
	uv run sphinx-build -b linkcheck $(DOCS_SOURCE) $(DOCS_BUILD)/linkcheck
	@echo ""
	@echo "Отчет сохранен в: $(DOCS_BUILD)/linkcheck/output.txt"
	@if [ -f "$(DOCS_BUILD)/linkcheck/output.txt" ]; then \
		echo ""; \
		echo "=== Результаты проверки ссылок ==="; \
		cat $(DOCS_BUILD)/linkcheck/output.txt | grep -E "(broken|redirected)" || echo "✅ Все ссылки работают!"; \
	fi

# ---------- Структура проекта ----------

# Вывести структуру проекта
tree:
	@if command -v tree >/dev/null 2>&1; then \
		tree -L $(or $(DEPTH),3) -I '__pycache__|*.pyc|*.pyo|.pytest_cache|.ruff_cache|*.egg-info|.venv|.git|docs/build'; \
	else \
		echo "❌ Команда 'tree' не найдена. Установите: sudo apt install tree (Linux) или brew install tree (macOS)"; \
	fi

# ---------- Feature Generation ----------

# Генерация фичей basic (быстро, для dev)
features-basic:
	@echo "⚡ Генерация фичей (basic)..."
	uv run python -m sports_forecast.features.features_build --multirun \
		tournament=uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by,nhl \
		features=basic

# Генерация фичей advanced (полный каркас пресета; NHL/streak только для ice_hockey — см. feature_pipeline в conf/sport)
features-advanced:
	@echo "🔬 Генерация фичей (advanced)..."
	uv run python -m sports_forecast.features.features_build --multirun \
		tournament=uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by,nhl \
		features=advanced

# ---------- Основной пайплайн обучения ----------

# Запуск одиночного эксперимента (архитектура v2.0)
train:
	uv run python -m sports_forecast.train \
		tournament=$(or $(TOURNAMENT),uel_kz_1) \
		market=$(or $(MARKET),winner) \
		market_spec=$(or $(SPEC),winner) \
		algorithm=$(or $(ALG),catboost) \
		features=$(or $(FEAT),basic)

# Sweep моделей на одном турнире (winner market)
train-sweep:
	uv run python -m sports_forecast.train --multirun \
		tournament=$(or $(TOURNAMENT),uel_kz_1) \
		market=winner \
		market_spec=winner \
		algorithm=catboost,lgbm,logreg \
		features=basic

# NHL baseline (R22): regulation winner, advanced features, season holdout — см. conf/tournament/nhl.yaml
train-sweep-nhl:
	uv run python -m sports_forecast.train --multirun \
		tournament=nhl \
		market=winner \
		market_spec=winner \
		algorithm=catboost,lgbm \
		features=advanced

# R22.8: full-match labels (pl_goals_full); отдельный MLflow experiment от baseline winner.
# dummy — prior baseline для сравнения log-loss в MLflow (тот же features=advanced в конфиге).
train-sweep-nhl-ot-winner:
	uv run python -m sports_forecast.train --multirun \
		tournament=nhl \
		market=winner_withOT \
		market_spec=winner_withOT \
		algorithm=catboost,lgbm,dummy \
		features=advanced

# R22.8: total over full match; одна линия 6.5 (другие линии — через market_spec.line=...).
train-sweep-nhl-ot-total:
	uv run python -m sports_forecast.train --multirun \
		tournament=nhl \
		market=total_withOT \
		market_spec=total_over_withOT \
		market_spec.line=6.5 \
		algorithm=catboost,lgbm \
		features=advanced

# Sweep: все модели × все фичи
train-sweep-full:
	uv run python -m sports_forecast.train --multirun \
		tournament=$(or $(TOURNAMENT),uel_kz_1) \
		market=winner \
		market_spec=winner \
		algorithm=catboost,lgbm,logreg \
		features=basic,advanced

# NHL baseline: см. train-sweep-nhl (tournament=nhl, MLflow experiment nhl__winner)
nhl-train-baseline: train-sweep-nhl

# Выбор лучшей модели (compare)
promote:
	@echo "🏆 Сравнение моделей..."
	uv run python main.py promote compare \
		--experiment $(or $(EXP),uel_kz_1__winner) \
		--metric $(or $(METRIC),test_logloss) \
		--direction $(or $(DIR),minimize) \
		--top-n $(or $(TOP),5)

# ---------- Уборка мусора ----------

# Очистка кешей и временных файлов
clean:
	@echo "🧹 Очистка временных файлов..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Временные файлы удалены"

# Полная очистка (включая документацию)
clean-all: clean docs-clean
	@echo "✅ Полная очистка завершена"

# ---------- DVC репозиторий ----------

# Перепроизвести датасет с DVC
dvc-repro:
	@echo "🔄 Запуск DVC pipeline..."
	uv run dvc repro
	@echo "✅ DVC pipeline завершен"

# ---------- MLflow UI ----------
mlflow-ui:  ## Запустить MLflow UI на порту 5000
	@echo "🚀 Запуск MLflow UI..."
	@-pkill -f "mlflow.server" 2>/dev/null || true
	@-pkill -f "mlflow ui" 2>/dev/null || true
	@-fuser -k 5000/tcp 2>/dev/null || true
	@sleep 2
	@bash -c "cd $(shell pwd) && nohup uv run mlflow ui --backend-store-uri sqlite:///$(shell pwd)/mlflow.db --default-artifact-root file://$(shell pwd)/mlruns --host 127.0.0.1 --port 5000 > mlflow_ui.log 2>&1 & echo \$$!" > mlflow_ui.pid
	@echo "⏳ Ожидание запуска MLflow UI..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		sleep 1; \
		if curl -sf http://127.0.0.1:5000/ > /dev/null 2>&1; then \
			echo "✅ MLflow UI запущен! ($$i сек)"; \
			echo "📊 URL: http://127.0.0.1:5000"; \
			echo "📂 Backend: sqlite:///$(shell pwd)/mlflow.db"; \
			echo "📁 Artifacts: $(shell pwd)/mlruns"; \
			echo "📝 Логи: mlflow_ui.log"; \
			echo "🆔 PID: $$(cat mlflow_ui.pid)"; \
			exit 0; \
		fi; \
	done; \
	echo "❌ Ошибка запуска MLflow UI (таймаут 10 сек)"; \
	echo "Логи:"; \
	tail -20 mlflow_ui.log; \
	exit 1

mlflow-stop:  ## Остановить MLflow UI
	@echo "🛑 Остановка MLflow UI..."
	@-pkill -f "mlflow.server" 2>/dev/null || true
	@-pkill -f "mlflow ui" 2>/dev/null || true
	@-fuser -k 5000/tcp 2>/dev/null || true
	@rm -f mlflow_ui.pid
	@echo "✅ MLflow UI остановлен"

# ---------- Service (FastAPI / Prediction Store) ----------

# Запустить FastAPI локально (dev mode, SQLite)
api-dev:
	@echo "🚀 Запуск FastAPI (dev mode)..."
	uv run uvicorn sports_forecast.service.app:app \
		--host 127.0.0.1 --port 8000 --reload

# Telegram-бот (локально; задайте BOT_TOKEN и BOT_ALLOWED_USER_IDS)
bot-dev:
	uv run python -m sports_forecast.bot

# Бот + API через compose (нужен BOT_TOKEN; профиль bot)
bot-up:
	docker compose --profile bot up -d api telegram-bot

# Инициализация БД (создание таблиц)
db-init:
	@echo "🗄️  Инициализация Prediction Store..."
	uv run python -c "from sports_forecast.service.db.engine import init_db; init_db(); print('✅ Таблицы созданы')"

# Материализация предсказаний (NHL promoted: TOURNAMENT=nhl MARKET=winner SPEC=winner)
materialize:
	@echo "🔮 Материализация предсказаний..."
	uv run python -m sports_forecast.materialize \
		tournament=$(or $(TOURNAMENT),uel_kz_1) \
		market=$(or $(MARKET),winner) \
		market_spec=$(or $(SPEC),winner) \
		algorithm=$(or $(ALG),catboost) \
		features=$(or $(FEAT),basic)

# Сухой просмотр команды ежедневного утреннего NHL (12:00 MSK ≈ DAG Airflow 09:00 UTC; см. docs/source/nhl_local_operations.rst)
nhl-morning-refresh-dry-run:
	uv run python -m sports_forecast.orchestration.cron_refresh \
		--tournaments nhl \
		--features advanced \
		--market winner_withOT \
		--market-spec winner_withOT \
		--dry-run

# Полный утренний NHL refresh (как DAG без --dry-run), затем validate — вручную; для TG см. nhl-morning-test-notify
nhl-morning-refresh:
	uv run python -m sports_forecast.orchestration.cron_refresh \
		--tournaments nhl \
		--features advanced \
		--market winner_withOT \
		--market-spec winner_withOT
	uv run python -m sports_forecast.validation.run_validation

# Тест: пауза МСК + offset; refresh → validate → python -m sports_forecast.orchestration.post_refresh_digest (legacy: scripts/run_nhl_refresh_notify.py, R39.8)
nhl-morning-test-notify:
	uv run python scripts/run_nhl_refresh_notify.py

# ---------- Football Smart Tables (R42) ----------

football-catalog-refresh:
	uv run python scripts/refresh_smart_tables_catalog.py

football-backfill:
	mkdir -p data/source/football_nationals
	SF_TOURNAMENT_FILTER=football_nationals uv run python -m sports_forecast.data.ingest

football-backfill-wc:
	mkdir -p data/source/football_nationals
	SF_SMART_TABLES_COMPETITION_CODES=WC SF_TOURNAMENT_FILTER=football_nationals \
		uv run python -m sports_forecast.data.ingest

football-ingest-debug:
	mkdir -p data/source/football_nationals
	SF_SMART_TABLES_MAX_MATCHES=3 SF_TOURNAMENT_FILTER=football_nationals \
		uv run python -m sports_forecast.data.ingest

football-rebuild-source:
	uv run python scripts/rebuild_football_source_from_bronze.py

# Диагностика эксклюзивной блокировки refresh (flock на SF_REFRESH_LOCK_FILE, см. cron_refresh / Airflow Variables)
refresh-lock-status:
	@LOCK="$${SF_REFRESH_LOCK_FILE:-/tmp/sf_refresh_pipeline.lock}"; \
	echo "SF refresh flock — lock file: $$LOCK"; \
	echo ""; \
	if command -v fuser >/dev/null 2>&1; then \
		echo "--- fuser (PIDs держащих файл; может быть пусто, см. ps ниже) ---"; \
		(fuser -v "$$LOCK" 2>&1) || echo "(нет процессов по fuser — lock свободен или инструмент не видит держателя)"; \
	else \
		echo "(fuser не найден — пакет psmisc; или lsof см. ниже)"; \
	fi; \
	echo ""; \
	if command -v lsof >/dev/null 2>&1; then \
		echo "--- lsof ---"; \
		(lsof "$$LOCK" 2>&1) || echo "(lsof: ничего)"; \
		echo ""; \
	fi; \
	echo "--- возможные процессы refresh/flock (ищите STAT=T после Ctrl+Z) ---"; \
	ps -eo pid,tty,stat,cmd 2>/dev/null | grep -v 'SF_REFRESH_LOCK_FILE:-/tmp/sf_refresh_pipeline.lock' | grep -E 'run_nhl_refresh_notify\.py|\\bflock[[:space:]]+-w[[:space:]]|-m sports_forecast\.orchestration\.cron_refresh' | grep -v '[g]rep -E' || true; \
	echo ""; \
	echo "Освобождение: завершите PID держателя lock (обычно shell с flock), например: kill -9 <pid>"; \
	echo "Подробнее: docs/source/nhl_local_operations.rst (Troubleshooting flock / Ctrl+Z)."; \
	wait_seconds="$${SF_REFRESH_LOCK_WAIT_SECONDS:-300}"; \
	echo "(Ожидание lock новым запуском: SF_REFRESH_LOCK_WAIT_SECONDS=$${wait_seconds})"

# ---------- Docker ----------

# Собрать Docker образы
docker-build:
	@echo "🐳 Сборка Docker образов..."
	docker compose build

# Запустить все сервисы (API + DB + MLflow + Monitoring)
docker-up:
	@echo "🐳 Запуск сервисов..."
	docker compose up -d
	@echo ""
	@echo "✅ Сервисы запущены:"
	@echo "   API:        http://localhost:8000"
	@echo "   MLflow:     http://localhost:5000"
	@echo "   Prometheus: http://localhost:9090"
	@echo "   Grafana:    http://localhost:3000 (admin/admin)"
	@echo "   DB:         postgresql://localhost:5432/sports_forecast"

# Остановить все сервисы
docker-down:
	@echo "🛑 Остановка сервисов..."
	docker compose down

# Показать логи
docker-logs:
	docker compose logs -f --tail=50

# Запустить worker для материализации (через Docker)
docker-materialize:
	docker compose run --rm worker uv run python -m sports_forecast.materialize \
		tournament=$(or $(TOURNAMENT),uel_kz_1) \
		market=$(or $(MARKET),winner) \
		market_spec=$(or $(SPEC),winner) \
		algorithm=$(or $(ALG),catboost) \
		features=$(or $(FEAT),basic)

# ---------- Airflow ----------

# Инициализация Airflow (создание БД, admin user)
airflow-init:
	@echo "✈️  Инициализация Airflow..."
	docker compose -f docker-compose.yml -f airflow/docker-compose.airflow.yml \
		--profile init run --rm airflow-init

# Запустить Airflow (webserver + scheduler)
airflow-up:
	@echo "✈️  Запуск Airflow..."
	docker compose -f docker-compose.yml -f airflow/docker-compose.airflow.yml up -d
	@echo ""
	@echo "✅ Airflow запущен:"
	@echo "   Web UI:  http://localhost:8080"
	@echo "   Login:   admin / admin"

# Остановить Airflow
airflow-down:
	@echo "✈️  Остановка Airflow..."
	docker compose -f docker-compose.yml -f airflow/docker-compose.airflow.yml down

# Логи Airflow
airflow-logs:
	docker compose -f docker-compose.yml -f airflow/docker-compose.airflow.yml \
		logs -f --tail=50 airflow-webserver airflow-scheduler

# ---------- Валидация данных ----------

# Проверка качества данных (Pandera)
validate-data:
	@echo "🔍 Валидация данных..."
	uv run python -m sports_forecast.validation.run_validation

# ---------- Демо доступ ----------
download-demo-data:
	uv run python -m sports_forecast.data.download_demo \
		--url "$(URL)" \
		--tournament "uel" \
		--filename "source.csv"
