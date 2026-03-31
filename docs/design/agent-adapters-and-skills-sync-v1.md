# Синхронизация repo-адаптеров и agent skills с глобальной базой v1

## 1. Summary

### Проблема

В репозитории накопился локальный слой agent-адаптеров и workflow skills, который уже расходится с текущей глобальной базой у пользователя:

- `.codex/config.toml` закрепляет устаревший режим `approval_policy = "on-request"`;
- `.claude/settings.local.json` хранится в git, хотя по смыслу это локальный override;
- thin adapters есть только для Codex и Claude;
- repo-local skills `developer` и `reviewer` частично отстают от текущих глобальных правил;
- AGENTS-ссылка ожидает `policy/task-routing-matrix.json` и `policy/team-lead-orchestrator.md`, но этих файлов в репозитории нет.

Из-за этого проект ведёт себя как смесь старых repo-правил и новых глобальных правил, а агентские runtime-файлы попадают в версионирование.

### Цели

- Привести repo-local adapter/config/skill слой к текущей глобальной базе без дублирования всего домашнего policy-дерева.
- Сохранить repo-specific инструкции по проекту, но явно сделать их надстройкой над глобальными правилами.
- Убрать из git локальные runtime-артефакты агентов и локальные настройки.
- Закрыть минимальные bootstrap-дыры, из-за которых текущий workflow ссылается на отсутствующие файлы.

### Не-цели

- Не менять продуктовую логику отчётов или CLI.
- Не переписывать весь глобальный policy stack внутрь репозитория.
- Не добавлять новые зависимости.
- Не вводить новый сложный multi-agent фреймворк поверх уже существующего процесса.

## 2. Scope Boundaries

### In scope

- `.codex/AGENTS.md`
- `.claude/CLAUDE.md`
- `.codex/config.toml`
- `.codex/skills/architect/SKILL.md`
- `.codex/skills/developer/SKILL.md`
- `.codex/skills/reviewer/SKILL.md`
- `docs/agents/AGENTS.md`
- `docs/agents/shared-guidelines.md`
- `.gitignore`
- `.claude/settings.local.json` как кандидат на de-track/local-only
- `.agent-memory/**`, `.scratchpad/**`, `coordination/tasks.jsonl`, `coordination/state/**`, `coordination/reviews/**` как candidate local-only runtime paths
- `policy/task-routing-matrix.json`
- `policy/team-lead-orchestrator.md`
- при необходимости новые thin adapters: `CURSOR.md`, `GEMINI.md`, `OPENCODE.md`

### Out of scope

- Домашние глобальные файлы вне репозитория (`%USERPROFILE%\\AGENTS.md`, `%USERPROFILE%\\.codex-94o\\config.toml` и т.д.)
- Логика Python-отчётов в `stats_core/**`
- Полное восстановление всех policy/scripts, упомянутых глобальной базой, если они не нужны для bootstrap этого репо
- Любые git history rewrite-операции

## 3. Assumptions + Constraints

- Глобальная база пользователя уже является актуальной и остаётся главным источником общих правил.
- Репозиторию нужен собственный локальный слой только для project-specific контекста, lifecycle и кратких adapter entrypoints.
- Текущие `architect` / `developer` / `reviewer` skills полезны для этого проекта и должны остаться, но без конфликтов с глобальными правилами.
- Локальные runtime-артефакты агентов не должны быть delivery-артефактами репозитория.
- Новые bootstrap-файлы должны быть минимальными и понятными, без разрастания policy-дерева на десятки документов в один заход.
- Изменения должны оставаться кросс-системными по intent: одинаковая базовая логика для Codex, Claude, Cursor, Gemini и OpenCode.

## 4. Architecture

### 4.1 Целевой управляющий слой

Целевая цепочка должна выглядеть так:

1. System-specific thin adapter
2. Global baseline rules
3. Repo-specific agent guide
4. Repo-local workflow skill
5. Local-only runtime files

Это означает:

- thin adapter не дублирует политику;
- глобальные правила дают baseline по routing, safety и output contract;
- `docs/agents/AGENTS.md` содержит только знания о проекте и локальном workflow;
- repo-local skills описывают локальные стадии `architect -> developer -> reviewer`, но не подменяют глобальные правила;
- `.agent-memory`, `.scratchpad`, `coordination/*`, `.claude/settings.local.json` остаются локальными служебными файлами.

### 4.2 Ответственность файлов

- `.codex/AGENTS.md`, `.claude/CLAUDE.md`, `CURSOR.md`, `GEMINI.md`, `OPENCODE.md`
  - только тонкий входной слой для соответствующей системы;
  - содержат ссылки на глобальную базу и на repo-specific guide.
- `docs/agents/AGENTS.md`
  - repo-specific правила проекта;
  - список команд, карта проекта, локальный lifecycle и документационный контракт;
  - не объявляет себя единственным canonical source поверх глобального baseline.
- `.codex/config.toml`
  - только те repo-local overrides, которые действительно должны жить в репозитории;
  - не закрепляет устаревшие permission defaults и не дублирует быстро меняющиеся глобальные настройки без причины.
- `.codex/skills/*`
  - описывают локальные workflow-стадии;
  - отсылают к глобальному baseline, а не конфликтуют с ним.
- `policy/task-routing-matrix.json`
  - минимальная routing-матрица с топ-уровневыми профилями и размерами задач для repo bootstrap.
- `policy/team-lead-orchestrator.md`
  - короткий протокол для top-level orchestrator в контексте этого репозитория.

### 4.3 Поток управления

При старте агент должен получать инструкции в таком порядке:

1. Системный адаптер указывает, что нужно сначала следовать глобальной базе.
2. После глобальной базы подключается `docs/agents/AGENTS.md` как repo addendum.
3. Если задача требует локального workflow, используется соответствующий repo skill.
4. Любые runtime-записи состояния уходят в локальные ignore-paths и не попадают в git diff проекта.

## 5. Interfaces / Contracts

### 5.1 Thin adapters

Контракт для всех thin adapters:

- 3-6 строк, без копирования больших policy blocks;
- обязательно указывать глобальную базу;
- обязательно указывать repo-specific addendum;
- не хранить system-specific business rules в самом adapter-файле.

Ожидаемая структура:

```md
# <System> Entrypoint

Use the global baseline instructions from:
- `%USERPROFILE%\\AGENTS.md`

Use repo-specific additions from:
- `docs/agents/AGENTS.md`
```

### 5.2 Repo guide

Контракт для `docs/agents/AGENTS.md`:

- явно помечен как repo-specific addendum;
- хранит только project map, команды, локальный workflow и doc-sync expectations;
- при необходимости ссылается на `docs/agents/shared-guidelines.md` как на короткий общий конспект, но не подменяет им глобальную базу.

### 5.3 `.codex/config.toml`

Контракт:

- убрать legacy-блоки, которые противоречат текущей глобальной конфигурации;
- если файл остаётся, он должен содержать только необходимые repo-local overrides;
- предпочтительно не закреплять здесь model/version/reasoning, если проект не зависит от них функционально;
- устаревший `approval_policy = "on-request"` должен исчезнуть.

Предпочтительное направление:

- либо минимальный синхронизированный файл с безопасными repo-local defaults;
- либо ещё более тонкий вариант, который почти полностью наследует глобальные defaults.

### 5.4 Repo-local workflow skills

Контракт:

- каждый skill явно работает поверх глобального baseline;
- `architect` остаётся design-first skill и не выполняет кодовые изменения;
- `developer` больше не требует commit message безусловно, а следует актуальному commit-output gate;
- `reviewer` явно фиксирует, что review идёт отдельной стадией и уважает текущие verification/security gates;
- skills остаются минимальными и project-specific.

### 5.5 Local-only settings and runtime artifacts

Контракт:

- `.claude/settings.local.json` не должен быть tracked;
- `.agent-memory/**` не должен быть tracked;
- `.scratchpad/**` не должен быть tracked;
- `coordination/tasks.jsonl`, `coordination/state/**`, `coordination/reviews/**` не должны быть tracked;
- `reports/**` остаётся локальной output-зоной по умолчанию;
- если позднее понадобятся tracked templates в `coordination/`, они должны жить отдельно, например в `coordination/templates/`, без смешивания с runtime-содержимым.

### 5.6 Error handling strategy

- Если локальный optional файл типа `.claude/settings.local.json` отсутствует, это не должно блокировать работу.
- Если отсутствует critical bootstrap-файл из текущего repo contract (`policy/task-routing-matrix.json` или `policy/team-lead-orchestrator.md`), это считается repo drift и должно быть устранено в этой задаче.
- Если глобальная база в будущем снова изменится, repo-local слой должен требовать минимального diff за счёт thin-adapter модели и минимизации overrides.

## 6. Data Model Changes + Migrations

Продуктовых data model changes нет.

Есть только migration для git-tracking:

1. Добавить ignore-правила для local-only agent/runtime paths.
2. Убрать из index уже tracked runtime-файлы без удаления локального содержимого.
3. Проверить, что tracked остаются только намеренно репозиторные adapter/doc/skill файлы.

Ожидаемые de-track targets:

- `.claude/settings.local.json`
- `.agent-memory/**`
- `.scratchpad/**`
- `coordination/tasks.jsonl`
- `coordination/state/**`
- `coordination/reviews/**`
- при согласованном решении - `reports/**`

## 7. Edge Cases + Failure Modes

- Репозиторий обновили только для Codex/Claude, но забыли про Cursor/Gemini/OpenCode:
  - результатом будет частичная синхронизация и повторное расхождение по системам.
- `.gitignore` обновлён, но уже tracked runtime-файлы не сняты из index:
  - пользователь продолжит видеть мусор в git status.
- `.codex/config.toml` синхронизирован слишком агрессивно и закрепит новые глобальные значения, которые снова быстро устареют:
  - нужно держать только действительно repo-local overrides.
- В `docs/agents/AGENTS.md` останется формулировка, будто он сам является единственным canonical source:
  - это сохранит конфликт с глобальной моделью.
- Будут добавлены bootstrap policy-файлы, но без явного ограничения scope:
  - репо начнёт бесконтрольно дублировать всю домашнюю policy-структуру.

## 8. Security Requirements

- Никаких секретов, токенов или пользовательских credential-путей в tracked adapter/config/skill файлах.
- Repo-local skills и docs не должны поощрять:
  - sandbox escalation без явного разрешения пользователя,
  - destructive git-команды,
  - silent writes вне repo scope.
- `.claude/settings.local.json`, если остаётся локальным файлом, не должен использоваться как общий носитель командных allowlist для всей команды.
- Игнорируемые runtime-пути не должны маскировать реальные tracked policy/docs файлы.
- Новые зависимости не добавляются.

## 9. Performance Requirements + Limits

- Изменения не должны влиять на runtime отчётов.
- Agent bootstrap должен стать проще: меньше конфликтующих источников, меньше лишних tracked runtime-файлов.
- Поддержка должна стать дешевле: следующий drift должен исправляться малыми diff за счёт thin adapters и минимальных overrides.

## 10. Observability

- Repo-specific guide должен явно описывать, какие файлы являются tracked policy/docs, а какие - локальные runtime artifacts.
- После изменения достаточно иметь простой ручной audit checklist:
  - какой файл задаёт baseline,
  - какие thin adapters есть,
  - какие runtime paths игнорируются,
  - какие bootstrap policy-файлы в repo действительно обязательны.
- Отдельные метрики или логи не требуются.

## 11. Test Plan

Поскольку функциональная Python-логика не меняется, основной verification здесь файловый и конфигурационный.

Минимальный набор:

- `git diff --check`
- `python -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('.codex/config.toml').read_text(encoding='utf-8'))"` если `.codex/config.toml` остаётся
- `python -c "import json, pathlib; json.loads(pathlib.Path('policy/task-routing-matrix.json').read_text(encoding='utf-8'))"` если файл добавляется
- `git check-ignore -v .claude/settings.local.json .agent-memory/index.jsonl .scratchpad/research.md coordination/state/codex.md`
- `git ls-files .claude/settings.local.json .agent-memory .scratchpad coordination reports`

Дополнительно:

- Если будут изменены repo-local skill файлы, провести manual review их текста на конфликты с актуальными commit-output/approval/security gates.
- Если в репозитории не появятся `scripts/validate-skills.*` и `scripts/security-review-gate.*`, это нужно явно отметить как ограничение verification, а не притворяться, что gate отработал.

## 12. Rollout Plan + Rollback Plan

### Rollout

1. Синхронизировать thin adapters и при необходимости добавить недостающие системные adapters.
2. Привести `.codex/config.toml` к минимальному актуальному виду.
3. Обновить repo-local skills.
4. Обновить repo guide и shared guidelines.
5. Добавить missing bootstrap policy files.
6. Обновить `.gitignore` и снять runtime-файлы из git index.
7. Прогнать file-level verification.

### Rollback

- Rollback делается обычным обратным diff по repo-файлам.
- Для de-track runtime-файлов rollback означает повторное добавление их в index, если это вообще понадобится.
- Локальное содержимое `.agent-memory`, `.scratchpad`, `coordination/*` при de-track не должно теряться, потому что задача ограничивается git tracking, а не удалением файлов.

## 13. Acceptance Criteria Checklist

- [ ] `.codex/config.toml` больше не закрепляет устаревший `approval_policy = "on-request"` и не содержит конфликтующего legacy workflow блока.
- [ ] Repo thin adapters выровнены по одной модели и не дублируют большие policy blocks.
- [ ] Для поддерживаемых систем есть одинаково тонкий adapter-слой, либо явно задокументировано, почему какой-то system adapter отсутствует.
- [ ] `docs/agents/AGENTS.md` явно объявлен repo-specific addendum, а не единственный источник глобальных правил.
- [ ] Repo-local skills `architect`, `developer`, `reviewer` не конфликтуют с текущими commit-output, approval и security gates.
- [ ] `policy/task-routing-matrix.json` и `policy/team-lead-orchestrator.md` присутствуют и достаточны для bootstrap repo workflow.
- [ ] `.claude/settings.local.json` и agent runtime paths выведены из tracked-состояния и покрыты ignore-правилами.
- [ ] Изменения не вводят новых зависимостей и не затрагивают продуктовую логику отчётов.
- [ ] Verification-команды из этой спецификации выполнены или ограничения явно задокументированы.

## Approval

APPROVED:v1

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
