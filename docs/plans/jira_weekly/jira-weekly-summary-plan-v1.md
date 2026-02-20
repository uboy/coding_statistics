# Implementation Plan — Jira Weekly Summary Section (v1)

## Objective
Add an AI-assisted `Summary` section to `jira_weekly` Word report with epic-level concise achievements and mandatory counters.

## Lead-dev decomposition

### EPIC A — Evidence readiness
Task A1 — Extend weekly evidence for summary  
- Ensure resolved weekly rows have required fields:
  - `Summary`, `Description`, `Last_Comment`, `Type`, `Epic_Link`, `Epic_Name`, `Parent_Key`.
- Reuse `resolved_issues_df` as primary source, enrich with activity comments if needed.

Task A2 — Build weekly summary payload  
- Group resolved items by epic.
- Split:
  - planned resolved tasks/subtasks (non-bug, non-epic),
  - resolved bugs count.
- Prepare per-item AI input payload and deterministic fallback text.

### EPIC B — AI rewrite pipeline (weekly)
Task B1 — Prompt design for weak model  
- Highly explicit prompt:
  - software context (ArkUI/OpenHarmony),
  - strict 1-2 sentence output,
  - result-focused phrasing,
  - exclusions (links/PR/MR/commits/Jira IDs),
  - strict JSON-only map output.

Task B2 — Provider adapters  
- Add provider router (`ai_provider`) with two backends:
  - Ollama (`/api/generate`)
  - Open WebUI (`/api/chat/completions`)
- Mirror safety/timeout/header handling style used in `jira_weekly_email`.

Task B3 — Fallback strategy  
- If provider/model/response invalid:
  - keep non-fatal behavior,
  - use deterministic short achievement text.

### EPIC C — Weekly Word rendering
Task C1 — Insert `Summary` section  
- Add heading and epic groups in `jira_weekly` Word flow.
- Render:
  - bullet achievement lines per planned task/subtask,
  - `Resolved xx planned tasks on time.`,
  - optional `Resolved xx reported issues.`

Task C2 — Keep existing sections stable  
- Ensure order and behavior of existing sections remain unchanged except new section insertion.

### EPIC D — Test/verification
Task D1 — Update weekly tests  
- Add assertions for:
  - Summary heading presence,
  - epic-level counters,
  - conditional bug line,
  - fallback behavior.

Task D2 — Full regression run  
- Execute full repository test suite.

## Dependencies / sequence
1. A1 -> A2
2. A2 -> B3
3. B1 -> B2
4. B2 + B3 -> C1
5. C1 -> C2
6. C2 -> D1
7. D1 -> D2

## Risk matrix
- R1: weak AI model returns malformed/truncated JSON  
  Mitigation: strict parser + fallback.
- R2: summary text drifts to technical noise  
  Mitigation: explicit prompt constraints + post-sanitization.
- R3: regression in weekly word formatting  
  Mitigation: additive insertion and tests on section presence/content.

## Test matrix
- T1: summary section appears in weekly Word report.
- T2: per-epic planned-task counter line is correct.
- T3: bug counter line appears only when bug count > 0.
- T4: no-model or provider failure still yields summary lines.
- T5: existing weekly tests remain green.
- T6: full `pytest tests` pass.

## Exit criteria
- Approved spec acceptance criteria mapped to implementation.
- All tests pass in full suite.
- No new dependencies.

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
