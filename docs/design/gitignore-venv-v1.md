# Gitignore Venv Exclusion v1

## Summary
Problem: The `.venv` directory is created locally for development and should not be tracked in git. It is currently not guaranteed to be ignored.

Goals:
- Ensure `.venv` is ignored by git for this repository.

Non-goals:
- Changing any other ignore patterns.
- Modifying source code or dependencies.

## Scope boundaries
In scope:
- Update `.gitignore` to include `.venv`.

Out of scope:
- Any other repository hygiene changes.

## Assumptions + constraints
- Diffs should be minimal and additive.
- No new dependencies.
- Follow 3-role workflow (Architect → Approved spec → Developer → Reviewer).
- Tests must be run with `pytest tests`.

## Architecture
Components affected:
- `.gitignore` file

Data flow:
- Git ignore rules prevent `.venv` from being tracked.

## Interfaces / contracts
- `.gitignore` includes a line that ignores `.venv/`.
- Error handling: none (git ignore rule change).

## Data model changes + migrations
- None.

## Edge cases + failure modes
- Existing tracked `.venv` would still be tracked; may require `git rm --cached` if it was committed.

## Security requirements
- No auth/authz changes.
- No user input changes.
- No secrets in logs.
- Dependency policy unchanged (no new deps).

## Performance requirements + limits
- None.

## Observability
- No logging changes.

## Test plan
- Run `pytest tests`.

## Rollout plan + rollback plan
- Rollout: update `.gitignore` to include `.venv/`.
- Rollback: remove the `.venv/` ignore entry.

## Acceptance criteria checklist
- `.gitignore` ignores `.venv/`.
- `pytest tests` passes.

## Approval
REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
