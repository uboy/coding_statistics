# Repo Agent Guide (AGENTS.md)

## Project Summary
- Name: coding_statistics
- Stack: Python CLI toolkit (pandas, requests, jira, openpyxl, python-docx)
- Package manager: pip (requirements.txt)

## Repo Map (top dirs)
- stats_core/ — core CLI, sources, reports, export, cache
- reports/ — generated report outputs (docx/xlsx/html + snapshots)
- templates/ — Word/Excel templates
- tests/ — pytest suite
- .vscode/ — editor settings

## Built-in Reports
- jira_weekly
- jira_comprehensive
- jira_weekly_email
- unified_review

## Commands
- Install: `pip install -r requirements.txt`
- Tests: `pytest tests`
- Lint: TODO (no linter configured)
- Typecheck: TODO (no type checker configured)
- Build (binary): `scripts/build/build_stats_tool.cmd` (Windows) / `./scripts/build/build_stats_tool.sh` (Linux/macOS)

## Change Policy
- Keep diffs minimal and additive
- No new dependencies without explicit approval
- No secrets/tokens/credentials in repo or logs
- No drive-by refactors unrelated to the task
- Follow the mandatory workflow: Architect -> Approved spec -> Developer (plan + red/green tests + implementation) -> Reviewer
- Mandatory process for every feature/change request:
  - Step 1: create/update design spec only (`docs/design/*`); do not create implementation plan before approval.
  - Step 2: get explicit approval token (`APPROVED:v1` or later).
  - Step 3: automatically create/update implementation plan (`docs/plans/*`) from the approved spec.
  - Step 4: automatically create/update tests per plan and run them in RED phase (new/updated tests must fail before implementation).
  - Step 5: implement strictly within approved spec scope and plan.
  - Step 6: run verification in GREEN phase until tests pass.
  - Step 7: run separate reviewer stage/agent after GREEN tests and capture PASS/FAIL verdict.
  - If requirements changed, implementation must stop until spec is updated and re-approved.
- Keep `README.md`, `docs/specs/common/SPEC.md`, and relevant design docs in sync when adding/changing report capabilities

## Definition of Done
- Requirements implemented exactly as approved spec
- Tests/verification commands run and pass (or deviations explicitly documented)
- No regressions or unrelated changes
- Security review completed (authn/authz, inputs, injection, secrets/logging, deps)
- Acceptance criteria mapped to evidence
