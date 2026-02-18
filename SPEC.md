# Coding Statistics Toolkit — Spec

## Description
Unified toolkit for gathering coding and Jira activity statistics across Git-like services (Gitee, GitCode, GitHub, GitLab, CodeHub family, Gerrit) and Jira, then exporting reports to Excel/Word/CSV. The entry point is `stats_main.py`, which dispatches to a CLI in `stats_core/cli.py`.

## Primary Functions

### CLI
- **setup**: Generates `config.ini` from `config.ini_template` if missing and guides token/credential onboarding.
- **run**: Executes a report by name, with date range, sources, output formats, and extra params.

### Data Collection
- **Collector** (`stats_core/stats/collector.py`): Pulls PRs/commits from configured sources, filters by date range, and returns a unified dataset.
- **Sources** (`stats_core/sources/*`): Adapters for gitee/gitcode, github, gitlab, codehub variants, gerrit, jira.

### Reports
- **jira_weekly** (`stats_core/reports/jira_weekly.py`):
  - Builds weekly Jira views based on worklogs + resolutions.
  - Produces Word sections (table view, list view, engineer activity, epic progress, resolved tasks).
  - Produces Excel grouped by assignee/week.
- **jira_comprehensive** (`stats_core/reports/jira_comprehensive.py`):
  - Generates multi-sheet Excel: Issues, Links, Engineer/QA/PM metrics, Worklog activity, Worklog entries.
  - Supports project+dates, version, epic, or custom JQL filters.
- **jira_weekly_email** (`stats_core/reports/jira_weekly_email.py`):
  - Generates Outlook-friendly HTML weekly report from Jira comments for the selected week.
  - Week selector supports `week_date`, or `week` (+ optional `year`), or same-week `start/end`.
  - Keeps Epic/task order using previous snapshots and prints red/green/white diff to console only.
  - Supports configurable labels (`labels_highlights`, `labels_report`) and optional vacations from Excel.
- **unified_review** (`stats_core/reports/unified_review.py`):
  - Processes links from `input.txt` (or config override), auto-detects platform by URL, and exports summary tables.

### Export
- **Excel**: `stats_core/export/excel.py` with optional templates.
- **Word**: `stats_core/export/word.py` with sectioned tables and optional templates.
- **CSV**: `stats_core/export/csv_export.py`.

### Caching
- **CacheManager** (`stats_core/cache.py`): Caches API responses and link-processing results in `cache.json`, with optional TTL.

## Inputs and Outputs

### Inputs
- `config.ini` (created from `config.ini_template` by setup)
- `input.txt` (link list for unified_review, unless overridden)
- `members.xlsx` (team list for Jira reports)
- Optional: `code_volume.xlsx` (jira_comprehensive metrics)
- Optional: templates in `templates/word` and `templates/excel`
- Optional: `bundle-ca` (custom CA for SSL)

### Outputs
- Default output folder: `reports/` (configurable via `[reporting] output_dir`)
- Jira weekly: `jira_report_{PROJECT}_{START}-{END}_{timestamp}.docx/.xlsx`
- Jira comprehensive: `jira_comprehensive_report_{timestamp}.xlsx`
- Jira weekly email: `jira_weekly_email_{PROJECT}_{YY'wWW}.html`
- Jira weekly email snapshots: `reports/snapshots/jira_weekly_email/{PROJECT}/{YY'wWW}.json`
- Unified review: `review_summary.(xlsx|csv|docx)`

## Requirements

### Runtime
- Python environment with dependencies from `requirements.txt` (notably `jira`, `requests`, `pandas`, `openpyxl`, `python-docx`, `pygerrit2`).

### Configuration (Minimum)
- **Jira**: `[jira] jira-url, username, password` (API token for Atlassian Cloud).
- **Git sources**: Provide tokens and `repository` lists per source in config sections (`[gitee]`, `[gitcode]`, `[github]`, `[gitlab]`, `[codehub]`, `[gerrit]`).
- **Reporting** (optional): `[reporting] links_file, output_dir, review_word_template`.
- **Ollama** (optional for jira_weekly_email): `[ollama] url, model, timeout_seconds, temperature, enabled`.
- **jira_weekly_email** (optional defaults): labels (`labels_highlights`, `labels_report`), vacation settings, chapter titles.
- **Cache** (optional): `[cache] enabled, file, ttl_days`.
- **Proxy/SSL** (optional): `[proxy]` and `[ssl]` settings.

### Example Commands
```
python stats_main.py setup

python stats_main.py run \
  --report jira_weekly \
  --start 2025-02-01 --end 2025-02-28 \
  --params project=ABC member_list_file=members.xlsx include_empty_weeks=True \
  --output-formats excel word

python stats_main.py run \
  --report unified_review \
  --output-formats excel word

python stats_main.py run \
  --report jira_weekly_email \
  --output-formats html \
  --params project=ABC week_date=2026-02-18 labels_highlights=highlights labels_report=report ollama_enabled=true
```

## Limitations

- **Report scope**: Built-in reports include `jira_weekly`, `jira_comprehensive`, `jira_weekly_email`, and `unified_review`.
- **Jira weekly**:
  - Requires `project`, `start`, `end`.
  - Uses worklogs for attribution; issues without worklogs may be absent unless resolved within range.
  - Can synthesize empty weeks per member when enabled.
- **Jira comprehensive**:
  - Excel-only; no Word/CSV output.
  - Requires JQL or project+dates or version/epic filters.
  - Member-based metrics depend on `members.xlsx` columns.
- **Jira weekly email**:
  - HTML-only output.
  - Diff is printed to console only (not embedded into report HTML).
  - Requires Jira comment activity in selected week; empty week produces mostly empty chapters.
  - Ollama is optional; if unavailable, deterministic text is used.
  - Vacation extraction depends on workbook structure (date row + marker cells) and configured markers.
- **Unified review**:
  - Only processes URLs matching known platform patterns.
  - Private repository data requires valid tokens.
- **Network/SSL**: Requires outbound access; SSL verification is on by default unless explicitly disabled.
- **Date handling**: Filters are ISO date strings; timestamps normalized to UTC for comparisons, but source timestamps drive inclusion.

## Extension Points
- **New source**: Implement `BaseSource` (`stats_core/sources/base.py`) and add to `SOURCE_BUILDERS`.
- **New report**: Create report class and register with `stats_core/reports/registry.register`.
- **Export customization**: Use templates in `templates/` or pass report params like `word_template`, `word_font`, `word_font_size`, `word_table_style`.
