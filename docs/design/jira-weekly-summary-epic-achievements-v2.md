# Design Spec - Jira Weekly Summary Epic Achievements (v2)

## 1) Summary

### Problem statement

The current `jira_weekly` `Summary` fixed missing epic coverage and parent/subtask attribution, but the output is still not good enough for reporting:

- some important delivered results do not appear in the final bullets even though they are visible in `Epic Progress`;
- the final text is often over-trimmed, which produces incomplete or weak-looking sentences;
- aggressive cleanup removes not only noise but also useful technical evidence that should become part of the achievement summary;
- when a parent task stays open and only subtasks are closed, the current summary does not reliably foreground the subtask names that actually describe the delivered work.

The target report should read like team achievements for the period: what exactly was delivered, which subtask or feature part was completed, and what measurable result was achieved when comments provide metrics such as percentage improvement, latency change, memory reduction, or similar outcome data.

### Goals

- Keep the new epic and parent-task grouping model from v1.
- Produce fuller, more natural achievement bullets instead of heavily compressed text.
- Preserve meaningful metrics and quantified results from Jira comments.
- For parent tasks with resolved subtasks, explicitly include subtask names in the summary bullet.
- Prefer the latest meaningful comment of each resolved subtask as evidence, because that usually contains the final delivery/result statement.
- Continue to include open parent tasks in summary when they contain resolved subtasks during the period.
- Keep cleanup strong enough to remove markup and links, but soft enough to avoid deleting useful content.

### Non-goals

- No changes to `List View`.
- No weekly Excel changes.
- No second AI pass whose only purpose is to rewrite already generated prose.
- No changes to `jira_comprehensive` summary behavior in this scope.

## 2) Scope boundaries

### In scope

- `jira_weekly` Word `Summary` only.
- Evidence selection for parent-task groups.
- Prompt redesign for longer, result-focused bullets.
- Lighter final cleanup rules.
- Regression coverage for metrics preservation and unfinished-sentence avoidance.

### Out of scope

- `Epic Progress` rendering rules.
- `jira_weekly_email`.
- Jira transport/auth changes.

## 3) Assumptions + constraints

- Repo workflow remains design-first for this new scope change.
- Existing AI providers must be reused.
- No new dependencies.
- If AI fails, deterministic fallback must still produce usable achievement bullets.
- External guidance for project status reports consistently emphasizes accomplishments and metrics first, with concise but not content-starved summaries.

## 4) Research-based reporting principles

The updated design follows these patterns from external project-report guidance:

- Atlassian: status reports should highlight achievements and milestones and quantify impact when possible.
- Atlassian: weekly status reports should focus on results rather than hours spent.
- Asana: executive/progress summaries should capture completed deliverables, measurable achievements, and high-level insights.
- MIT weekly template: accomplishments should remain the primary section, with risks and next steps separated instead of being mixed into accomplishment bullets.

Design implication:

- the weekly `Summary` should prioritize delivered work and measurable outcomes;
- bullet quality matters more than keeping every bullet to 1-2 tiny sentences;
- losing an important achievement is worse than producing a slightly longer bullet.

## 5) Architecture

### Keep the v1 grouping model

Retain the v1 group key:

- `epic -> anchor parent task`

Where:

- resolved subtasks belong to the parent anchor;
- a resolved parent task is also its own anchor;
- open parent + resolved subtasks must still create a summary bullet.

### Replace "comment facts" with "achievement evidence"

The current `comment_facts` model is too lossy. Replace it with richer group evidence:

- `anchor_title`
- `anchor_description`
- `resolved_subtasks`: list of resolved subtasks for this parent
- `resolved_parent`: optional flag/details if parent itself was resolved
- `latest_meaningful_comment_per_resolved_item`
- `metric_hints`: extracted numeric/measurable phrases

### Evidence selection rules

For each parent-task group:

1. If the group contains resolved subtasks:
   - keep every resolved subtask title;
   - for each resolved subtask, take the latest meaningful Jira comment in period;
   - use the subtask title as the main carrier of "what was done";
   - use the comment mainly as the carrier of "what result/impact was achieved".
2. If the parent task itself was resolved:
   - include the parent title;
   - use the latest meaningful parent comment and parent description as supporting context.
3. If a comment contains metrics, explicitly preserve them:
   - `%`
   - `ms`
   - `s`
   - `MB`, `GB`, `KB`
   - `fps`
   - counts like APIs/tests/issues
   - similar numeric outcome phrases.

### Meaningful comment detection

The "latest meaningful comment" filter must ignore comments that are mostly:

- links only
- attachment markers only
- code/log dumps without delivery/result explanation
- templated report wrappers
- empty cleanup residue

But it must preserve comments that contain:

- result statements
- completion statements
- measured improvements
- behavior changes
- coverage/test completion notes

### Prompt model

The new prompt should present the input as structured achievement evidence rather than a flattened fact bag.

Each AI item should contain:

- epic name
- parent task title
- parent status
- parent description
- resolved subtasks:
  - subtask title
  - latest meaningful comment
- optional parent result comment
- extracted metrics

The prompt should explicitly ask for:

- one achievement paragraph per parent group;
- 2-4 complete sentences when needed;
- first sentence: what was delivered;
- second/third sentence: key result details or metrics;
- explicit mention of subtask names when they are the delivered units;
- no links, file paths, UNC paths, filenames, Jira markup, PR/MR references, or repo noise.

### Final cleanup strategy

Do not add a second AI cleanup request.

Instead:

- pre-AI cleanup should remove obvious markup and unsafe noise but preserve useful words and numbers;
- post-AI cleanup should only normalize residual artifacts;
- final truncation must be much softer:
  - prefer preserving complete sentences;
  - increase length budget materially;
  - if truncation is unavoidable, end with `...`, not a fake-complete sentence.

## 6) Interfaces/contracts

### Group evidence shape

Proposed internal structure:

```json
{
  "id": "EPIC-1::FEATURE-42",
  "epic_name": "Rendering Engine",
  "anchor_title": "Component teardown stability",
  "anchor_status": "In Progress",
  "anchor_description": "Parent feature context.",
  "resolved_subtasks": [
    {
      "title": "Finalize lifecycle cleanup",
      "latest_comment": "Cleanup now releases detached nodes and reduces memory usage by 18%."
    },
    {
      "title": "Add teardown regression coverage",
      "latest_comment": "Regression scenario for repeated mount/unmount was fixed and covered by tests."
    }
  ],
  "parent_result_comment": "",
  "metric_hints": [
    "memory usage reduced by 18%"
  ]
}
```

### Prompt contract

Prompt requirements:

1. Describe delivered achievements for the parent task group.
2. Mention resolved subtask names when they are the actual shipped units.
3. Preserve measurable outcomes when present.
4. Use the comment as supporting evidence, not as raw quoted text.
5. Write 2-4 complete sentences when needed.
6. Return strict JSON only.

### Fallback contract

If AI is unavailable:

- fallback text should still include:
  - parent title
  - resolved subtask titles
  - first useful metric/result phrase when present
- fallback must not collapse to a single generic sentence unless evidence is truly weak.

## 7) Data model changes + migrations

- No migrations.
- Replace or expand current group fields:
  - from `comment_facts`
  - to richer resolved-subtask evidence and metric hints.

## 8) Edge cases + failure modes

- Parent open, multiple subtasks resolved:
  - bullet must still be created and must name the resolved subtasks.
- Parent and subtasks both resolved:
  - one combined bullet, but parent completion must not erase subtask detail.
- Comments contain both result text and code block:
  - keep the result text, drop the code block.
- Comment ends with artifact garbage after cleanup:
  - normalize the residue without dropping the useful sentence.
- Metric appears only once in a long comment:
  - keep it if it is tied to delivered work.
- Weak comments but strong subtask titles:
  - summary can rely mainly on subtask titles and parent title.

## 9) Security requirements

- Keep stripping links, paths, attachment markers, repo references, and Jira markup.
- Do not log raw AI payloads containing sensitive config.
- Preserve numbers and result statements unless they are clearly part of a path or dump.

## 10) Performance requirements + limits

- Group-building still linear over weekly resolved items.
- Comment selection should prefer latest meaningful entries without scanning more than necessary.
- Metric extraction must be lightweight regex-based parsing.

## 11) Observability

Add logs for:

- number of groups using subtask-driven evidence;
- number of latest comments accepted vs rejected as non-meaningful;
- number of groups with extracted metric hints;
- AI vs fallback usage counts.

## 12) Test plan

### Coverage targets

`tests/test_jira_weekly_report.py`

- parent open + resolved subtasks still appears in summary and names subtasks;
- measurable outcomes such as `%`, `ms`, `MB`, counts remain in summary when present;
- final summary text does not end mid-thought after truncation;
- Jira markup and artifact garbage are removed without losing the actual result statement;
- `Epic Progress` completed items that form the summary evidence are not silently dropped from `Summary`.

### Verification commands

- focused: `pytest tests/test_jira_weekly_report.py`
- full: `pytest tests`

## 13) Rollout plan + rollback plan

### Rollout

1. Replace lossy `comment_facts` aggregation with subtask-centric achievement evidence.
2. Redesign weekly summary prompt for longer result-oriented bullets.
3. Soften final truncation and cleanup.
4. Add regression tests for metrics preservation and summary completeness.
5. Run focused and full verification.

### Rollback

1. Restore the current v1 weekly summary text builder.
2. Keep existing epic/parent enrichment unchanged.

## 14) Acceptance criteria checklist

- [ ] Summary bullets can be longer and remain grammatically complete.
- [ ] Parent groups with resolved subtasks explicitly mention subtask names.
- [ ] Important metrics and measurable results from comments are preserved in summary.
- [ ] Open parent tasks with resolved subtasks still appear in summary.
- [ ] Cleanup removes markup/artifacts without removing meaningful achievement text.
- [ ] `List View` and other weekly sections remain unchanged.
- [ ] Focused and full pytest verification pass.

## Approval

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"

APPROVED:v1
