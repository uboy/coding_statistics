
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
