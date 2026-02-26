# Feature Design Specification: Agent Knowledge Base

## 1) Summary
Проблема: ИИ-агентам тяжело быстро понять контекст проекта и точки расширения.
Цель: создать единый knowledge base документ для ИИ-агентов с кратким, структурированным обзором проекта, потоков данных, отчётов, параметров CLI, ключевых модулей и правил изменений.
Не цели: автоматическая генерация, изменение кода, обновление зависимостей.

## 2) Scope Boundaries
In scope:
- Новый документ в docs/agents/ с кратким, поддерживаемым описанием проекта.
- Ссылки на ключевые файлы и модули, минимальные примеры CLI.
- Раздел "Как обновлять knowledge base".

Out of scope:
- Изменение бизнес-логики, отчётов, CLI.
- Автогенерация из кода.
- Новые зависимости.

## 3) Assumptions + Constraints
- Репозиторий coding_statistics, Python CLI.
- Политика: минимальные диффы, без новых зависимостей.
- Никаких секретов/токенов в документации.
- Основные источники: README.md, stats_core/*, docs/*.

## 4) Architecture
Компоненты:
- docs/agents/knowledge-base.md: основной документ.
- docs/agents/AGENTS.md: правила работы агентов.
- README.md: существующий обзор, на который будут ссылки.

Поток данных: нет (статическая документация).

## 5) Interfaces / Contracts
Публичный интерфейс: файл docs/agents/knowledge-base.md.

Предлагаемая структура документа (добавить конкретику):
- Overview (что делает проект, 3-5 предложений)
- Repo map (ключевые каталоги + 1 строка ответственности)
- Core data flow (sources -> stats -> reports -> export, 1 диаграмма в ASCII)
- Reports catalog:
  - jira_weekly: назначение, входы, выходы, ключевые params
  - jira_comprehensive: назначение, входы, выходы, ключевые params
  - jira_weekly_email: назначение, входы, выходы, ключевые params
  - unified_review: назначение, входы, выходы, ключевые params
- CLI recipes:
  - setup и run (минимальные примеры)
  - паттерн передачи --params
- Config essentials:
  - секции configs/local/config.ini
  - обязательные ключи для jira и report
  - cache и где хранится
- Output formats:
  - Word/Excel/HTML: где лежат, как называются
  - templates/word, templates/excel
- Extension points:
  - как добавить новый report (registry.register)
  - как добавить source (BaseSource)
- Common pitfalls:
  - пустые отчёты (неверный period)
  - jql/resolution filter
  - отсутствие members.xlsx
- Operational constraints (no secrets, no deps without approval)
- Update checklist (when to refresh KB)

## 6) Data Model Changes
Нет.

## 7) Edge Cases + Failure Modes
- Документ устаревает при появлении новых отчётов или параметров CLI.
- Несоответствие README/KB.

## 8) Security Requirements
- Не включать токены, креды, URL с ключами.
- Не логировать секреты в примерах.
- Соблюдать запрет на новые зависимости без согласования.

## 9) Performance Requirements
Н/П (статический документ).

## 10) Observability
Н/П.

## 11) Test Plan
- Док-изменение. Автотесты не требуются.
- При необходимости: pytest tests (регрессия проекта).

## 12) Rollout + Rollback
Rollout:
- Добавить файл docs/agents/knowledge-base.md.
- (Опционально) добавить ссылку в docs/index.md.

Rollback:
- Удалить новый файл и ссылку.

## 13) Acceptance Criteria
- Файл docs/agents/knowledge-base.md создан.
- Документ включает разделы из пункта 5 с конкретными примерами CLI и params.
- Нет секретов/кредов.
- Ссылки на ключевые модули корректны.
- Ясная инструкция, когда обновлять KB.

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
