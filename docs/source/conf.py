"""Конфигурация Sphinx для документации Sports Probabilistic Forecasting.

Этот файл содержит настройки для генерации документации проекта.
Для полного списка опций см.:
https://www.sphinx-doc.org/en/master/usage/configuration.html
"""

import sys
from pathlib import Path


# Добавляем корень проекта в путь для импорта модулей
# docs/source/conf.py -> docs/source -> docs -> project_root
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Sports Probabilistic Forecasting"
copyright = "2025, Dmitriy Tkachev"
author = "Dmitriy Tkachev"
release = "0.1.0"
version = "0.1.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",  # Автоматическая документация из docstrings
    "sphinx.ext.napoleon",  # Поддержка Google/NumPy style docstrings
    "sphinx.ext.viewcode",  # Ссылки на исходный код
    "sphinx.ext.intersphinx",  # Ссылки на другую документацию (Python, pandas и т.д.)
    "sphinx.ext.todo",  # Поддержка TODO директив
    "sphinx.ext.coverage",  # Проверка покрытия документацией
]

templates_path: list[str] = ["_templates"]
exclude_patterns: list[str] = []

language = "ru"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path: list[str] = ["_static"]

# Настройки темы Read the Docs
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "includehidden": True,
    "titles_only": False,
}

# -- Extension configuration -------------------------------------------------

# Autodoc settings
autodoc_default_options = {
    "members": True,  # Документировать все члены класса/модуля
    "member-order": "bysource",  # Порядок как в исходном коде
    "special-members": "__init__",  # Включить __init__
    "undoc-members": True,  # Включить недокументированные члены
    "exclude-members": "__weakref__",  # Исключить служебные атрибуты
    "show-inheritance": True,  # Показывать наследование
}

# Автоматически добавлять type hints в документацию
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"

# Napoleon settings (для Google-style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = False
napoleon_type_aliases = None
napoleon_attr_annotations = True

# Todo extension
todo_include_todos = True
todo_emit_warnings = False

# Intersphinx mapping - ссылки на внешнюю документацию
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
}

# Настройки для viewcode
viewcode_follow_imported_members = True

# Настройки для coverage
coverage_show_missing_items = True
