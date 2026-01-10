# ============================
# Управление окружением, качеством кода и запуском пайплайна
# Стек: uv + ruff + pre-commit + pytest + sphinx
# ============================

SRC := sports_forecast
TESTS := tests
DOCS_SOURCE := docs/source
DOCS_BUILD := docs/build

.PHONY: help init install lint format fix test test-unit test-cov test-watch test-file pre-commit train clean dvc-repro
.PHONY: docs docs-serve docs-clean docs-open docs-coverage docs-linkcheck tree

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
	@echo "  make train        - запустить training-пайплайн"
	@echo "  make dvc-repro    - перепроизвести датасет с DVC"
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

# ---------- Основной пайплайн обучения ----------

# Запуск тренировочного скрипта (архитектура v2.0)
train:
	uv run python -m sports_forecast.train \
		tournament=uel_kz_1 \
		market=total \
		market_spec=total_over \
		market_spec.line=6.5 \
		recipe=total_baseline \
		features=basic \
		algorithm=dummy

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
	@-pkill -f "mlflow ui" 2>/dev/null || true
	@sleep 1
	@bash -c "cd $(shell pwd) && nohup uv run mlflow ui --backend-store-uri file:$(shell pwd)/mlruns --host 127.0.0.1 --port 5000 > mlflow_ui.log 2>&1 & echo \$$!" > mlflow_ui.pid
	@sleep 3
	@if pgrep -f "mlflow ui" > /dev/null; then \
		echo "✅ MLflow UI запущен!"; \
		echo "📊 URL: http://127.0.0.1:5000"; \
		echo "📂 Tracking: $(shell pwd)/mlruns"; \
		echo "📝 Логи: mlflow_ui.log"; \
		echo "🆔 PID: $$(cat mlflow_ui.pid)"; \
	else \
		echo "❌ Ошибка запуска MLflow UI"; \
		echo "Логи:"; \
		tail -10 mlflow_ui.log; \
		exit 1; \
	fi

mlflow-stop:  ## Остановить MLflow UI
	@echo "🛑 Остановка MLflow UI..."
	@-pkill -f "mlflow ui" 2>/dev/null && echo "✅ MLflow UI остановлен" || echo "ℹ️  MLflow UI не был запущен"
	@rm -f mlflow_ui.pid

# ---------- Демо доступ ----------
download-demo-data:
	uv run python -m sports_forecast.data.download_demo \
		--url "$(URL)" \
		--tournament "uel" \
		--filename "source.csv"
