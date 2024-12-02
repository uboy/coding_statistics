from jira import JIRA
from configparser import ConfigParser
import pandas as pd
from datetime import datetime, timedelta
import argparse
import codecs
import os
from docx import Document

# Configuration constants
CONFIG_FILE = "config.ini"
CONFIG_SECTION = "jira"
CONFIG_URL = "jira-url"
CONFIG_USERNAME = "username"
CONFIG_PASSWORD = "password"

def parse_arguments_and_config():
    parser = argparse.ArgumentParser(description="Generate JIRA monthly report with links and Word output.")
    parser.add_argument("-c", "--config", default=CONFIG_FILE, help="Path to config file.")
    parser.add_argument("-u", "--username", help="JIRA username.")
    parser.add_argument("-p", "--password", help="JIRA password.")
    parser.add_argument("-l", "--url", help="JIRA base URL.")
    parser.add_argument("-proj", "--project", required=True, help="JIRA project key.")
    parser.add_argument("-m", "--month", required=True, help="Month in YYYY-MM format (e.g., 2024-11).")
    args = parser.parse_args()

    config = ConfigParser(allow_no_value=False, comment_prefixes=('#', ';'), inline_comment_prefixes='#')
    config.read_file(codecs.open(args.config, 'r', encoding='utf-8-sig'))

    jira_url = args.url or config.get(CONFIG_SECTION, CONFIG_URL, fallback=None)
    jira_username = args.username or config.get(CONFIG_SECTION, CONFIG_USERNAME, fallback=None)
    jira_password = args.password or config.get(CONFIG_SECTION, CONFIG_PASSWORD, fallback=None)

    if not jira_url or not jira_username or not jira_password:
        raise ValueError("JIRA URL, username, and password must be specified either as arguments or in the config file.")

    return jira_url, jira_username, jira_password, args.project, args.month

def get_all_worklogs(jira, issue_key):
    """Fetch all work logs for an issue using pagination."""
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
    # Determine the first and last day of the specified month
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    # JQL query for fetching issues (tasks and subtasks)
    jql_query = f"project = {project}"  # No date filter to include all relevant tasks
    issues = jira.search_issues(jql_query, maxResults=1000, fields=["key", "summary", "assignee", "resolutiondate", "updated"])

    data = []
    for issue in issues:
        key = issue.key
        summary = issue.fields.summary
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        resolved_date = issue.fields.resolutiondate
        issue_url = f"{jira._options['server']}/browse/{key}"

        # Fetch all work logs for the issue
        worklogs = get_all_worklogs(jira, key)
        worklog_dates = set()
        for log in worklogs:
            try:
                log_date = datetime.strptime(log["started"].split("T")[0], "%Y-%m-%d")
                if start_date <= log_date <= end_date:
                    worklog_dates.add(log_date)
            except Exception:
                continue

        # Determine resolved week
        resolved_week = None
        if resolved_date:
            resolved_date_dt = datetime.strptime(resolved_date.split("T")[0], "%Y-%m-%d")
            if start_date <= resolved_date_dt <= end_date:
                resolved_week = resolved_date_dt.strftime("%G-W%V")
                data.append({
                    "Issue key": key,
                    "Summary": summary,
                    "Assignee": assignee,
                    "Status": "Resolved",
                    "Week": resolved_week,
                    "URL": issue_url
                })

        # Add "In progress" for unique weeks, excluding resolved week
        for log_date in worklog_dates:
            log_week = log_date.strftime("%G-W%V")
            if log_week != resolved_week:
                if not any(d["Issue key"] == key and d["Week"] == log_week for d in data):
                    data.append({
                        "Issue key": key,
                        "Summary": summary,
                        "Assignee": assignee,
                        "Status": "In progress",
                        "Week": log_week,
                        "URL": issue_url
                    })

    return pd.DataFrame(data)

def generate_report(data, month, project):
    # Ensure only data within the specified month or overlapping weeks
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    # Include weeks overlapping with the month
    valid_weeks_dates = pd.date_range(start=start_date - timedelta(days=7), end=end_date, freq='W-MON')
    week_labels = [f"{week.strftime('%Y-W%V')}({week.strftime('%d/%m')}-{(week + timedelta(days=6)).strftime('%d/%m')})"
                   for week in valid_weeks_dates]
    valid_weeks = valid_weeks_dates.strftime("%G-W%V").tolist()

    # Filter data to include only relevant weeks
    data = data[data["Week"].isin(valid_weeks)]

    # Group by Assignee and Week
    grouped_data = data.groupby(["Assignee", "Week"]).apply(
        lambda x: "\n".join(
            f'=HYPERLINK("{row["URL"]}", "{row["Issue key"]} - {row["Summary"]}")'
            for _, row in x.sort_values(by="Status", key=lambda col: col.map({"Resolved": 0, "In progress": 1})).iterrows()
        )
    ).unstack(fill_value="")

    # Generate timestamp for filenames
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    excel_filename = f"jira_report_{project}_{month}_{timestamp}.xlsx"
    word_filename = f"jira_report_{project}_{month}_{timestamp}.docx"

    # Save to Excel with hyperlinks
    with pd.ExcelWriter(excel_filename, engine="xlsxwriter") as writer:
        grouped_data.to_excel(writer, sheet_name="Report", index_label="Assignee")
        workbook = writer.book
        worksheet = writer.sheets["Report"]

        # Update week headers with week ranges
        for col_num, week_label in enumerate(week_labels, start=1):
            worksheet.write(0, col_num, week_label)

        # Format cells with hyperlinks
        hyperlink_format = workbook.add_format({'font_color': 'blue', 'underline':  1})
        for row_num, assignee in enumerate(grouped_data.index, start=1):
            for col_num, week in enumerate(grouped_data.columns, start=1):
                cell_value = grouped_data.at[assignee, week]
                if cell_value:
                    lines = cell_value.split('\n')
                    cell_text = ''
                    for line in lines:
                        if line.startswith('=HYPERLINK'):
                            # Extract URL and display text
                            url, display = line[11:-2].split('","')
                            worksheet.write_url(row_num, col_num, url, hyperlink_format, display)
                        else:
                            worksheet.write(row_num, col_num, line)
                else:
                    worksheet.write(row_num, col_num, "")

    # Save to Word
    doc = Document()
    doc.add_heading(f"JIRA Report for {project} - {month}", level=1)

    # Create Word table
    table = doc.add_table(rows=1, cols=len(valid_weeks) + 1)
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = "Assignee"
    for i, week_label in enumerate(week_labels, start=1):
        hdr_cells[i].text = week_label

    for assignee, week_data in grouped_data.iterrows():
        row_cells = table.add_row().cells
        row_cells[0].text = assignee
        for i, (week, issues) in enumerate(week_data.items()):
            cell = row_cells[i + 1]
            if issues:
                paragraphs = issues.split('\n')
                for paragraph in paragraphs:
                    if paragraph.startswith('=HYPERLINK'):
                        url, display = paragraph[11:-2].split('","')
                        p = cell.add_paragraph()
                        run = p.add_run(display)
                        run.font.color.rgb = docx.shared.RGBColor(0, 0, 255)
                        run.font.underline = True
                        hyperlink = run._r
                        hyperlink = hyperlink.get_or_add_hlinkClick()
                        hyperlink.set(qn('w:anchor'), url)
                    else:
                        cell.add_paragraph(paragraph)
            else:
                cell.text = ""

    doc.save(word_filename)
    print(f"Reports successfully created: {excel_filename} and {word_filename}")

def main():
    jira_url, jira_username, jira_password, project, month = parse_arguments_and_config()

    jira = JIRA(server=jira_url, basic_auth=(jira_username, jira_password))

    data = fetch_jira_data(jira, project, month)
    generate_report(data, month, project)

if __name__ == "__main__":
    main()
