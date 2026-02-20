# Design Spec — Jira Comprehensive Monthly Summary (v1)

## 1) Summary
### Problem statement
`jira_comprehensive` (monthly report) currently exports detailed sheets (`Issues`, `Links`, `Results`, performance sheets), but has no executive-level `Summary` section per epic. Stakeholders need short, outcome-focused achievements for the period, not raw issue data.

### Goals
- Add `Summary` generation for monthly report, grouped by epic.
- For each epic, summarize resolved planned tasks/subtasks in the period.
- Build each task achievement from:
  - issue title,
  - issue description,
  - latest comment.
- Use AI rewriting (same transport options as weekly email): Ollama and Open WebUI.
- Enforce concise output (1-2 sentences per task achievement).
- Add mandatory epic-level closing lines:
  - `Resolved xx planned tasks on time.`
  - If epic has bugs: `Resolved xx reported issues.`

### Non-goals
- No changes to Jira data source/auth model.
- No changes to existing report filters/JQL semantics.
- No changes to weekly reports.
- No new external dependencies.

## 2) Scope boundaries
### In scope
- `jira_comprehensive` report only.
- New `Summary` sheet in Excel output.
- AI rewrite pipeline for summary items (provider-selectable: `ollama` / `webui`).
- Deterministic fallback text when AI is disabled/unavailable/invalid.

### Out of scope
- Word/HTML output for comprehensive report.
- Changing existing `Results` extraction semantics.
- Any migration/storage schema changes.

## 3) Assumptions + constraints
- Repo constraints from `AGENTS.md`:
  - minimal, additive diffs;
  - no new deps without approval;
  - run full `pytest tests`.
- Monthly period is already defined by existing JQL (`resolved >= start and < end+1`).
- AI model can be weak (e.g., `gpt-oss-120b`), so prompt must be explicit, schema-constrained, and defensive.
- Existing config sections `[ollama]` and `[webui]` are reused.

## 4) Architecture
### Components
- `fetch_jira_data(...)`:
  - enrich issue rows with latest comment text (`Last_Comment`) for summary evidence.
- `build_monthly_summary_df(...)` (new):
  - input: `issues_df`, `config`, `extra_params`;
  - output: normalized summary rows per epic.
- `rewrite_summary_items_with_ai(...)` (new orchestrator):
  - provider routing (`ollama`/`webui`);
  - batch prompt construction;
  - strict JSON parse + sanitization.
- `export_to_excel(...)`:
  - write new `Summary` sheet.

### Data flow
1. Fetch Jira issues/comments (existing flow).
2. Build `issues_df` + `results_df` (existing flow).
3. Build summary evidence from resolved, countable issues:
   - planned tasks = non-bug, non-epic resolved items;
   - bug counter = resolved bug items.
4. Rewrite planned task achievements via AI (or fallback).
5. Compose epic summary body:
   - bullet-style achievements by task;
   - mandatory count lines.
6. Export workbook with new `Summary` sheet.

## 5) Interfaces/contracts
### Public behavior (CLI/report contract)
- Report: `jira_comprehensive` (`excel` output).
- New output sheet: `Summary`.
- Optional params reused from weekly-email AI stack:
  - `ai_provider` (`ollama` | `webui`);
  - `ollama_enabled`, `ollama_url`, `ollama_model`, `ollama_timeout_seconds`, `ollama_temperature`, `ollama_api_key`;
  - `webui_enabled`, `webui_url`, `webui_endpoint`, `webui_model`, `webui_timeout_seconds`, `webui_connect_timeout_seconds`, `webui_temperature`, `webui_api_key`.

### Internal function contracts
- `build_monthly_summary_df(issues_df: pd.DataFrame, config: ConfigParser, extra_params: dict[str, Any]) -> pd.DataFrame`
  - returns columns:
    - `Epic_Link`
    - `Epic_Name`
    - `Summary`
    - `Planned_Tasks_Resolved`
    - `Reported_Issues_Resolved`
- `rewrite_summary_items_with_ai(items: list[dict[str, str]], config: ConfigParser, extra_params: dict[str, Any]) -> dict[str, str]`
  - input item fields: `id`, `summary`, `description`, `last_comment`;
  - output map: `id -> rewritten text`.

### Error handling strategy
- AI provider failures do not fail report generation.
- On AI HTTP/parse failures:
  - log warning with batch context;
  - use deterministic fallback per task.
- Missing model/config -> warning + fallback.

## 6) Data model changes + migrations
- No DB/data migrations.
- Workbook structure change:
  - add sheet `Summary`.
- `Issues` dataframe enriched with `Last_Comment` runtime column.

## 7) Edge cases + failure modes
- Epic with only bugs:
  - no task bullets; include required count lines (`0 planned`, `N issues`).
- Epic with only planned tasks:
  - include task bullets + planned count line only.
- Missing description/comments:
  - fallback from title-only achievement template.
- AI returns non-JSON or truncated output:
  - skip batch rewrite, keep fallback text.
- Unknown epic:
  - use `Unknown Epic`.

## 8) Security requirements
- Authn/authz unchanged (Jira creds from config).
- Input safety:
  - sanitize AI output (strip links, ticket IDs, commit hashes).
  - keep strict JSON parse boundary.
- Logging:
  - avoid secrets (API keys not logged).
  - log aggregate counts and provider mode only.
- Dependency policy:
  - no additional packages.

## 9) Performance requirements
- Grouping/summarization complexity: `O(n)` over resolved issue rows.
- AI requests are batched (fixed-size chunks) to avoid oversized prompts.
- Expected monthly scale: hundreds of issues; should remain within current report runtime envelope.

## 10) Observability
- Add/extend info logs:
  - summary rows generated,
  - AI provider used,
  - rewritten vs fallback counts,
  - batch failure warnings (non-fatal).
- Include `summary_epics` in final report summary log.

## 11) Test plan
### Unit/integration coverage
- `tests/test_jira_comprehensive_report.py`:
  - workbook contains `Summary` sheet;
  - per-epic mandatory lines exist:
    - `Resolved xx planned tasks on time.`
    - `Resolved xx reported issues.` when bugs exist;
  - planned/bug counters are correct by epic;
  - `priority/high` logic unaffected in comprehensive report path.
- AI fallback behavior:
  - without configured model, summary still generated deterministically.

### Commands
- Full validation command (repo standard):
  - `pytest tests`

## 12) Rollout plan + rollback plan
### Rollout
1. Implement summary dataframe build and export.
2. Add tests for summary sheet and counters.
3. Run full `pytest tests`.
4. Release with no config migration required.

### Rollback
1. Revert summary builder + sheet write.
2. Keep existing sheets unchanged (`Issues`, `Links`, `Results`, performance).

## 13) Acceptance criteria checklist
- [ ] `jira_comprehensive` generates `Summary` sheet in Excel.
- [ ] Summary is grouped by epic.
- [ ] Planned task achievements are generated from title+description+latest comment.
- [ ] Each planned achievement is 1-2 short sentences.
- [ ] Each epic ends with `Resolved xx planned tasks on time.`
- [ ] If bugs exist in epic, includes `Resolved xx reported issues.`
- [ ] AI routing supports both Ollama and Open WebUI with deterministic fallback.
- [ ] Existing report sheets remain intact and tests pass.

## Approval
REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
