# Openpyxl Pin Update v1

## Summary
Problem: `requirements.txt` pins `openpyxl==3.2.0b1`, which is yanked on PyPI and produces install warnings. This can reduce reliability and confidence in dependency installs.

Goals:
- Update the `openpyxl` pin to a stable, non-yanked release.
- Keep the change minimal and confined to dependency pinning.

Non-goals:
- Updating other dependencies.
- Modifying application code or templates.
- Changing Python version support.

## Scope boundaries
In scope:
- Change the `openpyxl` version pin in `requirements.txt` to a stable, non-yanked release.

Out of scope:
- Any functional changes to Excel generation.
- Any new dependencies or transitive overrides.

## Assumptions + constraints
- No new dependencies without explicit approval (AGENTS.md).
- Diffs should be minimal and additive.
- Follow 3-role workflow (Architect → Approved spec → Developer → Reviewer).
- Tests must be run with `pytest tests`.

## Architecture
Components affected:
- Dependency pinning in `requirements.txt`.

Data flow:
- Dependency resolution via pip uses the updated pin.

## Interfaces / contracts
- `requirements.txt` line for `openpyxl` is updated to a specific stable version.
- Error handling: if the chosen version is not available for the current Python version, select the highest compatible stable release.

## Data model changes + migrations
- None.

## Edge cases + failure modes
- The chosen stable version is incompatible with Python 3.11; fallback to the highest compatible stable version.
- New version introduces runtime regressions; rollback by restoring prior pin (noting it is yanked).

## Security requirements
- No auth/authz changes.
- No user input changes.
- No secrets in logs.
- Dependency policy: do not introduce new dependencies.

## Performance requirements + limits
- No runtime performance impact expected.

## Observability
- No new logging.
- Monitor pip install output to confirm no yank warning.

## Test plan
- Run `pytest tests`.

## Rollout plan + rollback plan
- Rollout: update `requirements.txt`, reinstall dependencies, run tests.
- Rollback: revert the `openpyxl` pin to the previous value and rerun tests.

## Acceptance criteria checklist
- `requirements.txt` pins `openpyxl` to a stable, non-yanked release.
- `pytest tests` passes.
- No new dependencies added.

## Approval
REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
