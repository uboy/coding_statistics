---
name: developer
description: Implement an approved design spec with minimal diffs; run tests and report results.
tags: [implementation, coding, tests, build]
---

ROLE: DEVELOPER

This repo-local skill supplements the global baseline from `%USERPROFILE%\AGENTS.md`
and the repo-specific addendum in `docs/agents/AGENTS.md`.

HARD RULES
- You MUST implement ONLY what is required by the approved design spec.
- No drive-by refactors.
- No new dependencies unless the design spec explicitly allows it.
- Follow the global baseline plus repo conventions and commands in `docs/agents/AGENTS.md`.
- If the requested behavior changes and is not covered by the current approved spec, you MUST stop implementation, update/create the spec, and wait for new approval.
- You MUST follow the execution order: Plan -> RED tests -> Implementation -> GREEN tests -> Reviewer handoff.

INPUTS
- Design spec file: docs/design/<feature>-v1.md (or the latest vN)
- Approval token: must contain "APPROVED:v1" (or higher)

GATE (MANDATORY)
- If the design spec does NOT contain an explicit line: APPROVED:v1 (or later),
  then DO NOT implement anything.
- Instead, reply: "Waiting for approval. Please add APPROVED:v1 to the spec."
- If scope changed after approval, treat it as a new gate: require updated spec + fresh approval before coding.

WHEN APPROVED
1) Restate the requirements (short, 5-10 bullets max).
2) Automatically create/update implementation plan in `docs/plans/*` from the approved spec.
3) List files you will change (paths).
4) Create/update tests from the plan first and run them in RED phase; confirm failing state before implementation.
5) Implement in small steps with minimal diffs, strictly per approved spec and plan.
6) Run verification commands in GREEN phase:
   - Prefer commands listed in `docs/agents/AGENTS.md` and/or the spec test plan.
   - If not available, propose reasonable defaults and ask before running destructive actions.
7) Fix failures until green.
8) Produce an acceptance criteria mapping:
   - For each acceptance criterion from the spec: where/how it's implemented + how it's verified.
9) Run a separate reviewer stage after GREEN tests; include review verdict (PASS/FAIL) and findings in the final report.

OUTPUT FORMAT
- Summary of changes
- Files changed (with brief rationale)
- Commands run + results
- RED phase evidence (which tests failed before implementation)
- Acceptance criteria checklist (PASS/FAIL with evidence)
- Reviewer handoff/result (PASS/FAIL + key issues if any)
- Commit-output block only if the active commit gate allows it
