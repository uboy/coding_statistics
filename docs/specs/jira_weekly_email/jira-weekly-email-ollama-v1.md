# Design Spec — Jira Weekly Email Report (Ollama) (v1)

## Status
- Status: APPROVED:v1
- Approved by: user
- Date: 2026-02-18

## Summary
Problem:
- Existing Jira reports are table/Word oriented, but the team needs a weekly narrative email in HTML (Outlook-friendly), built from Jira comments, with stable ordering week-to-week and AI-polished short text.

Goals:
- Add a new weekly Jira email report that:
1. Uses existing Jira integration/auth.
2. Supports period selection by any date within the week, or by ISO week number (default year = current year).
3. Collects all Jira comments added in the reporting week for configured/CLI project.
4. Produces Outlook-compatible HTML.
5. Structures content into required chapters (Highlights, Key Results/Achievements, Next Week Plans, Vacations), where High Priority and Bugs Summary are included inside chapter 2 per epic.
6. Uses Ollama to rewrite short text (1-2 sentences max per item).
7. Preserves epic/task ordering from previous report and shows delta only in console logs.

Non-goals:
- Replacing `jira_weekly` or `jira_comprehensive`.
- Adding external SaaS or new Python dependencies.
- Changing Jira credentials/auth flow.

## Scope boundaries
In scope:
- New report type (suggested name: `jira_weekly_email`).
- New HTML renderer (inline styles for Outlook).
- Ollama API client wrapper using existing `requests`.
- Week resolver (date/week-number inputs).
- Previous report snapshot persistence and console diffing.
- Vacation extraction from Excel sheet (default `Vacations2026`, configurable).

Out of scope:
- Refactoring legacy weekly/comprehensive reports.
- Rich HTML/CSS framework support.
- Multi-locale NLP beyond configurable text templates.

## Architecture
### Components
1. `stats_core/reports/jira_weekly_email.py` (new):
- Main orchestrator for data collection, AI processing, ordering, console diff, and export.

2. `stats_core/reports/jira_weekly_email_utils.py` (new):
- Week range resolution.
- Issue/comment evidence assembly.
- Epic/task grouping and deterministic ordering.
- Diff computation vs previous snapshot.
- Vacation parsing + normalization.

3. `stats_core/reports/ollama_client.py` (new):
- Minimal Ollama HTTP client for `/api/generate` (or `/api/chat` if selected), strict JSON response parsing.

4. `stats_core/reports/jira_utils.py` (update):
- Reuse/move comment-body normalization helper (string/ADF) to avoid duplication.

5. `stats_core/reports/__init__.py` (update):
- Register new report module.

### Data flow
1. Resolve target week (`week_start`, `week_end`, `week_key` like `26'w08`).
2. Resolve `project` from CLI param first, fallback config.
3. Fetch Jira issues for project using existing `JiraSource`.
4. Fetch all issue comments; keep comments with created/updated inside the week.
5. Build normalized evidence rows (issue, epic, type, status, resolution, labels, priority, comment text, dates).
6. Build chapter payload:
- Highlights: issues matching configurable highlights labels with short headline text; Jira key is placed at line end in parentheses.
- Key Results/Achievements by epic (finished items/subtasks).
- Report-labeled subgroup (configurable labels, default includes `report`) first inside each epic.
- High-priority subsection per epic (separate paragraph inside chapter 2).
- Bug summary subsection per epic (separate paragraph inside chapter 2).
- Next week plans (in-progress issues).
- Vacations in next 60 days.
7. Load previous snapshot for the same project; apply prior epic/task ordering.
8. Call Ollama to rewrite item texts to concise 1-2 sentence outputs under strict schema.
9. Validate/normalize AI output; fallback to deterministic non-AI text if needed.
10. Render Outlook-safe HTML + save snapshot + compute/print diff only to console.

## Contracts / APIs / Data Schemas
### Report invocation
- CLI:
  - `python stats_main.py run --report jira_weekly_email --output-formats html --params project=ABC week_date=2026-02-18`
  - `python stats_main.py run --report jira_weekly_email --output-formats html --params project=ABC week=8`
  - Optional: `year=2026` (default current year if omitted).

### Week input contract
Accepted selectors (priority order):
1. `week_date=YYYY-MM-DD` -> derive ISO week/year from date.
2. `week=<1..53>` and optional `year=<YYYY>` (default current year).
3. Fallback: `start/end` only if both in same ISO week; otherwise validation error.

### Configuration additions
`[ollama]`:
- `url` (default `http://localhost:11434`)
- `model` (required for AI mode)
- `timeout_seconds` (default `60`)
- `temperature` (default `0.2`)
- `enabled` (`true/false`, default `true`)

`[jira_weekly_email]`:
- `project` (fallback if CLI missing)
- `output_dir` (default `reports`)
- `snapshot_dir` (default `reports/snapshots/jira_weekly_email`)
- `vacation_file` (optional path)
- `vacation_sheet` (default `Vacations2026`)
- `vacation_marker_values` (default `p,P`)
- `vacation_horizon_days` (default `60`)
- `priority_high_values` (default `High,Highest`)
- `labels_highlights` (default `highlights`; comma-separated list supported)
- `labels_report` (default `report`; comma-separated list supported)
- Configurable text fields/titles/templates:
  - `title_main`
  - `chapter_highlights_title`
  - `chapter_results_title`
  - `chapter_next_week_title`
  - `chapter_vacations_title`
  - `chapter_results_high_priority_subtitle`
  - `chapter_results_bugs_subtitle`
  - `console_diff_title`
  - `bugs_summary_template_closed_in_progress`

### Internal function signatures (proposed)
- `resolve_week_window(params: dict[str, Any], now: date) -> WeekWindow`
- `collect_weekly_comment_evidence(jira_source: JiraSource, project: str, week: WeekWindow) -> pd.DataFrame`
- `build_report_payload(evidence_df: pd.DataFrame, week: WeekWindow, config: ConfigParser) -> dict[str, Any]`
- `load_previous_snapshot(snapshot_dir: Path, project: str) -> dict[str, Any] | None`
- `apply_previous_order(payload: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]`
- `rewrite_payload_with_ollama(payload: dict[str, Any], ollama_cfg: dict[str, Any]) -> dict[str, Any]`
- `compute_payload_diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]`
- `parse_vacations_excel(path: Path, sheet: str, markers: set[str], horizon_start: date, horizon_days: int) -> list[VacationRange]`
- `render_outlook_html(payload: dict[str, Any], cfg: dict[str, Any]) -> str`
- `render_console_diff(diff: dict[str, Any], *, use_color: bool = True) -> None`
- `save_snapshot(path: Path, payload: dict[str, Any], meta: dict[str, Any]) -> None`

### Output artifacts
- HTML report:
  - `reports/jira_weekly_email_<project>_<week_key>.html` where week key format is `26'w08`.
- JSON snapshot:
  - `reports/snapshots/jira_weekly_email/<project>/<week_key>.json`
- Diff is not embedded in HTML; it is printed to console and may be stored in snapshot metadata.

### Error handling strategy
- Missing project -> fail with actionable message.
- Invalid week selector -> fail with selector guidance.
- Ollama unavailable/invalid JSON:
  - if strict mode disabled: fallback deterministic text + warning.
  - if strict mode enabled: fail run.
- Vacation file missing/unreadable: warning + continue without vacation section.

## Constraints & Assumptions
- No new dependencies (AGENTS).
- Must use existing Jira integration (`JiraSource`) and config auth.
- Comments are the primary evidence source for weekly progress.
- Finished/in-progress classification uses issue fields (`resolution/status/type`) plus weekly evidence.
- Outlook compatibility means simple HTML with inline CSS, no JS/external assets.
- Current year default applies only when `week` is set and `year` omitted.

## Data model changes + migrations
- No DB migrations.
- New persisted snapshot JSON schema:
  - `meta`: project, week/year, generated_at
  - `order`: epic_order, task_order_by_epic
  - `chapters`: rendered canonical data (before/after AI)
  - `diff`: added/removed/changed entries

## Edge cases + failure modes
- Issue without epic:
  - map via parent epic if possible, else `Unknown Epic`.
- No comments in week:
  - produce report with empty-state sections and explicit note.
- Multiple disjoint vacation ranges per engineer:
  - collapse adjacent dates into ranges; output each range.
- Vacation markers mixed case (`p`/`P`):
  - compare case-insensitively.
- Priority ambiguity (`High` vs `Highest` or custom):
  - configurable set in `priority_high_values`.
- report/highlights labels (based on configurable label sets) both present:
  - issue appears in both relevant sections but with same canonical key (for diff stability).

## Security Requirements
- Authn/authz unchanged (Jira + local Ollama).
- Input validation:
  - strict date/week parsing, week bounds check.
  - HTML-escape all Jira/Ollama/user-provided strings before rendering.
- Injection risks:
  - JQL built from constrained params only.
  - prompt injection mitigation: send comments as delimited data, enforce strict response schema.
- Secrets/logging:
  - never log passwords/tokens.
  - log counts/issue keys, not full sensitive payloads.
- Dependency policy:
  - no new packages without explicit approval.

## Performance Considerations
- Time complexity O(I + C) for issues/comments in week scope.
- Keep Ollama calls bounded (single call per report; optional chunking fallback).
- Use snapshot ordering to avoid expensive recomputation of stable order.
- Practical limits:
  - configurable cap per epic comments for prompt construction.
  - truncate oversized comment evidence before AI call.

## Observability
- Info logs:
  - selected week/project, issue count, comment count, epic count.
  - highlights/results/plans item counts.
  - vacation entries count.
  - previous snapshot found/not found.
  - AI mode/fallback mode.
  - diff lines printed in console:
    - old line: strikethrough + red
    - new line: green
    - unchanged line: white/default
- Warning logs:
  - malformed comment payloads.
  - unknown vacation markers.
  - Ollama schema failures.
- Metrics (optional log-based):
  - `weekly_email_report_generation_seconds`
  - `weekly_email_ollama_failures_total`
  - `weekly_email_items_total{chapter=...}`

## Test Plan
Unit tests:
1. Week resolver:
- `week_date` mapping.
- `week + default current year`.
- invalid mixed selectors.
2. Comment evidence:
- only comments within week included.
- ADF/string normalization.
3. Chapter builder:
- highlights by label.
- finished/in-progress grouping by epic.
- `report`-labeled items first in epic section.
- configurable label mapping via `labels_highlights` and `labels_report`.
- high-priority bucket.
- bug summary counters (closed vs in-progress).
4. Ordering:
- first run default order.
- subsequent run preserves prior epic/task order and appends new items.
5. Vacation parser:
- read `Vacations2026` style sheet (header row with dates, name column B).
- parse markers `p/P`, collapse ranges, 60-day filter.
6. AI rewrite validator:
- enforces max 1-2 sentences per item.
- fallback on invalid payload.
7. HTML renderer:
- produces single self-contained HTML suitable for Outlook (inline CSS, no script tags).

Integration-like tests (mock Jira + mock Ollama + fixture vacation xlsx):
- Full run creates HTML + snapshot + console diff output.
- Week-key naming format `26'w08`.
- Console diff shows added/changed/removed between snapshots with red/green/default formatting.

Verification command:
- `pytest tests`

## Rollout / Rollback Plan
Rollout:
1. Add report in parallel (`jira_weekly_email`), no changes to existing report defaults.
2. Pilot on one project for 2-3 weeks.
3. Tune text templates and marker config from pilot feedback.

Rollback:
1. Remove report registration/import.
2. Keep generated artifacts for audit but stop generation.
3. No impact on existing reports.

## Acceptance Criteria
1. New report runs via CLI and uses existing Jira config/auth.
2. Week can be selected by any date in week or week number (+ default current year).
3. Report evidence is built from Jira comments added in reporting week.
4. Output is Outlook-compatible HTML.
5. Highlights section includes one-line-per-task headline for issues matched by configurable `labels_highlights`, with Jira key at end in parentheses.
6. Key Results section is grouped by epic; finished tasks/subtasks listed with Jira key in parentheses.
7. Report-labeled items (via configurable `labels_report`) are shown first-level and separate paragraph inside epic block.
8. Next Week Plans contains in-progress issues grouped by epic.
9. High-priority issues are shown inside chapter 2, within each related epic, as separate paragraph.
10. Previous report ordering is preserved; changes vs previous are printed only to console in diff format.
11. Reports are stored by week/year key format like `26'w08`.
12. Bugs are grouped by epic and summarized as closed vs in-progress counts inside chapter 2 using configurable template text.
13. Generated result/progress texts are concise (1-2 sentences max per item).
14. Vacations are parsed from configurable Excel sheet (default `Vacations2026`) and listed per developer for next 60 days.
15. No new dependencies added.
16. `pytest tests` passes after implementation.
17. Highlights/report labels are configurable via `labels_highlights` and `labels_report`.

## Open Questions
1. In vacation sheet, marker `a` appears in sample; should it be treated as vacation/absence or ignored by default?
2. Should week selector allow explicit `year` when `week_date` is provided (override), or always infer from date?
3. For first run with no previous snapshot, should epic order be alphabetical or by activity volume?

## Report Example
Below is an example of how the final report should look for recipients (HTML email body, Outlook-friendly structure).

```html
<html>
  <body style="font-family: Calibri, Arial, sans-serif; font-size:14px; color:#1f2937;">
    <h2 style="margin:0 0 8px 0;">TelmaST Weekly Report - ABC - 26'w08</h2>
    <p style="margin:0 0 16px 0;">Period: 2026-02-16 to 2026-02-22</p>

    <h3>1. Highlights</h3>
    <ul>
      <li><b>Dashboard pagination delivered:</b> End-to-end flow is complete and validated in staging (ABC-1245).</li>
      <li><b>Weekly test stability improved:</b> Flaky integration checks were stabilized and reruns reduced (ABC-1310).</li>
      <li><b>Permission middleware migration completed:</b> Shared validation path is now active for target endpoints (ABC-1402).</li>
    </ul>

    <h3>2. Key Results and Achievements</h3>
    <h4>Epic: Reporting Platform Improvements (EPIC-201)</h4>
    <p><b>Report items</b></p>
    <p>(ABC-1245) Feature delivery: we finalized backend pagination and connected it to UI filters. Feature is merged and ready for rollout.</p>
    <p>(ABC-1262) Task completion: we finished email template cleanup and aligned all section anchors for consistent rendering.</p>
    <p><b>Other completed work</b></p>
    <p>(ABC-1291) Improvement completion: we finished export retry logic and verified handling for temporary Jira API failures.</p>
    <p><b>High priority items</b></p>
    <p>(ABC-1421) Snapshot conflict handling remains in progress and is tracked as high priority for release readiness.</p>
    <p><b>Bugs summary</b></p>
    <p>3 trouble reports/issues are analyzed and closed, 2 currently in progress.</p>

    <h4>Epic: Quality and Automation (EPIC-188)</h4>
    <p>(ABC-1310) Improvement completion: we fixed unstable tests around weekly range selection and improved deterministic assertions.</p>
    <p>(ABC-1338) Task completion: we completed smoke checks for HTML generation in Outlook-compatible mode.</p>
    <p><b>High priority items</b></p>
    <p>No high-priority issues were active for this epic in the selected week.</p>
    <p><b>Bugs summary</b></p>
    <p>1 trouble report/issue is analyzed and closed, 1 currently in progress.</p>

    <h4>Epic: User Management Modernization (EPIC-233)</h4>
    <p>(ABC-1501) Subtask-only completion: the authentication cache invalidation subtask is finished, while parent feature (ABC-1490) remains in progress.</p>
    <p><b>High priority items</b></p>
    <p>(ABC-1490) Parent feature remains high priority due to dependency on production access rollout.</p>
    <p><b>Bugs summary</b></p>
    <p>No bug items were attached to this epic for the selected week.</p>

    <h4>Epic: Build and Infrastructure Hardening (EPIC-245)</h4>
    <p>(ABC-1555) Feature completion: we delivered secure artifact signing in the CI pipeline and verified package integrity checks.</p>
    <p>(ABC-1560) Improvement completion: we reduced build queue time by optimizing parallel job allocation.</p>
    <p><b>High priority items</b></p>
    <p>No high-priority issues were active for this epic in the selected week.</p>
    <p><b>Bugs summary</b></p>
    <p>2 trouble reports/issues are analyzed and closed, 0 currently in progress.</p>

    <h3>3. Next Week Plans</h3>
    <h4>Epic: Reporting Platform Improvements (EPIC-201)</h4>
    <ul>
      <li>(ABC-1419) Continue refactoring narrative block builder and finalize edge cases for missing epic links.</li>
      <li>(ABC-1421) Implement snapshot conflict handling for concurrent report generation.</li>
    </ul>
    <h4>Epic: Quality and Automation (EPIC-188)</h4>
    <ul>
      <li>(ABC-1430) Add regression suite for ordering persistence against previous reports.</li>
    </ul>
    <h4>Epic: User Management Modernization (EPIC-233)</h4>
    <ul>
      <li>(ABC-1490) Continue parent feature implementation after completed subtask integration.</li>
    </ul>
    <h4>Epic: Build and Infrastructure Hardening (EPIC-245)</h4>
    <ul>
      <li>(ABC-1572) Start rollout validation for artifact signing across all release branches.</li>
    </ul>

    <h3>4. Vacations (next 60 days)</h3>
    <ul>
      <li>Denis Mazur vacation 01.02.2026 - 14.02.2026</li>
      <li>Roman Evstigneev vacation 09.03.2026 - 22.03.2026</li>
      <li>Alexey Horaskin vacation 23.03.2026 - 05.04.2026</li>
    </ul>
  </body>
</html>
```

Console diff output example (not part of HTML report):

```text
[DIFF] ABC 26'w08 vs 26'w07
Epic: Reporting Platform Improvements (EPIC-201)
  - \x1b[31m(̶A̶B̶C̶-̶1̶1̶8̶7̶)̶ ̶L̶e̶g̶a̶c̶y̶ ̶p̶a̶r̶s̶e̶r̶ ̶c̶l̶e̶a̶n̶u̶p̶\x1b[0m
  + \x1b[32m(ABC-1402) Permission middleware migration completed\x1b[0m
    \x1b[37m(ABC-1419) Continue narrative block refactoring\x1b[0m
```

Formatting rules for console diff:
- removed/old line: red + strikethrough
- added/new line: green
- unchanged line: white/default
- this diff is printed to console only and is never rendered in HTML report body

## Approval
APPROVED:v1
