# Dev tooling: uv, тесты, качество кода, pre-commit

Практический шаблон инфраструктуры разработки из **Sports Probabilistic Forecasting** — для переноса в другой Python-проект. Здесь не ML/DVC/Airflow, только стек разработки.

---

## Общая схема

```
pyproject.toml + uv.lock     ← зависимости и lockfile
        ↓
make init                    ← uv sync + pre-commit install
        ↓
разработка → make fix        ← ruff check --fix + format
        ↓
git commit                   ← pre-commit хуки (автофикс + проверки)
        ↓
GitHub CI                    ← lint + test-unit на PR/push в main
```

**Стек качества:** `uv` → `ruff` (lint + format) → `pre-commit` → `mypy` → `pytest` → GitHub Actions.

---

## 1. uv — окружение и зависимости

### Принципы

- Один источник правды: `pyproject.toml`
- Воспроизводимость: `uv.lock` в git
- Prod-зависимости в `[project.dependencies]`, dev — в `[dependency-groups] dev`
- Все команды через `uv run …` (не активировать venv вручную)
- Docker: `uv sync --frozen --no-dev`

### Минимальный `pyproject.toml`

```toml
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    # runtime deps
]

[dependency-groups]
dev = [
    "pre-commit>=4.5.0",
    "pytest>=9.0.1",
    "pytest-cov>=4.0.0",
    "ruff>=0.14.8",
]
```

### Bootstrap в новом проекте

```bash
# установить uv: https://docs.astral.sh/uv/getting-started/installation/
uv init                    # или вручную создать pyproject.toml
uv add <runtime-packages>
uv add --group dev pre-commit pytest pytest-cov ruff
uv lock
```

### Makefile (ядро)

```makefile
SRC := my_package
TESTS := tests

init: install
	uv run pre-commit install

install:
	uv sync

lint:
	uv run ruff check $(SRC) $(TESTS)

format:
	uv run ruff format $(SRC) $(TESTS)

fix:
	uv run ruff check --fix $(SRC) $(TESTS)
	uv run ruff format $(SRC) $(TESTS)

pre-commit:
	uv run pre-commit run --all-files

test:
	uv run pytest

test-unit:
	uv run pytest -m unit -v

test-cov:
	uv run pytest --cov=$(SRC) --cov-report=html --cov-report=term-missing
```

### Docker

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
CMD ["uv", "run", "uvicorn", "my_package.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `.gitignore`

```
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
```

---

## 2. Чистота кода — ruff

Конфиг в отдельном `ruff.toml` (можно и в `pyproject.toml` под `[tool.ruff]`).

### Что включено

| Категория | Правила | Зачем |
|-----------|---------|-------|
| Базовые | E, F, W | синтаксис, неиспользуемые импорты |
| Качество | B (bugbear), SIM, RET | типичные баги, упрощение |
| Стиль | I (isort), N (naming) | импорты, PEP8-имена |
| Современный Python | UP (pyupgrade) | `list[str]` вместо `List[str]` |
| pathlib | PTH | `Path` вместо `os.path` |

Параметры: `line-length = 100`, `target-version = "py312"`.

### Per-file ignores (паттерн)

```toml
[lint.per-file-ignores]
"__init__.py" = ["F401"]
"tests/**/*.py" = ["ARG", "N803", "N806"]
```

### isort

```toml
[lint.isort]
known-first-party = ["my_package"]
lines-after-imports = 2
```

### Пример полного `ruff.toml` (из этого репозитория)

```toml
line-length = 100
target-version = "py312"

[lint]
select = [
    "E", "F", "W",
    "B",
    "I",
    "N",
    "UP",
    "C4",
    "SIM",
    "RET",
    "ARG",
    "PTH",
]

ignore = [
    "E203",
    "E501",
]

[lint.per-file-ignores]
"__init__.py" = ["F401"]
"tests/**/*.py" = ["ARG", "N803", "N806"]

[lint.isort]
known-first-party = ["sports_forecast"]
force-single-line = false
lines-after-imports = 2

[format]
quote-style = "double"
indent-style = "space"
```

---

## 3. Pre-commit — хуки перед коммитом

Здесь **не** автоматический `git commit` при каждом сохранении, а **хуки перед коммитом**: автофикс + блокировка плохого кода.

### Установка

```bash
make init   # uv sync + pre-commit install
```

### Хуки (`.pre-commit-config.yaml`)

1. **ruff** с `--fix` — автоисправление
2. **ruff-format** — форматирование
3. **pre-commit-hooks:** EOF, trailing whitespace, large files (1 MB), YAML/TOML, merge conflicts, `breakpoint()` / `pdb`
4. **mypy** — мягкий режим (`--ignore-missing-imports`), с `types-*` stubs

### Рабочий цикл

```bash
make fix              # перед коммитом вручную
git add .
git commit -m "..."   # pre-commit снова прогонит хуки
make pre-commit       # полный прогон по всем файлам (как в CI локально)
```

Если хук что-то поправил — `git add` снова и повторить `git commit`.

### Cursor reviewer (опционально)

В `.cursor/agents/reviewer.md`: после успешного ревью агент **пушит коммит** и обновляет бэклог. Это workflow для Cursor, не git hook.

---

## 4. Тесты — pytest

### `pytest.ini`

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    --verbose
    --strict-markers
    --tb=short
    --disable-warnings
    -ra
minversion = 7.0

markers =
    unit: Unit tests (быстрые, изолированные)
    integration: Integration tests
    slow: Медленные тесты
    requires_data: Требуют реальных данных
    requires_model: Требуют обученной модели
    orchestration: Контур оркестрации (Makefile/CLI/DAG smoke)
```

### Автомаркер `unit` в `tests/conftest.py`

Все тесты без явных маркеров `integration`, `slow`, `requires_data` и т.д. получают `unit`. CI гоняет только их:

```python
"""Pytest hooks: default ``unit`` marker for tests without slow/integration scope."""

from __future__ import annotations

import pytest

_NON_UNIT_MARKERS = frozenset(
    {"integration", "orchestration", "slow", "requires_data", "requires_model"},
)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Attach ``unit`` to tests that are not explicitly slow or integration-scoped."""
    for item in items:
        names = {m.name for m in item.iter_markers()}
        if names & _NON_UNIT_MARKERS:
            continue
        item.add_marker(pytest.mark.unit)
```

### Структура

```
tests/
├── conftest.py
├── test_*.py              # unit (по умолчанию)
└── integration/
    └── test_*.py          # @pytest.mark.integration
```

### Стиль тестов

- `from __future__ import annotations`
- type hints на fixtures и тестах
- docstring модуля — что покрывается
- `@pytest.fixture` для данных
- тяжёлые тесты — явные маркеры

### Команды

| Команда | Назначение |
|---------|------------|
| `make test` | все тесты |
| `make test-unit` | только unit (CI) |
| `make test-cov` | HTML + terminal coverage |
| `make test-file FILE=tests/test_foo.py` | один файл |

---

## 5. CI — GitHub Actions

`.github/workflows/ci.yml`:

- триггер: `pull_request` + `push` в `main`
- `concurrency` с `cancel-in-progress: true`
- матрица Python: **3.10** и **3.12**
- `astral-sh/setup-uv@v5` с кешем
- `uv python install` → `uv sync --frozen --group dev`
- `make lint` + `make test-unit`

Пример workflow:

```yaml
name: CI

on:
  pull_request:
  push:
    branches:
      - main

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  lint-test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          cache-suffix: ${{ matrix.python-version }}

      - name: Install Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}

      - name: Sync dependencies (incl. dev)
        run: uv sync --frozen --python ${{ matrix.python-version }} --group dev

      - name: Lint
        run: make lint

      - name: Unit tests
        run: make test-unit
```

Локально перед push:

```bash
make lint && make test-unit
```

---

## 6. Чеклист для нового проекта

```bash
# 1. Структура
mkdir -p my_package tests
touch pyproject.toml ruff.toml pytest.ini .pre-commit-config.yaml Makefile

# 2. Зависимости
uv sync
make init

# 3. CI
mkdir -p .github/workflows
# скопировать ci.yml, подставить имя пакета в Makefile

# 4. Первый тест
# tests/test_smoke.py с assert True или простой функцией

# 5. Проверка
make fix && make test-unit && make pre-commit
```

### Файлы для копирования (адаптировать имена пакета)

| Файл | Роль |
|------|------|
| `pyproject.toml` | зависимости, `[dependency-groups] dev` |
| `uv.lock` | после `uv lock` |
| `Makefile` | `init`, `install`, `lint`, `format`, `fix`, `test*` |
| `ruff.toml` | правила линтера |
| `.pre-commit-config.yaml` | хуки |
| `pytest.ini` | маркеры и опции |
| `tests/conftest.py` | автомаркер `unit` |
| `.github/workflows/ci.yml` | CI |
| `.gitignore` | `.venv`, кеши |

---

## Ограничения и возможные улучшения

**Почему так:** uv быстрее pip/poetry, ruff заменяет black+isort+flake8, pre-commit ловит проблемы до CI, маркер `unit` даёт быстрый CI без отключения тяжёлых тестов локально.

**Альтернативы:**

- Poetry вместо uv — проще для некоторых, медленнее
- только ruff без pre-commit — меньше защиты (YAML, merge conflicts)
- mypy в CI вместо pre-commit — строже, но медленнее каждый коммит

**Слабые места шаблона:**

- mypy мягкий (`ignore-missing-imports`) — не ловит все типовые ошибки
- `pytest-watch` в Makefile есть, в dev-зависимостях нет
- нет порога coverage в CI
- ruff-конфиг в отдельном файле, не в `pyproject.toml`

**Улучшения позже:** coverage gate в CI, `[tool.uv] default-groups = ["dev"]`, Renovate для версий pre-commit, `nox`/`tox` для матрицы локально.

---

## Ссылки на файлы в этом репозитории

| Файл | Путь |
|------|------|
| Зависимости | `pyproject.toml`, `uv.lock` |
| Makefile | `Makefile` |
| Ruff | `ruff.toml` |
| Pre-commit | `.pre-commit-config.yaml` |
| Pytest | `pytest.ini`, `tests/conftest.py` |
| CI | `.github/workflows/ci.yml` |
| Docker + uv | `Dockerfile` |
