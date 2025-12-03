from __future__ import annotations

import pandas as pd

from stats_core.reports.jira_utils import mark_reassigned_tasks


def test_not_reassigned_when_final_assignee_logged_time():
    df = pd.DataFrame(
        [
            {
                "Issue_key": "ABC-1",
                "Assignee": "John Smith",        # worklog author
                "Final_Assignee": "John Smith",  # Jira assignee
            }
        ]
    )

    result = mark_reassigned_tasks(df)
    assert bool(result.loc[0, "Reassigned"]) is False


def test_reassigned_when_final_assignee_never_logged_time():
    df = pd.DataFrame(
        [
            {
                "Issue_key": "ABC-2",
                "Assignee": "John Smith",          # worklog author
                "Final_Assignee": "Another User",  # Jira assignee
            }
        ]
    )

    result = mark_reassigned_tasks(df)
    assert bool(result.loc[0, "Reassigned"]) is True


