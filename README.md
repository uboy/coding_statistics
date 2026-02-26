## Unified Coding Statistics Toolkit

Centralized framework for gathering and exporting statistics from Git-like services (Gitee, GitCode, GitHub, GitLab, CodeHub family, Gerrit) and Jira.

```
stats_core/
  config.py      # config loader, token onboarding
  cli.py         # 'setup' and 'run' commands
  sources/       # API adapters (gitee, gitcode, github, gitlab, codehub*, gerrit)
  stats/         # collector orchestrating multiple sources (dataset -> reports)
  reports/       # report definitions (unified_review, jira_weekly, jira_comprehensive, jira_weekly_email)
  export/        # Word/Excel/CSV helpers with template support
templates/
  word/          # docx templates
  excel/         # xlsx templates
```

- `stats_main.py` simply calls `stats_core.cli.main`.
- Data flows: `sources` -> `stats.collector` -> `reports` -> `export`.

# Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Generate/verify configuration: `python stats_main.py setup`
   - Copies `configs/config.ini_template` if needed.
   - Default config path: `configs/local/config.ini`.
   - Prompts for tokens if they are missing (GitHub, Gitee, etc.).
3. Fill in relevant sections `[gitee]`, `[gitcode]`, `[github]`, `[gitlab]`, `[codehub]`, `[gerrit]`, `[jira]`, `[reporting]`.
   - For AI weekly email report also configure `[ollama]` and optional defaults in `[jira_weekly_email]`.
   - `repository`/`project` accepts comma-separated list.
   - Branch filter is optional; absence implies “all branches”.

# Running Reports

```
# Unified review report from links (default: report_inputs/input.txt) export to Excel/CSV/Word
python stats_main.py run \
  --report unified_review \
  --output-formats excel word

# Weekly Jira report (--sources jira is optional, defaults to jira for jira_weekly)
python stats_main.py run \
  --report jira_weekly \
  --start 2025-02-01 \
  --end 2025-02-28 \
  --params project=ABC include_empty_weeks=True member_list_file=report_inputs/members.xlsx \
  --output-formats excel word

# Comprehensive Jira report (Excel-only, migrated from legacy jira_ranking_report.py)
python stats_main.py run \
  --report jira_comprehensive \
  --start 2025-02-01 \
  --end 2025-02-28 \
  --params project=ABC member_list_file=report_inputs/members.xlsx code_volume_file=code_volume.xlsx \
  --output-formats excel

# Weekly Jira email report (HTML-only, with optional Ollama text polishing)
python stats_main.py run \
  --report jira_weekly_email \
  --params project=ABC week_date=2026-02-18 labels_highlights=highlights labels_report=report ai_provider=ollama ollama_enabled=true vacation_file=TelmaST_Team_Vacation.xlsx vacation_sheet=Vacations2026

- Для `unified_review` параметры `--start/--end` опциональны. Если их не задавать, будут обработаны все ссылки из `reporting.links_file` (по умолчанию `report_inputs/input.txt`, с fallback на legacy `input.txt`). При указании дат в отчёт попадут только PR/коммиты, замёрженные в указанный период.
- Источник для каждой ссылки определяется автоматически по URL, так что `--sources` задавать не обязательно.
- Для `jira_weekly` параметр `--sources` необязателен, по умолчанию используется `jira`. Если нужны другие источники, их можно указать явно.
- Для `jira_comprehensive` можно передать `--params jql=...` (или `version=...` / `epic=...`) вместо `project+dates`.
- Для `jira_weekly_email` формат `--output-formats` можно не указывать: отчёт всегда генерируется в HTML.
- Для `jira_weekly_email` неделю можно задать через `week_date=YYYY-MM-DD` или `week=WWwYY` / `week=WWwYYYY` / `week=WW`.
- `jira_weekly_email` строит HTML для Outlook, хранит weekly snapshot в том же каталоге, что и HTML (по умолчанию `reports`) с именем `jira_weekly_email_<PROJECT>_<WEEK>.json`, и выводит diff только в консоль.
- Labels для глав настраиваются через `labels_highlights` и `labels_report`.
- Для `labels_report` можно указать `@all`, чтобы отключить label-фильтр и включать эпики/задачи с любыми метками.
- Для Ollama можно задать `ollama_api_key` (CLI param) или `[ollama].api_key` в конфиге.
- Для WebUI можно выбрать `ai_provider=webui` и задать `webui_url`, `webui_endpoint`, `webui_model`, `webui_api_key` (или секцию `[webui]`).
- Для `vacation_file`: абсолютный путь используется как есть, относительный резолвится от parent-каталога проекта.
  Рекомендуемое место файла отпусков: `report_inputs/<vacations>.xlsx` (например, `report_inputs/vacations.xlsx`).
- Для `vacation_horizon_anchor`: `today` (по умолчанию) или `week_start`.
- Заголовки/поля шапки конфигурируются в `[jira_weekly_email]`: `header_project_info_title`, `header_banner_bg_color`, `meta_active_iteration_*`, `meta_report_period_label`, `meta_report_owner_*`, `meta_team_member_*`.
- Дополнительная HTML-строка в конце отчёта задаётся через `footer_html` (вставляется как raw HTML).
- `jira_comprehensive` включает лист `Worklog_Activity` (агрегация времени по задаче и инженеру, только задачи с несколькими авторами).
- `jira_comprehensive` включает лист `Worklog_Entries` (все логи времени за период).
- `jira_comprehensive` включает лист `Comments_Period` (задачи с комментариями в период; колонки `Comments`, `Comments_In_Period`, `AI_Comments`). AI включается через `--params ai_comments_enabled=true`.
- `Assistance_Provided` считается по метке `dev_assistance`.
- Все отчёты выводят прогресс-бар и шаги выполнения.
- AI-запросы при таймаутах повторяются до 3 раз.
- Параллелизм тяжёлых операций управляется через `--params parallel_workers=4`.
```

## Jira Weekly Email Report Structure

The `jira_weekly_email` report produces an Outlook-friendly HTML email with fixed chapter order:

1. **Highlights** — one-line headline per highlighted issue with Jira key in parentheses
2. **Key Results and Achievements** — grouped by Epic, including:
   - report-labeled completed items first
   - other completed task/feature/improvement items
   - high-priority paragraph inside each epic
   - bugs summary paragraph inside each epic
3. **Next Week Plans** — in-progress items grouped by Epic
4. **Vacations (next 60 days)** — parsed from configured Excel sheet

Report ordering is stabilized using previous snapshots; differences vs previous report are printed to console with colored diff formatting.

## Jira Weekly Report Structure

The `jira_weekly` report consists of multiple views:

Worklog-driven attribution: if time is logged on an issue within the selected period, it appears in the weekly report as `Task in progress` for those weeks, even if the issue is still unresolved.

1. **Table View** - Tabular format with columns: Name, Week #, Date, Description, Link, Status
2. **List View** - Tasks grouped by assignee and week, showing weekly progress
3. **Engineer Weekly Activity** - Per engineer weekly breakdown with time logged by that engineer, status/resolution, and comments (including worklog comments) added/updated in the week
4. **Epic Progress** - Resolved tasks grouped by epics, plus Progressed Tasks (issues with worklogs but no resolution during the period) with parent/sub-task hierarchy
5. **Summary** - Epic-level weekly achievements (AI-assisted, 1-2 sentences per resolved planned task/sub-task) with mandatory counters:
   - `Resolved xx planned tasks on time.`
   - `Resolved xx reported issues.` (if bugs were resolved in epic)
6. **Resolved Tasks** - Chronological list of resolved tasks by week

`Summary` AI processing in `jira_weekly` supports the same providers/options as `jira_weekly_email` (`ai_provider=ollama|webui`, plus `[ollama]` / `[webui]` settings).

Each view is generated as a separate section in the Word document. Excel export contains a pivot table grouped by assignee and week.

# Caching

The toolkit includes a two-level caching system to speed up repeated runs:

1. **API-level caching**: All API requests are cached automatically. This reduces redundant calls to Git services when processing the same repositories or links.
2. **Link-level caching**: Results from processing individual links (PRs/commits) are cached, so re-running the same `report_inputs/input.txt` file is much faster.

Cache configuration in `configs/local/config.ini`:
```ini
[cache]
; Enable/disable caching (true/false)
enabled = true
; Path to cache file (JSON format, can be edited manually)
file = data/cache/cache.json
; Time-to-live in days (0 = no expiration)
ttl_days = 0
```

- Cache is stored in JSON format, so you can manually edit `data/cache/cache.json` if needed.
- To clear cache, delete `data/cache/cache.json` or set `enabled = false`.
- Cache is automatically saved after each report run.

# Templates and Export

- Word export supports custom templates (DOCX) via `--params word_template=...`.
- Excel export can reuse templates via `templates/excel/...`.
- Default formatting uses Calibri 8pt for tables; adjust by passing `word_font`, `word_font_size`, `word_table_style`.

# Tests

```
pytest tests
```

- Includes coverage for:
  - Exporters (Word, Excel, CSV)
  - CLI utilities
  - Source adapters (Gitee, GitCode, GitHub, GitLab, CodeHub, Gerrit)
  - Jira weekly report (all test cases: same week closure, multi-week tasks, no tasks, reassigned)
  - Jira weekly email report (week resolver, vacations parser, html/snapshot/diff flow)
  - Unified review report
- Add fixtures under `tests/fixtures/` when extending functionality.

# Building Binaries

Windows:
```
scripts/build/build_stats_tool.cmd
```

Linux/macOS:
```
chmod +x scripts/build/build_stats_tool.sh
./scripts/build/build_stats_tool.sh
```

Outputs `dist/stats_tool` executable (PyInstaller-based) bundling Python + templates.

# Adding New Sources/Reports

- Implement `BaseSource` protocol (see existing gitee/github/gitlab).
- Register new report via `stats_core.reports.registry.register`.
- Reuse `stats_core.export` helpers for consistent formatting.


