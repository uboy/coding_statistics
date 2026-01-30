# Repo Agent Guide (AGENTS.md)

## Project Summary
- Name: coding_statistics
- Stack: Python CLI toolkit (pandas, requests, jira, openpyxl, python-docx)
- Package manager: pip (requirements.txt)

## Repo Map (top dirs)
- stats_core/ — core CLI, sources, reports, export, cache
- reports/ — generated report outputs (docx/xlsx)
- templates/ — Word/Excel templates
- tests/ — pytest suite
- .vscode/ — editor settings

## Commands
- Install: `pip install -r requirements.txt`
- Tests: `pytest tests`
- Lint: TODO (no linter configured)
- Typecheck: TODO (no type checker configured)
- Build (binary): `build_stats_tool.cmd` (Windows) / `./build_stats_tool.sh` (Linux/macOS)

## Change Policy
- Keep diffs minimal and additive
- No new dependencies without explicit approval
- No secrets/tokens/credentials in repo or logs
- No drive-by refactors unrelated to the task
- Follow the 3-role workflow: Architect -> Approved spec -> Developer -> Reviewer

## Definition of Done
- Requirements implemented exactly as approved spec
- Tests/verification commands run and pass (or deviations explicitly documented)
- No regressions or unrelated changes
- Security review completed (authn/authz, inputs, injection, secrets/logging, deps)
- Acceptance criteria mapped to evidence
