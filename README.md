## Unified Coding Statistics Toolkit

Centralized framework for gathering and exporting statistics from Git-like services (Gitee, GitCode, GitHub, GitLab, CodeHub family, Gerrit) and Jira.

```
stats_core/
  config.py      # config loader, token onboarding
  cli.py         # 'setup' and 'run' commands
  sources/       # API adapters (gitee, gitcode, github, gitlab, codehub*, gerrit)
  stats/         # collector orchestrating multiple sources (dataset -> reports)
  reports/       # report definitions (unified_review, jira_weekly)
  export/        # Word/Excel/CSV helpers with template support
templates/
  word/          # docx templates
  excel/         # xlsx templates
```

- `stats_main.py` simply calls `stats_core.cli.main`.
- Data flows: `sources` → `stats.collector` → `reports` → `export`.

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

# Weekly Jira report
python stats_main.py run \
  --report jira_weekly \
  --sources jira \
  --start 2025-02-01 \
  --end 2025-02-28 \
  --params project=ABC include_empty_weeks=True member_list_file=members.xlsx

- Для `unified_review` параметры `--start/--end` опциональны. Если их не задавать, будут обработаны все ссылки из `reporting.links_file` (по умолчанию `input.txt`). При указании дат в отчёт попадут только PR/коммиты, замёрженные в указанный период.
- Источник для каждой ссылки определяется автоматически по URL, так что `--sources` задавать не обязательно.
```

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

- Includes coverage for exporters, CLI utilities, Gitee source, and unified review Word export.
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


# Jira Performance Report Generator

This tool generates performance reports for team members based on Jira data and optional Git (Gitee/Gerrit) statistics. It calculates role-based metrics for engineers, test engineers, and project managers, and produces detailed reports in Excel and Word formats.

---

## 🔧 Usage

Run the script:

```bash
python jira_weekly_report.py \
  --project ABC \
  --start-date 2025-07-01 \
  --end-date 2025-07-31 \
  --member-list-file members.xlsx \
  --pr-stat-file gitee_pr_stats.xlsx \
  --include-empty-weeks True
```

### Command-Line Arguments

| Argument                | Description                                                        |
|-------------------------|--------------------------------------------------------------------|
| `--project`             | Jira project key (**required**)                                    |
| `--start-date`          | Start date in format YYYY-MM-DD (**required**)                     |
| `--end-date`            | End date in format YYYY-MM-DD (**required**)                       |
| `--member-list-file`    | Path to Excel file with team member info (**required**)            |
| `--pr-stat-file`        | Path to Excel file with PR statistics (**required for engineers**) |
| `--include-empty-weeks` | Include weeks with no data (default: True)                         |
| `--config`              | Path to `config.ini` file (default: `config.ini`)                  |
| `--username`            | Jira username (overrides config.ini)                               |
| `--password`            | Jira password (overrides config.ini)                               |
| `--url`                 | Jira base URL (overrides config.ini)                               |

---

## 📁 Input Files

### `members.xlsx`

Team member details. Required columns:

- `name`: Full name as in Jira
- `role`: `engineer`, `test engineer`, or `project manager`
- `gitee_account`: Gitee or Git login (used for PR matching)
- `feedback_score`: Optional (for PMs)

Example:

```csv
name,role,gitee_account,feedback_score
Alice,engineer,alice_git,
Bob,test engineer,bob_test,
Carol,project manager,,8.5
```

---

### `gitee_pr_stats.xlsx`

Used for engineer metrics. Required columns:

- `PR ID`, `Name`, `Login`, `PR_Name`, `PR_URL`, `PR_State`
- `PR_Created_Date`, `PR_Merged_Date`, `branch`, `Repo`
- `Additions`, `Deletions`, `Reviewers`

Example:

```csv
PR ID,Name,Login,PR_Name,PR_URL,PR_State,PR_Created_Date,PR_Merged_Date,branch,Repo,Additions,Deletions,Reviewers
1,Alice,alice_git,Fix bug,https://gitee.com/pr/1,merged,2025-07-01,2025-07-02,main,repo1,120,30,Bob
```

---

## 📊 Output Reports

### Excel
- **Team Performance**: Summary table (tasks resolved, bugs, etc.)
- **Role-Based Metrics**: Based on team roles, with team averages

### Word
- **Team Performance Ranking**
- **Role-Based Metrics**
- **Tabular View**: Tasks grouped by week
- **List View**: Resolved tasks by assignee
- **Epic Progress**
- **Resolved Tasks**: Raw task list

---

## 🧮 Metrics by Role

### 👨‍💻 Engineers

| Metric                     | Description                                            |
|----------------------------|--------------------------------------------------------|
| **Code Volume**            | Sum of PR additions + deletions                        |
| **Code Quality (Bugs)**    | Bugs opened by others, linked to this engineer’s tasks |
| **Documentation Quantity** | Jira tasks with label `documentation`                  |
| **Critical Tasks**         | Tasks with `critical` label or `Priority = Highest`    |
| **PR Reviews**             | Number of PRs reviewed (not authored)                  |

---

### 🧪 Test Engineers

| Metric                      | Description                                                                    |
|-----------------------------|--------------------------------------------------------------------------------|
| **Test Cases**              | Tasks with `testdev` or `test` labels                                          |
| **Bugs Reported**           | Bugs created by this engineer                                                  |
| **Performance Benchmarks**  | Tasks with label `testperf` and keyword `benchmark` or `performance`           |

---

### 📋 Project Managers

| Metric              | Description                                                       |
|---------------------|-------------------------------------------------------------------|
| **Goal Planning**   | Number of resolved tasks with label `milestone`                   |
| **Project Result**  | Resolved tasks assigned to the PM (including Epics)               |
| **Huawei Feedback** | Optional score from `members.xlsx` column `feedback_score`        |

---

## ✅ Jira Marking Instructions for Teams

To ensure data is collected correctly, use the following conventions when creating and managing Jira tasks:

| Jira Element    | Required Value                                      | Used For                       |
|-----------------|-----------------------------------------------------|--------------------------------|
| **Labels**      | `documentation`                                     | Engineer documentation         |
|                 | `critical`                                          | Critical tasks                 |
|                 | `milestone`                                         | PM milestone tasks             |
|                 | `testdev`, `test`                                   | Test engineer scenarios        |
|                 | `testperf`                                          | Performance benchmarks         |
| **Priority**    | `Highest`                                           | Critical task identification   |
| **Issue Type**  | `Bug`, `Task`, `Epic`, etc.                         | General classification         |
| **Resolution**  | Set to `Resolved` when complete                     | Filter for completed tasks     |
| **Assignee**    | Must match `name` in `members.xlsx`                 | Attribution of metrics         |
| **Creator**     | Important for tracking bugs reported by testers     | Test engineer bug metrics      |
| **Issue Links** | Use `relates to` for linking engineer tasks to bugs | Engineer code quality tracking |

---

## 📝 Notes

- Dates should be in `YYYY-MM-DD` format
- Missing or invalid data (e.g. empty `Labels`) are handled gracefully
- PR review metrics only work if reviewer names are listed in `Reviewers` column
- Use `config.ini` or command-line credentials for authentication
