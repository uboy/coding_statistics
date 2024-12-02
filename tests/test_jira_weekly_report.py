import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime
import os
from jira_weekly_report import get_all_worklogs, fetch_jira_data, generate_report


class TestJiraReport(unittest.TestCase):

    @patch("main_script.JIRA")
    def test_get_all_worklogs(self, mock_jira):
        """Test fetching all worklogs for an issue."""
        mock_session = MagicMock()
        mock_session.get.side_effect = [
            MagicMock(
                json=lambda: {
                    "worklogs": [{"id": "1", "started": "2024-11-01T10:00:00.000+0000"}],
                    "total": 1,
                }
            )
        ]
        mock_jira._session = mock_session
        mock_jira._options = {"server": "https://jira.example.com"}

        worklogs = get_all_worklogs(mock_jira, "TEST-123")
        self.assertEqual(len(worklogs), 1)
        self.assertEqual(worklogs[0]["id"], "1")

    @patch("main_script.JIRA")
    def test_fetch_jira_data(self, mock_jira):
        """Test fetching and filtering data from JIRA."""
        mock_issue = MagicMock()
        mock_issue.key = "TEST-123"
        mock_issue.fields = MagicMock(
            assignee=MagicMock(displayName="John Doe"),
            summary="Test issue",
            resolutiondate="2024-11-05T00:00:00.000+0000",
            updated="2024-11-10T00:00:00.000+0000"
        )

        mock_jira.search_issues.return_value = [mock_issue]

        def mock_get_all_worklogs(_, issue_key):
            if issue_key == "TEST-123":
                return [{"started": "2024-11-03T00:00:00.000+0000"}]
            return []

        with patch("main_script.get_all_worklogs", mock_get_all_worklogs):
            data = fetch_jira_data(mock_jira, "TEST", "2024-11")

        self.assertEqual(len(data), 2)
        self.assertTrue(any(data["Status"] == "Resolved"))
        self.assertTrue(any(data["Status"] == "In progress"))

    @patch("main_script.Document")
    @patch("main_script.pd.ExcelWriter")
    def test_generate_report(self, mock_excel_writer, mock_document):
        """Test generating reports in Excel and Word formats."""
        data = pd.DataFrame({
            "Assignee": ["John Doe", "John Doe"],
            "Week": ["2024-W45", "2024-W46"],
            "Status": ["Resolved", "In progress"],
            "Issue key": ["TEST-123", "TEST-456"],
            "Summary": ["Resolved Task", "In Progress Task"],
            "URL": ["https://jira.example.com/browse/TEST-123", "https://jira.example.com/browse/TEST-456"],
        })

        mock_writer_instance = MagicMock()
        mock_excel_writer.return_value = mock_writer_instance

        generate_report(data, "2024-11", "TEST")

        # Check Excel file was written
        mock_writer_instance.__enter__.assert_called()
        mock_writer_instance.sheets.__getitem__.assert_called_with("Report")

        # Check Word document was created
        mock_document.return_value.save.assert_called_once()
        self.assertTrue(mock_document.return_value.save.call_args[0][0].endswith(".docx"))

    def tearDown(self):
        """Clean up after tests."""
        for file in os.listdir():
            if file.startswith("jira_report_TEST_") and (file.endswith(".xlsx") or file.endswith(".docx")):
                os.remove(file)


if __name__ == "__main__":
    unittest.main()
