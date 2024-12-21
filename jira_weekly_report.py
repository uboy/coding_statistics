from jira import JIRA
from configparser import ConfigParser
import pandas as pd
from datetime import datetime, timedelta
import argparse
import codecs
import os
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import load_workbook

# Configuration constants
CONFIG_FILE = "config.ini"
CONFIG_SECTION = "jira"
CONFIG_URL = "jira-url"
CONFIG_USERNAME = "username"
CONFIG_PASSWORD = "password"

def parse_arguments_and_config():
    """
    Parse command-line arguments and configuration file to retrieve JIRA credentials and project details.
    """
    parser = argparse.ArgumentParser(description="Generate JIRA monthly report with extended filtering.")
    parser.add_argument("-c", "--config", default=CONFIG_FILE, help="Path to config file.")
    parser.add_argument("-u", "--username", help="JIRA username.")
    parser.add_argument("-p", "--password", help="JIRA password.")
    parser.add_argument("-l", "--url", help="JIRA base URL.")
    parser.add_argument("-proj", "--project", required=True, help="JIRA project key.")
    parser.add_argument("-m", "--month", required=True, help="Month in YYYY-MM format (e.g., 2024-11).")
    parser.add_argument("--member-list-file", help="Path to Excel file with a list of required assignees.")
    args = parser.parse_args()

    # Load credentials from configuration file if not provided via command-line arguments
    config = ConfigParser(allow_no_value=False, comment_prefixes=('#', ';'), inline_comment_prefixes='#')
    config.read_file(codecs.open(args.config, 'r', encoding='utf-8-sig'))

    jira_url = args.url or config.get(CONFIG_SECTION, CONFIG_URL, fallback=None)
    jira_username = args.username or config.get(CONFIG_SECTION, CONFIG_USERNAME, fallback=None)
    jira_password = args.password or config.get(CONFIG_SECTION, CONFIG_PASSWORD, fallback=None)

    # Ensure all required credentials are provided
    if not jira_url or not jira_username or not jira_password:
        raise ValueError("JIRA URL, username, and password must be specified either as arguments or in the config file.")

    return jira_url, jira_username, jira_password, args.project, args.month, args.member_list_file


def read_member_list(member_list_file):
    """
    Read the list of required assignees from an Excel file.
    Assumes the assignee names are in column 'E'.
    """
    wb = load_workbook(member_list_file)
    sheet = wb.active
    assignee_column = 'E'

    # Extract all unique assignees from column 'E' starting from row 2
    assignees = [sheet[f"{assignee_column}{row}"].value for row in range(2, sheet.max_row + 1) if sheet[f"{assignee_column}{row}"].value]
    return list(set(assignees))


def get_all_worklogs(jira, issue_key):
    """
    Fetch all work logs for an issue using pagination.
    """
    worklogs = []
    start_at = 0
    while True:
        response = jira._session.get(
            f"{jira._options['server']}/rest/api/2/issue/{issue_key}/worklog",
            params={"startAt": start_at, "maxResults": 100}
        )
        response.raise_for_status()
        data = response.json()
        worklogs.extend(data.get("worklogs", []))
        if len(worklogs) >= data.get("total", 0):
            break
        start_at += 100
    return worklogs

def fetch_jira_data(jira, project, month):
    """
    Fetch data from JIRA and format it for the report.
    """
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = min(datetime.now(), (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))

    # Pagination variables
    start_at = 0
    max_results = 100
    all_issues = []

    # Fetch all issues updated during the specified period with pagination
    while True:
        jql_query = (
            f"project = {project}"
            #f"project = {project} AND updated >= '{start_date.strftime('%Y-%m-%d')}' AND updated <= '{end_date.strftime('%Y-%m-%d')}'"
        )
        issues = jira.search_issues(jql_query, startAt=start_at, maxResults=max_results, fields=[
            "key", "summary", "assignee", "resolutiondate", "updated", "customfield_10000", "parent"
        ])
        all_issues.extend(issues)
        if len(issues) < max_results:
            break
        start_at += max_results

    # Fetch all epic names
    epic_keys = list({getattr(issue.fields, "customfield_10000", None) for issue in all_issues if getattr(issue.fields, "customfield_10000", None)})
    epic_names = {}
    if epic_keys:
        epics = jira.search_issues(f"issuekey in ({', '.join(epic_keys)})", maxResults=1000, fields=["key", "summary"])
        epic_names = {epic.key: epic.fields.summary for epic in epics}

    data = []
    for issue in all_issues:
        key = issue.key
        summary = issue.fields.summary
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        resolved_date = issue.fields.resolutiondate
        epic_link = getattr(issue.fields, "customfield_10000", None)
        parent = getattr(issue.fields, "parent", None)
        parent_key = parent.key if parent else None
        parent_summary = parent.fields.summary if parent else None

        worklogs = get_all_worklogs(jira, key)
        worklog_dates = set()
        for log in worklogs:
            try:
                log_date = datetime.strptime(log["started"].split("T")[0], "%Y-%m-%d")
                if start_date <= log_date <= end_date:
                    worklog_dates.add(log_date)
            except Exception:
                continue

        resolved_week = None
        if resolved_date:
            resolved_date_dt = datetime.strptime(resolved_date.split("T")[0], "%Y-%m-%d")
            if start_date <= resolved_date_dt <= end_date:
                resolved_week = resolved_date_dt.strftime("%G-W%V")
                data.append({
                    "Issue_key": key,
                    "Summary": summary,
                    "Assignee": assignee,
                    "Status": "Resolved",
                    "Week": resolved_week,
                    "Epic Link": epic_link,
                    "Epic Name": epic_names.get(epic_link, "Unknown Epic"),
                    "Parent Key": parent_key,
                    "Parent Summary": parent_summary
                })

        for log_date in worklog_dates:
            log_week = log_date.strftime("%G-W%V")
            if log_week != resolved_week:
                if not any(d["Issue_key"] == key and d["Week"] == log_week for d in data):
                    data.append({
                        "Issue_key": key,
                        "Summary": summary,
                        "Assignee": assignee,
                        "Status": "In progress",
                        "Week": log_week,
                        "Epic Link": epic_link,
                        "Epic Name": epic_names.get(epic_link, "Unknown Epic"),
                        "Parent Key": parent_key,
                        "Parent Summary": parent_summary
                    })

    return pd.DataFrame(data)


def generate_epic_report(data):
    """
    Generate a summary of resolved tasks grouped by epics.
    """
    epic_data = data[data["Status"] == "Resolved"].dropna(subset=["Epic_Link"])
    grouped = epic_data.groupby("Epic_Link")

    epic_summary = []
    for epic, tasks in grouped:
        task_details = [
            {
                "Task Key": row["Issue_key"],
                "Task Summary": row["Summary"]
            }
            for _, row in tasks.iterrows()
        ]
        epic_summary.append({"Epic": tasks.iloc[0]["Epic_Name"], "Tasks": task_details})

    return epic_summary


def generate_week_headers(valid_weeks, data):
    """
    Generate table headers with week ranges for the report.
    Include only weeks with existing JIRA data and that have passed.
    """
    headers = []
    unique_weeks_with_data = set(data["Week"])

    for week in valid_weeks:
        if week in unique_weeks_with_data:
            year, week_num = map(int, week.split("-W"))
            week_start = pd.Timestamp.fromisocalendar(year, week_num, 1)
            week_end = week_start + timedelta(days=6)
            # Exclude future weeks
            if week_start <= datetime.now():
                headers.append(f"{week}({week_start.strftime('%d/%m')}-{week_end.strftime('%d/%m')})")
    return headers


def generate_file_suffix():
    """
    Generate a timestamp-based suffix for file names to ensure uniqueness.
    """
    now = datetime.now()
    return now.strftime("_%Y%m%d_%H%M")

def add_hyperlink(paragraph, url, display_text):
    """
    Add a clickable hyperlink to a Word paragraph.
    """
    part = paragraph.part
    hyperlink = OxmlElement("w:hyperlink")
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink.set(qn("r:id"), r_id)

    # Create a run for the hyperlink
    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rStyle = OxmlElement("w:rStyle")
    rStyle.set(qn("w:val"), "Hyperlink")
    rPr.append(rStyle)
    run.append(rPr)

    # Add the display text
    text = OxmlElement("w:t")
    text.text = display_text
    run.append(text)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def add_resolved_tasks_section(document, resolved_tasks):
    """
    Add a section to the Word document for resolved tasks, grouped by week and parent tasks.
    """
    document.add_heading("Resolved Tasks", level=2)
    if resolved_tasks.empty:
        document.add_paragraph("No resolved tasks during the specified period.")
        return

    # Group tasks by week
    resolved_tasks["Resolution Week"] = pd.to_datetime(resolved_tasks["Resolution Date"]).dt.strftime("%G-W%V")
    for week, tasks in resolved_tasks.groupby("Resolution Week"):
        week_start = pd.Timestamp.strptime(week + '-1', "%G-W%V-%u")
        week_end = week_start + timedelta(days=6)
        week_header = f"Week {week} ({week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')})"
        document.add_heading(week_header, level=3)

        for _, task in tasks[tasks["Type"] != "Sub-task"].iterrows():
            paragraph = document.add_paragraph(style="Normal")
            paragraph.add_run(f"{task['Issue_key']}: {task['Summary']}").bold = True

            # List subtasks under parent task
            subtasks = tasks[tasks["Parent Key"] == task["Issue_key"]]
            for _, subtask in subtasks.iterrows():
                document.add_paragraph(f"    - {subtask['Issue_key']}: {subtask['Summary']}", style="List Bullet")


def generate_excel_report(data, month, project, headers, file_suffix):
    """
    Generate an Excel report summarizing the data grouped by assignee and week.
    """
    grouped_data = data.groupby(["Assignee", "Week"]).apply(
        lambda group: "\n".join(f"{row['Status']}: {row['Issue_key']} - {row['Summary']}" for _, row in group.iterrows())
    ).unstack(fill_value="")
    grouped_data.columns = headers

    output_file = f"jira_report_{project}_{month}{file_suffix}.xlsx"
    grouped_data.to_excel(output_file)
    print(f"Excel report successfully created: {output_file}")

def generate_word_report(data, month, project, headers, file_suffix, jira_url, epic_summary, member_list_file=None):
    """
    Generate a Word report including both the updated tabular view, a list view and Epic progress,
    with tasks sorted by assignee, week, and status.
    If an assignee from the member list has no data, add a row with empty cells for their tasks.
    """
    if member_list_file:
        # Read the required assignees from the Excel file if provided
        required_assignees = read_member_list(member_list_file)
    else:
        # Use all unique assignees in the data if member_list_file is not provided
        required_assignees = data["Assignee"].unique()

    # Sort data by assignee, week and status
    sorted_data = data.sort_values(by=["Assignee", "Week", "Status"])
    required_assignees.sort()

    document = Document()
    document.add_heading(f"JIRA Report: {project} - {month}", level=1)

    # Add new Tabular View with the updated format
    document.add_heading("Tabular View", level=2)
    table = document.add_table(rows=1, cols=6)
    table.style = 'Table Grid'

    # Add headers
    headers = ["Name", "Week #", "Date", "Description", "Link", "Status"]
    for col_idx, header in enumerate(headers):
        table.cell(0, col_idx).text = header

    # Add data rows, ensuring all required assignees are included
    for assignee in required_assignees:
        assignee_data = sorted_data[sorted_data["Assignee"] == assignee]

        if assignee_data.empty:
            # Add a row with empty task details if no data for the assignee
            row_cells = table.add_row().cells
            row_cells[0].text = assignee
            row_cells[1].text = ""
            row_cells[2].text = ""
            row_cells[3].text = ""
            row_cells[4].text = ""
            row_cells[5].text = ""
        else:
            # Add rows for each task of the assignee
            for _, row in assignee_data.iterrows():
                year, week_num = map(int, row["Week"].split("-W"))
                week_start = pd.Timestamp.fromisocalendar(year, week_num, 1).strftime("%Y/%m/%d")
                week_end = (pd.Timestamp.fromisocalendar(year, week_num, 1) + timedelta(days=6)).strftime("%Y/%m/%d")
                week_range = f"{week_start} – {week_end}"

        # Add a row to the table
                row_cells = table.add_row().cells
                row_cells[0].text = assignee
                row_cells[1].text = row["Week"]
                row_cells[2].text = week_range
                row_cells[3].text = row["Summary"]
                add_hyperlink(row_cells[4].paragraphs[0], f"{jira_url}/browse/{row['Issue_key']}", f"{row['Issue_key']}")
                row_cells[5].text = row["Status"]

    # Add List View
    document.add_heading("List View", level=2)
    for assignee, group in data.groupby("Assignee"):
        document.add_heading(assignee, level=3)

        for week, week_data in group.groupby("Week"):
            year, week_num = map(int, week.split("-W"))
            week_start = pd.Timestamp.fromisocalendar(year, week_num, 1).strftime("%d/%m")
            week_end = (pd.Timestamp.fromisocalendar(year, week_num, 1) + timedelta(days=6)).strftime("%d/%m")
            week_header = f"{week}({week_start}-{week_end}):"
            document.add_paragraph(week_header, style="Heading 4")

            # Add tasks for the current week
            for idx, row in enumerate(week_data.itertuples(index=False, name="Row"), start=1):
                # Add a new paragraph with the style 'List Number'
                paragraph = document.add_paragraph(style='List Number')
                paragraph.add_run(f"{row.Status}: ")
                add_hyperlink(paragraph, f"{jira_url}/browse/{row.Issue_key}", f"{row.Issue_key} - {row.Summary}")

    # Add Epic Progress section
    document.add_heading("Epic Progress", level=2)
    if epic_summary:
        for epic in epic_summary:
            document.add_heading(epic["Epic"], level=3)
            for task in epic["Tasks"]:
                document.add_paragraph(f"- {task['Task Key']}: {task['Task Summary']}")
    else:
        document.add_paragraph("No resolved tasks for open epics during the specified period.")


    # Add resolved tasks section
    resolved_tasks = data[data["Status"] == "Resolved"]
    add_resolved_tasks_section(document, resolved_tasks)

    # Save the document
    output_file = f"jira_report_{project}_{month}{file_suffix}.docx"
    document.save(output_file)
    print(f"Word report successfully created: {output_file}")


def generate_report(data, month, project, jira_url):
    """
    Generate both Excel and Word reports for the specified data.
    """
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    valid_weeks = pd.date_range(start=start_date, end=end_date, freq='W-MON').strftime("%G-W%V").tolist()
    data = data[data["Week"].isin(valid_weeks)]
    headers = generate_week_headers(valid_weeks, data)

    # Update the data to include only valid weeks
    data = data[data["Week"].isin(valid_weeks)]

    # Generate epic report data
    epic_summary = generate_epic_report(data)

    file_suffix = generate_file_suffix()
    generate_excel_report(data, month, project, headers, file_suffix)
    generate_word_report(data, month, project, headers, file_suffix, jira_url, epic_summary)

def main():
    """
    Main function to handle the overall process of fetching data and generating reports.
    """
    jira_url, jira_username, jira_password, project, month, member_list_file = parse_arguments_and_config()
    jira_options = {"verify": "bundle-ca"} if os.path.exists("bundle-ca") else True
    jira_options = {"verify": "bundle-ca"} if os.path.exists("bundle-ca") else True
    jira = JIRA(server=jira_url, basic_auth=(jira_username, jira_password), options=jira_options)
    data = fetch_jira_data(jira, project, month)
    generate_report(data, month, project, jira_url)

if __name__ == "__main__":
    main()