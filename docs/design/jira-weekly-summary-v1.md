# Design Spec — Jira Weekly Summary Section (v1)

## 1) Summary
### Problem statement
`jira_weekly` currently provides detailed sections (`Table View`, `List View`, `Engineer Weekly Activity`, `Epic Progress`, `Resolved Tasks`), but it does not provide an executive weekly `Summary` by epic with concise result-oriented statements.

### Goals
- Add a new `Summary` section to weekly report (Word output) grouped by epic.
- Use resolved tasks/subtasks in selected week period as source evidence.
- For each resolved planned task/subtask:
  - use task title,
  - description,
  - latest comment in period.
- Generate short achievement statements (1-2 sentences) using AI.
- Reuse AI transports from weekly email:
  - Ollama
  - Open WebUI
- For each epic, append mandatory lines:
  - `Resolved xx planned tasks on time.`
  - if bugs present: `Resolved xx reported issues.`

### Non-goals
- No changes to `jira_comprehensive` report behavior.
- No new output formats for `jira_weekly`.
- No replacement of existing weekly sections.
- No new dependencies.

## 2) Scope boundaries
### In scope
- `jira_weekly` Word report only.
- New `Summary` section insertion.
- AI/fallback generation for summary bullets.
- Weekly aggregation semantics based on resolved snapshot in period.

### Out of scope
- Excel output structural changes for weekly report.
- Reworking existing `Epic Progress`/`Resolved Tasks` hierarchy logic.
- Jira API/auth model changes.

## 3) Assumptions + constraints
- Process and repo constraints from `AGENTS.md`:
  - minimal additive diffs,
  - no new dependencies,
  - full `pytest tests` run required.
- Weekly report uses existing period arguments `start/end`.
- Weak AI model scenario (`gpt-oss-120b`) is expected:
  - prompt must be explicit, constrained, and schema-bound.
- Existing Jira extraction already provides resolved task hierarchy and activity datasets.

## 4) Architecture
### Components
- `stats_core/reports/jira_weekly.py`:
  - orchestrates new summary build and renders section in Word.
- `stats_core/reports/jira_utils.py`:
  - extend/enrich evidence rows with description and latest comment in period.
- New summary module (or additive functions in weekly report module):
  - `build_weekly_summary_payload(...)`
  - `rewrite_weekly_summary_with_ai(...)`
  - `add_summary_section_to_document(...)`

### Data flow
1. Fetch weekly Jira snapshots (existing flow).
2. Build resolved-in-period dataset (existing resolved snapshot + enrichment).
3. Group by epic:
  - planned resolved tasks/subtasks (non-bug, non-epic),
  - resolved bug count.
4. For each planned item, create concise achievement via AI (or deterministic fallback).
5. Render per-epic summary bullets + mandatory count lines into Word section.

## 5) Interfaces/contracts
### Public report behavior
- Report name remains `jira_weekly`.
- New Word section heading: `Summary`.
- Section layout:
  - Epic heading
  - bullet list of concise achievements
  - mandatory count lines:
    - `Resolved xx planned tasks on time.`
    - conditional bug line.

### AI provider parameters (same style as weekly email)
- `ai_provider` (`ollama` | `webui`)
- Ollama:
  - `ollama_enabled`, `ollama_url`, `ollama_model`, `ollama_timeout_seconds`, `ollama_temperature`, `ollama_api_key`
- WebUI:
  - `webui_enabled`, `webui_url`, `webui_endpoint`, `webui_model`,
  - `webui_timeout_seconds`, `webui_connect_timeout_seconds`, `webui_temperature`, `webui_api_key`

### Internal function contracts
- `build_weekly_summary_payload(resolved_df: pd.DataFrame, comments_df: pd.DataFrame) -> list[dict[str, Any]]`
- `rewrite_weekly_summary_with_ai(items: list[dict[str, str]], config: ConfigParser, extra_params: dict[str, Any]) -> dict[str, str]`
- `add_summary_section_to_document(document: Document, summary_payload: list[dict[str, Any]]) -> None`

### Error handling strategy
- AI errors must not fail report generation.
- On provider/model/config errors:
  - log warning,
  - deterministic fallback text per item.

## 6) Data model changes + migrations
- No database migrations.
- Runtime dataframe enrichment:
  - add `Description` and `Last_Comment` fields for summary evidence where needed.
- Word document structure change:
  - insert `Summary` section.

## 7) Edge cases + failure modes
- Epic with no planned tasks but resolved bugs:
  - no task bullets, only required count lines.
- Epic with planned tasks but no comments:
  - fallback from title + description.
- Task without epic:
  - group under `Unknown Epic`.
- AI malformed JSON/truncated response:
  - ignore rewritten output for that batch, use fallback.
- No resolved tasks in week:
  - section contains explicit no-data message.

## 8) Security requirements
- Existing Jira auth model unchanged.
- AI output sanitization required:
  - strip URLs/PR/MR/commit hashes/Jira keys from summary sentences.
- Secrets policy:
  - API keys must not appear in logs.
- Dependency policy:
  - no new packages.

## 9) Performance requirements + limits
- Summary grouping complexity: `O(n)` by resolved rows in weekly window.
- AI batching to avoid oversized prompts.
- Expected weekly volumes are moderate; section generation should not materially increase runtime.

## 10) Observability
- Add logs:
  - summary epics count,
  - summary planned tasks count,
  - summary bug count,
  - AI rewritten vs fallback counts,
  - provider and non-fatal batch errors.

## 11) Test plan
### Unit/integration coverage
- `tests/test_jira_weekly_report.py`:
  - Word output contains `Summary` section.
  - Per epic includes mandatory planned-task line.
  - Bug line appears only when resolved bugs exist.
  - Task bullet text present and concise.
  - No regressions in existing sections.
- AI fallback coverage:
  - missing model/unavailable provider still produces summary.
- Provider routing coverage:
  - `ai_provider=webui` and default/ollama branch selection.

### Verification commands
- Full suite:
  - `pytest tests`

## 12) Rollout plan + rollback plan
### Rollout
1. Add summary payload builder + document renderer.
2. Add AI rewrite adapter reusing weekly-email transport pattern.
3. Add tests for summary section and counters.
4. Run full regression suite.

### Rollback
1. Revert summary section generation and rendering.
2. Keep all existing weekly report sections unchanged.

## 13) Acceptance criteria checklist
- [ ] Weekly Word report includes new `Summary` section.
- [ ] Summary is grouped by epic.
- [ ] Each planned resolved task/subtask has 1-2 sentence achievement text.
- [ ] Each epic includes `Resolved xx planned tasks on time.`
- [ ] Epic bug line `Resolved xx reported issues.` appears only when applicable.
- [ ] AI processing supports Ollama and Open WebUI with deterministic fallback.
- [ ] Existing weekly report outputs remain stable.
- [ ] Full test suite passes.

## Approval
REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
