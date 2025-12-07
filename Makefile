# ============================
# Управление окружением, качеством кода и запуском пайплайна
# Стек: uv + ruff + pre-commit + pytest
# ============================

SRC := sports_forecast
TESTS := tests

.PHONY: help init install lint format fix test pre-commit train clean dvc-repro

# ---------- Справка ----------

help:
	@echo "Доступные команды:"
	@echo "  make init         - первичная настройка: установка зависимостей и pre-commit"
	@echo "  make install      - обновить зависимости через uv"
	@echo "  make lint         - запустить ruff (линтер)"
	@echo "  make format       - отформатировать код ruff format"
	@echo "  make fix         - автофиксить все проблемы перед коммитом"
	@echo "  make test         - запустить pytest"
	@echo "  make pre-commit   - прогнать все pre-commit хуки на всех файлах"
	@echo "  make train        - запустить training-пайплайн (python -m sports_forecast.train)"
	@echo "  make clean        - удалить кеши и временные файлы"
	@echo "  make dvc-repro     - перепроизвести датасет с DVC"

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
test:
	uv run pytest

# ---------- Основной пайплайн обучения ----------

# Запуск тренировочного скрипта
train:
	uv run python -m sports_forecast.train

# ---------- Уборка мусора ----------

clean:
	find . -name "__pycache__" -exec rm -rf {} +
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete

# ---------- DVC репозиторий ----------
dvc-repro:
	uv run dvc repro
