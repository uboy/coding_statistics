## Unified Coding Statistics Toolkit

Centralized framework for gathering and exporting statistics from Git-like services (Gitee, GitCode, GitHub, GitLab, CodeHub family, Gerrit) and Jira.

```
stats_core/
  config.py      # config loader, token onboarding
  cli.py         # 'setup' and 'run' commands
  sources/       # API adapters (gitee, gitcode, github, gitlab, codehub*, gerrit)
  stats/         # collector orchestrating multiple sources (dataset -> reports)
  reports/       # report definitions (unified_review, jira_weekly, jira_comprehensive)
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
   - Copies `config.ini_template` if needed.
   - Prompts for tokens if they are missing (GitHub, Gitee, etc.).
3. Fill in relevant sections `[gitee]`, `[gitcode]`, `[github]`, `[gitlab]`, `[codehub]`, `[gerrit]`, `[jira]`, `[reporting]`.
   - `repository`/`project` accepts comma-separated list.
   - Branch filter is optional; absence implies “all branches”.

# Running Reports

```
# Unified review report from links (input.txt) export to Excel/CSV/Word
python stats_main.py run \
  --report unified_review \
  --output-formats excel word

# Weekly Jira report (--sources jira is optional, defaults to jira for jira_weekly)
python stats_main.py run \
  --report jira_weekly \
  --start 2025-02-01 \
  --end 2025-02-28 \
  --params project=ABC include_empty_weeks=True member_list_file=members.xlsx \
  --output-formats excel word

# Comprehensive Jira report (Excel-only, migrated from legacy jira_ranking_report.py)
python stats_main.py run \
  --report jira_comprehensive \
  --start 2025-02-01 \
  --end 2025-02-28 \
  --params project=ABC member_list_file=members.xlsx code_volume_file=code_volume.xlsx \
  --output-formats excel

- Для `unified_review` параметры `--start/--end` опциональны. Если их не задавать, будут обработаны все ссылки из `reporting.links_file` (по умолчанию `input.txt`). При указании дат в отчёт попадут только PR/коммиты, замёрженные в указанный период.
- Источник для каждой ссылки определяется автоматически по URL, так что `--sources` задавать не обязательно.
- Для `jira_weekly` параметр `--sources` необязателен, по умолчанию используется `jira`. Если нужны другие источники, их можно указать явно.
- Для `jira_comprehensive` можно передать `--params jql=...` (или `version=...` / `epic=...`) вместо `project+dates`.
- `jira_comprehensive` включает лист `Worklog_Activity` (агрегация времени по задаче и инженеру), а `Assistance_Provided` считается по метке `dev_assistance`.
```

## Jira Weekly Report Structure

The `jira_weekly` report consists of multiple views:

Worklog-driven attribution: if time is logged on an issue within the selected period, it appears in the weekly report as `Task in progress` for those weeks, even if the issue is still unresolved.

1. **Table View** - Tabular format with columns: Name, Week #, Date, Description, Link, Status
2. **List View** - Tasks grouped by assignee and week, showing weekly progress
3. **Engineer Weekly Activity** - Per engineer weekly breakdown with time logged by that engineer, status/resolution, and comments (including worklog comments) added/updated in the week
4. **Epic Progress** - Resolved tasks grouped by epics, plus Progressed Tasks (issues with worklogs but no resolution during the period)
5. **Resolved Tasks** - Chronological list of resolved tasks by week

Each view is generated as a separate section in the Word document. Excel export contains a pivot table grouped by assignee and week.

# Caching

The toolkit includes a two-level caching system to speed up repeated runs:

1. **API-level caching**: All API requests are cached automatically. This reduces redundant calls to Git services when processing the same repositories or links.
2. **Link-level caching**: Results from processing individual links (PRs/commits) are cached, so re-running the same `input.txt` file is much faster.

Cache configuration in `config.ini`:
```ini
[cache]
; Enable/disable caching (true/false)
enabled = true
; Path to cache file (JSON format, can be edited manually)
file = cache.json
; Time-to-live in days (0 = no expiration)
ttl_days = 0
```

- Cache is stored in JSON format, so you can manually edit `cache.json` if needed.
- To clear cache, delete `cache.json` or set `enabled = false`.
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
  - Unified review report
- Add fixtures under `tests/fixtures/` when extending functionality.

# Building Binaries

Windows:
```
build_stats_tool.cmd
```

Linux/macOS:
```
chmod +x build_stats_tool.sh
./build_stats_tool.sh
```

Outputs `dist/stats_tool` executable (PyInstaller-based) bundling Python + templates.

# Adding New Sources/Reports

- Implement `BaseSource` protocol (see existing gitee/github/gitlab).
- Register new report via `stats_core.reports.registry.register`.
- Reuse `stats_core.export` helpers for consistent formatting.

