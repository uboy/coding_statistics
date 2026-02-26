# Knowledge Base: coding_statistics

## Overview
Unified Coding Statistics Toolkit is a Python CLI that collects data from Git-like
services (Gitee, GitCode, GitHub, GitLab, CodeHub family, Gerrit) and Jira, then
generates reports in Word/Excel/HTML formats.

Core entrypoint is `stats_main.py`, which delegates to `stats_core.cli.main`.

## Repo Map (Key Paths)
- `stats_core/` core CLI, config, cache, stats pipeline, sources, reports, export helpers
- `stats_core/sources/` API adapters per service (jira, github, gitlab, gerrit, etc.)
- `stats_core/stats/` data collection orchestration (`collector.py`)
- `stats_core/reports/` report definitions and registry
- `stats_core/export/` Word/Excel/CSV export helpers
- `configs/` config templates and local config location
- `report_inputs/` inputs like links list, members, vacations, etc.
- `reports/` generated outputs (docx/xlsx/html + snapshots)
- `templates/` Word/Excel templates
- `tests/` pytest suite

## Core Data Flow
```
sources -> stats.collector -> reports -> export
   |            |               |         |
   |            |               |         +-> Word/Excel/HTML
   |            |               +-> report definitions in stats_core/reports/
   |            +-> aggregation / filtering / normalization
   +-> API adapters (jira/github/gitlab/etc.)
```

## Reports Catalog
### jira_weekly
- Purpose: weekly activity & progress summary from Jira, including worklog-driven
  attribution and epic progress.
- Inputs: `--start`, `--end`, `--params project=KEY`
- Outputs: Word + Excel (table/list/engineer weekly activity/epic progress/summary)
- Key params: `include_empty_weeks`, `member_list_file`

### jira_comprehensive
- Purpose: comprehensive Jira export to Excel, includes issue details and comments.
- Inputs: `--start`, `--end` or `--params jql=...` or `version=...` or `epic=...`
- Outputs: Excel only
- Notes: JQL defaults to `resolved` date filtering if `project+dates` are used.
- Notes: Includes `Comments_Period` sheet with `Comments`, `Comments_In_Period`, `AI_Comments`. AI is off by default; enable via `--params ai_comments_enabled=true`.

### jira_weekly_email
- Purpose: Outlook-friendly HTML email, with highlights/achievements/next week plans/vacations.
- Inputs: `--params project=KEY week_date=YYYY-MM-DD` (or `week=WWwYYYY`)
- Outputs: HTML only, stores weekly snapshot JSON in `reports/`
- Key params: `labels_highlights`, `labels_report`, `vacation_file`, `ai_provider`

### unified_review
- Purpose: consolidated review report from links (PRs/commits), auto-detects sources.
- Inputs: `report_inputs/input.txt` (or `reporting.links_file` in config), optional `--start/--end`
- Outputs: Word/Excel/CSV

## CLI Recipes
- Setup config:
  - `python stats_main.py setup`
- Run a report:
  - `python stats_main.py run --report jira_weekly --start 2025-02-01 --end 2025-02-28 --params project=ABC --output-formats excel word`
- Passing params:
  - `--params key=value key2=value2`
  - For boolean: `true/false` or `1/0`

## Config Essentials
Default config path: `configs/local/config.ini` (copied from template on `setup`).

Common sections:
- `[jira]` url/username/password (required for Jira reports)
- `[reporting]` links file and output base options
- `[cache]` enable/ttl/path for API/link cache
- `[ollama]` and/or `[webui]` for AI summary polishing
- `[jira_weekly_email]` header/meta configuration

Cache file default: `data/cache/cache.json`.

## Output Formats and Templates
- Outputs are written to `reports/` unless overridden.
- Word templates: `templates/word/`
- Excel templates: `templates/excel/`

## Extension Points
- New report: implement in `stats_core/reports/` and register in
  `stats_core/reports/registry.py`.
- New source: implement adapter in `stats_core/sources/` and wire to reports or
  collector as needed.
- Reuse export utilities in `stats_core/export/` for consistent formatting.

## Common Pitfalls
- `jira_comprehensive` uses resolved-date filtering by default (not updated-date).
- Missing `report_inputs/members.xlsx` can break engineer/PM performance sheets.
- Empty reports often come from wrong period, project key, or missing config.
- Make sure `report_inputs/input.txt` exists for `unified_review` default flow.

## Operational Constraints
- No secrets/tokens/credentials in repo or logs.
- No new dependencies without explicit approval.
- Keep diffs minimal and additive.

## Update Checklist
- Add a new report or change params -> update this doc and README.
- Change output path or template usage -> update this doc.
- Add a new source adapter -> update repo map + extension points.
