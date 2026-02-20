# Implementation Plan — Jira Comprehensive Monthly Summary (v1)

## Objective
Deliver `Summary` section for `jira_comprehensive` monthly report with AI-assisted concise achievements per epic, plus mandatory planned-task/bug counters.

## Work breakdown (Lead Developer Decomposition)

### EPIC A — Data preparation
Task A1 — Enrich issue evidence with latest comment  
- Update Jira fetch pipeline to store `Last_Comment` per issue.
- Ensure deterministic selection of latest comment by created timestamp/order.

Task A2 — Build summary grouping model  
- Implement `build_monthly_summary_df(...)`:
  - filter resolved + countable issues;
  - group by epic;
  - split planned issues (non-bug/non-epic) vs bugs;
  - collect per-task evidence fields:
    - `Issue_Key`, `Summary`, `Description`, `Last_Comment`.

### EPIC B — AI summarization pipeline
Task B1 — Prompt engineering for weak model (`gpt-oss-120b`)  
- Create explicit prompt with:
  - role context (ArkUI/OpenHarmony monthly delivery),
  - strict format rules (1-2 sentences),
  - result-oriented language constraints,
  - explicit exclusions (URLs, PR/MR, commits, Jira IDs),
  - strict JSON-only output requirement.

Task B2 — Provider adapters (reuse weekly-email transport model)  
- Implement:
  - Ollama batch rewrite (`/api/generate`);
  - Open WebUI batch rewrite (`/api/chat/completions`);
  - provider selection via `ai_provider` and existing section flags.

Task B3 — Deterministic fallback  
- If AI unavailable/invalid:
  - generate concise fallback achievement from title+latest comment/description.

### EPIC C — Report output integration
Task C1 — Add `Summary` sheet export  
- Extend `export_to_excel(...)` signature and write `Summary` sheet.
- Preserve existing sheet generation unchanged.

Task C2 — Final epic summary composition  
- Per epic:
  - bullet list of task achievements,
  - append mandatory line: `Resolved xx planned tasks on time.`,
  - append optional line: `Resolved xx reported issues.` when bug count > 0.

### EPIC D — Verification
Task D1 — Update integration test expectations  
- Extend existing comprehensive report test to assert:
  - `Summary` sheet exists,
  - epic counter lines exist and counts are correct.

Task D2 — Full regression  
- Run full suite:
  - `pytest tests`

## Dependency graph
1. A1 -> A2  
2. A2 -> B3  
3. B1 -> B2  
4. B2 + B3 -> C2  
5. C2 -> C1  
6. C1 -> D1  
7. D1 -> D2

## Risk list
- R1: weak model emits malformed JSON.  
  Mitigation: strict extraction + fallback, non-fatal warnings.
- R2: verbose/low-quality AI output.  
  Mitigation: explicit constraints + post-sanitization.
- R3: regressions in existing workbook sheets.  
  Mitigation: keep additive-only sheet write and existing assertions.

## Test matrix
- T1: Summary sheet presence.
- T2: Planned task counter line correctness per epic.
- T3: Bug counter line appears only when bug count > 0.
- T4: Summary still generated when AI model not configured.
- T5: Full report regression (`Issues`, `Links`, `Results`, performance sheets intact).

## Exit criteria
- All acceptance points from design spec are met.
- `pytest tests` passes.
- No new dependencies introduced.

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
