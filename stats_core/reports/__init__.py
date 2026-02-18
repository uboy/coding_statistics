"""
Report registry and base classes.
"""

from . import registry  # noqa: F401
# ensure built-in reports register themselves
from . import jira_weekly  # noqa: F401
from . import jira_comprehensive  # noqa: F401
from . import jira_weekly_email  # noqa: F401
from . import unified_review  # noqa: F401

__all__ = ["registry"]

