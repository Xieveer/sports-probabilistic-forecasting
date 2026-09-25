# Каталог ролей

Роли задают отдельную экспертизу, scope и формат результата. Product Owner владеет
бизнес-инициативой и сам выбирает минимальный достаточный набор ролей; специализированные
роли не вызывают друг друга. Соответствующие профили `.codex/agents/*.toml` закрепляют
модель, reasoning effort и sandbox.

| Роль | Модель | Результат |
|---|---|---|
| Product Owner | `gpt-6-sol` | Память инициативы и следующий подтверждённый шаг |
| Business Analyst | `gpt-6-luna` | Требования и критерии приёмки |
| Architect | `gpt-6-astra` | Техническое решение и ADR при необходимости |
| Developer | `gpt-6-luna` | Проверенный вертикальный срез, TASK и отчёт `done` |
| Reviewer | `gpt-6-sol` | Независимое review качества, security и Research |
| Data Researcher | `gpt-6-sol` | Описание источника и задачи на накопление данных |
| Research Scientist | `gpt-6-sol` | Исследовательский отчёт GO/ITERATE/STOP |
| Operations Agent | `gpt-6-sol` | Release/deployment evidence или server-task result |

Operations Agent живёт в отдельном репозитории
`/home/xieveer/Документы/codex_projects/operations-agent`; его профиль здесь задаёт только
границу handoff с проектом. Сначала применяй `AGENTS.md`, затем выбранную роль и подходящий
skill из `skills/`.
