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

    return jira_url, jira_username, jira_password, args.project, args.month

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
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    jql_query = f"project = {project}"
    issues = jira.search_issues(jql_query, maxResults=1000, fields=["key", "summary", "assignee", "resolutiondate", "updated"])

    data = []
    for issue in issues:
        key = issue.key
        summary = issue.fields.summary
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        resolved_date = issue.fields.resolutiondate

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
                    "Week": resolved_week
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
                        "Week": log_week
                    })

    return pd.DataFrame(data)

def generate_week_headers(valid_weeks):
    """
    Generate table headers with week ranges for the report.
    """
    headers = []
    for week in valid_weeks:
        year, week_num = map(int, week.split("-W"))
        week_start = pd.Timestamp.fromisocalendar(year, week_num, 1)
        week_end = week_start + timedelta(days=6)
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

def generate_word_report(data, month, project, headers, file_suffix, jira_url):
    """
    Generate a Word report including both a tabular view and a list view.
    """
    grouped_data = data.groupby(["Assignee", "Week"]).apply(
        lambda group: "\n".join(f"{row['Status']}: {row['Issue_key']} - {row['Summary']}" for _, row in group.iterrows())
    ).unstack(fill_value="")

    document = Document()
    document.add_heading(f"JIRA Report: {project} - {month}", level=1)

    # Add tabular view
    document.add_heading("Tabular View", level=2)
    table = document.add_table(rows=grouped_data.shape[0] + 1, cols=grouped_data.shape[1] + 1)
    table.style = 'Table Grid'
    table.cell(0, 0).text = "Assignee"
    for col_idx, header in enumerate(headers, start=1):
        table.cell(0, col_idx).text = header
    for row_idx, (assignee, row) in enumerate(grouped_data.iterrows(), start=1):
        table.cell(row_idx, 0).text = assignee
        for col_idx, cell_value in enumerate(row, start=1):
            paragraph = table.cell(row_idx, col_idx).paragraphs[0]
            for cell_data in cell_value.split("\n"):
                if not cell_data.strip():
                    continue
                status, rest = cell_data.split(": ", 1)
                key, summary = rest.split(" - ", 1)
                paragraph.add_run(f"{status}: ")
                add_hyperlink(paragraph, f"{jira_url}/browse/{key}", f"{key} - {summary}")

    # Add list view
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
    valid_weeks = pd.date_range(start=start_date - timedelta(days=7), end=end_date, freq='W-MON').strftime("%G-W%V").tolist()
    data = data[data["Week"].isin(valid_weeks)]
    headers = generate_week_headers(valid_weeks)
    file_suffix = generate_file_suffix()
    generate_excel_report(data, month, project, headers, file_suffix)
    generate_word_report(data, month, project, headers, file_suffix, jira_url)

def main():
    """
    Main function to handle the overall process of fetching data and generating reports.
    """
    jira_url, jira_username, jira_password, project, month = parse_arguments_and_config()
    jira_options = {"verify": "bundle-ca"} if os.path.exists("bundle-ca") else {}
    jira = JIRA(server=jira_url, basic_auth=(jira_username, jira_password), options=jira_options)
    data = fetch_jira_data(jira, project, month)
    generate_report(data, month, project, jira_url)

if __name__ == "__main__":
    main()
