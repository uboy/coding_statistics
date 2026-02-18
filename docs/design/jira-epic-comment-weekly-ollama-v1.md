# Jira Epic Weekly Narrative Report from Jira Comments + Ollama v1

## 1) Summary: problem statement + goals + non-goals
Problem:
- Existing Jira weekly output is mostly task/worklog-centric.
- New requirement is a fixed-format narrative weekly report by epic/component, with:
  - highlighted achievements at the top,
  - epic status/progress details in the middle,
  - plans at the end,
  - content generated from Jira comments,
  - wording formulated by Ollama,
  - stable section order across weeks using previous report as baseline.

Goals:
- Introduce a new report type that produces a stable weekly narrative in the same logical order each run.
- Use Jira comments as the primary evidence source for narrative bullets.
- Use Ollama for phrasing/summarization while constraining output schema and order.
- Compare with previous report to keep section/epic ordering stable and highlight deltas.

Non-goals:
- Replacing existing `jira_weekly` report.
- Changing Jira credentials/auth flows.
- Adding external SaaS dependencies (local Ollama only).
- Finalizing visual styling permanently (format likely to change later).

## 2) Scope boundaries: what is in/out
In scope:
- New report class (separate from `jira_weekly`) for narrative output.
- Jira comment extraction and normalization for the selected period.
- Deterministic section ordering and previous-report comparison strategy.
- Ollama prompt/response contract with strict JSON schema.
- Word output section composition (and optional plain text snapshot).

Out of scope:
- Refactor of existing table/list/engineer weekly views.
- New package dependencies.
- Full HTML email renderer parity with legacy Word-exported HTML.

## 3) Assumptions + constraints (project-specific)
- No new dependencies without explicit approval (`AGENTS.md`).
- Minimal additive diff.
- Existing stack includes `requests`, `pandas`, `python-docx`; use these only.
- Tests must run with: `pytest tests`.
- Jira comments can arrive as plain string or Atlassian document JSON; parser must support both.
- Ollama is reachable locally (default `http://localhost:11434`) unless overridden.

## 4) Architecture: components/modules + responsibilities + data flow
### New/updated modules
- `stats_core/reports/jira_epic_narrative.py` (new):
  - report entrypoint and orchestration.
  - builds final ordered sections and writes output.
- `stats_core/reports/jira_comment_digest.py` (new):
  - transforms Jira comments/worklog comments into normalized evidence rows.
  - groups evidence by epic/component and semantic bucket.
- `stats_core/reports/ollama_client.py` (new):
  - local Ollama HTTP wrapper (`/api/generate`).
  - strict response parsing and validation.
- `stats_core/reports/jira_utils.py` (update):
  - move/reuse comment-to-text normalization helper (currently duplicated logic exists in comprehensive report).
- `stats_core/reports/__init__.py` and registry import chain (update):
  - register new report.

### Data flow
1. Fetch issues in date range (reuse Jira source).
2. Collect comments and worklog comments for in-range dates.
3. Normalize comments into structured evidence records with epic key/name.
4. Load previous snapshot (machine-readable JSON) if exists.
5. Build deterministic target structure:
   - `ACHIEVEMENTS`
   - `DEPENDENCIES & RISKS`
   - `IN PROGRESS` (grouped by epic/component)
   - `NEXT WEEK PLANS`
6. Call Ollama with strict JSON schema prompt:
   - evidence + prior snapshot + required section order.
7. Validate JSON, fallback safely on deterministic extractive text if LLM output invalid.
8. Render Word report (and persist current snapshot JSON for next run).

## 5) Interfaces/contracts
### Public report name and CLI usage
- Report name: `jira_epic_narrative`
- Example:
  - `python stats_main.py run --report jira_epic_narrative --start 2026-02-09 --end 2026-02-15 --params project=ABC ollama_model=qwen2.5:14b --output-formats word`

### Extra params/config contract
- Required:
  - `project`
  - `start` / `end`
- Optional params:
  - `ollama_url` (default `http://localhost:11434`)
  - `ollama_model` (default from config/reporting)
  - `snapshot_dir` (default `reports/snapshots`)
  - `max_comments_per_epic` (default 200)
  - `strict_ollama` (`true|false`, default `false`)

### Internal module boundaries (proposed signatures)
- `build_comment_evidence(jira_source, project: str, start_date: str, end_date: str) -> pd.DataFrame`
- `load_previous_snapshot(snapshot_path: Path) -> dict[str, Any] | None`
- `build_target_outline(previous_snapshot: dict[str, Any] | None, current_evidence: pd.DataFrame) -> dict[str, Any]`
- `generate_narrative_with_ollama(*, outline: dict[str, Any], evidence: dict[str, Any], previous_snapshot: dict[str, Any] | None, model: str, ollama_url: str) -> dict[str, Any]`
- `validate_narrative_payload(payload: dict[str, Any]) -> list[str]`
- `render_narrative_to_docx(document, payload: dict[str, Any]) -> None`
- `save_snapshot(snapshot_path: Path, payload: dict[str, Any], meta: dict[str, Any]) -> None`

### LLM response contract (strict JSON)
- Top-level keys fixed:
  - `achievements_highlighted`: `list[str]`
  - `dependencies_risks`: `list[str]`
  - `in_progress`: `list[{epic_key, epic_name, status_line, achievements, blockers, notes}]`
  - `next_week_plans`: `list[str]`
- Order must match template exactly; no extra sections allowed.

### Error handling strategy
- If Jira comment parsing fails for an item: skip item, log warning with issue key.
- If Ollama unavailable or invalid JSON:
  - if `strict_ollama=true`: fail report with actionable error.
  - else: build extractive deterministic fallback text from evidence.
- If previous snapshot missing: use default initial order template.

## 6) Data model changes + migrations (if any)
- No persistent DB migrations.
- New file artifact per project:
  - `reports/snapshots/jira_epic_narrative_<project>.json`
- Snapshot contains:
  - last rendered structured payload,
  - epic ordering map,
  - report period metadata.

## 7) Edge cases + failure modes
- Epic missing on issue/sub-task:
  - inherit from parent when possible; else group into `NO-EPIC`.
- Same comment edited multiple times:
  - keep latest in-period version based on updated timestamp.
- Very long comments / noisy logs:
  - truncate per item and per epic before prompt assembly.
- Prompt injection in comments:
  - comments treated as plain data, wrapped and delimited; model instructed to ignore embedded instructions.
- New epic appears this week:
  - append after previously known epics; preserve prior order for existing epics.
- Epic absent this week but existed previously:
  - keep section order stable; include only if configured to show empty epics (default: hide empty, keep ordering memory in snapshot).

## 8) Security requirements
- Authn/authz remains unchanged (Jira basic auth from config).
- Input validation:
  - strict date parsing and bounds check.
  - sanitize control characters from comments before rendering.
- Injection risks:
  - JQL values must be constrained to expected params.
  - LLM prompt injection mitigation by hard schema + delimiters + post-validation.
- Secrets/logging policy:
  - never log Jira password/token or full raw prompt payload.
  - log only counts and issue keys where needed.
- Dependency policy:
  - no new libraries.

## 9) Performance requirements + limits + expected complexity
- Complexity target:
  - Jira fetch and comment aggregation O(n) in number of issues/comments.
- Practical limits:
  - cap evidence volume per epic and total prompt size.
  - one Ollama call per report generation (or bounded small batch).
- Avoid extra Jira round-trips beyond existing fetch/comments/worklogs patterns.

## 10) Observability: logs/metrics/tracing + alerts
- Add structured logs:
  - total issues fetched,
  - comments considered/filtered,
  - epics produced,
  - fallback mode used (yes/no),
  - previous snapshot loaded (yes/no).
- Warning logs:
  - invalid comment body format,
  - LLM validation errors.
- Alert-worthy conditions (for CI/manual check):
  - empty report with non-empty evidence,
  - repeated LLM schema failures.

## 11) Test plan
Unit tests:
- comment normalization (string + ADF JSON body).
- deterministic ordering using previous snapshot.
- new epic append behavior without reordering existing epics.
- strict JSON validator accepts valid payload, rejects malformed payload.
- fallback generation when Ollama errors.

Integration-like tests (mocked Jira + mocked Ollama):
- full run creates `.docx` and snapshot JSON.
- sections appear strictly in required order:
  - `ACHIEVEMENTS`
  - `DEPENDENCIES & RISKS`
  - `IN PROGRESS`
  - `NEXT WEEK PLANS`
- plans are always rendered at the end.

Verification command:
- `pytest tests`

## 12) Rollout plan + rollback plan
Rollout:
1. Add new report in parallel to existing reports.
2. Keep default flows unchanged (`jira_weekly` unaffected).
3. Run on one pilot project and compare output with provided sample structure.
4. Tune prompt and section mapping iteratively.

Rollback:
- Remove report registration/import and keep artifacts untouched.
- Revert new modules without affecting existing reports.

## 13) Acceptance criteria checklist (explicit, testable)
- New report is callable via CLI as separate report type.
- Output always keeps section order:
  - achievements on top,
  - risks/dependencies,
  - in-progress by epic,
  - next-week plans at end.
- Narrative statements are derived from Jira comments/worklog comments for the selected period.
- Ollama is used for phrasing, with validated schema.
- Previous snapshot is consumed to stabilize ordering across runs.
- No new dependencies added.
- `pytest tests` passes.

## Approval
Status: REVIEW REQUIRED

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
