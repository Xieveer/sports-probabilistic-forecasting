# Каталог ролей

Роли задают точку зрения, scope и формат результата. Markdown-файлы остаются переносимыми
проектными playbooks, а соответствующие профили `.codex/agents/*.toml` делают их именованными
custom agents в Codex и закрепляют подходящие модель, reasoning effort и sandbox.

| Роль | Результат |
|---|---|
| Product analyst | Подтверждённые требования |
| Architect | Границы, контракты и ADR |
| Test designer | Тестовая стратегия и первый red |
| Implementer | Проверенные вертикальные срезы |
| Reviewer | Findings по качеству и корректности |
| Security reviewer | Findings по достижимым угрозам |
| Documentation writer | Актуальная русская документация |
| DevOps reviewer | CI/Docker/release go-no-go |

Сначала применяй `AGENTS.md`, затем выбранную роль и подходящий skill из `skills/`. Роли не
вызывают другие роли. Композиция описана в `references/orchestration.md`.
