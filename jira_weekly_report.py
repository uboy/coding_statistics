from jira import JIRA
from configparser import ConfigParser
import pandas as pd
from datetime import datetime
import argparse
import codecs  # Required for reading files with specific encoding

# Configuration constants
CONFIG_FILE = "config.ini"
CONFIG_SECTION = "jira"
CONFIG_URL = "jira-url"
CONFIG_USERNAME = "username"
CONFIG_PASSWORD = "password"

def parse_arguments_and_config():
    parser = argparse.ArgumentParser(description="Generate JIRA weekly report with detailed statuses.")
    parser.add_argument("-c", "--config", default=CONFIG_FILE, help="Path to config file.")
    parser.add_argument("-u", "--username", help="JIRA username.")
    parser.add_argument("-p", "--password", help="JIRA password.")
    parser.add_argument("-l", "--url", help="JIRA base URL.")
    parser.add_argument("-proj", "--project", required=True, help="JIRA project key.")
    parser.add_argument("-m", "--month", required=True, help="Month in YYYY-MM format (e.g., 2024-11).")
    args = parser.parse_args()

    # Updated config parser initialization
    config = ConfigParser(allow_no_value=False, comment_prefixes=('#', ';'), inline_comment_prefixes='#')
    config.read_file(codecs.open(args.config, 'r', encoding='utf-8-sig'))

    jira_url = args.url or config.get(CONFIG_SECTION, CONFIG_URL, fallback=None)
    jira_username = args.username or config.get(CONFIG_SECTION, CONFIG_USERNAME, fallback=None)
    jira_password = args.password or config.get(CONFIG_SECTION, CONFIG_PASSWORD, fallback=None)

    if not jira_url or not jira_username or not jira_password:
        raise ValueError("JIRA URL, username, and password must be specified either as arguments or in the config file.")

    return jira_url, jira_username, jira_password, args.project, args.month

def fetch_jira_data(jira, project, month):
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date.replace(day=28) + pd.DateOffset(days=4)).replace(day=1) - pd.DateOffset(days=1)
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    jql_query = f"project = {project} AND updated >= {start_date_str} AND updated <= {end_date_str}"
    issues = jira.search_issues(jql_query, maxResults=1000, fields=["key", "assignee", "resolutiondate", "worklog"])

    data = []
    for issue in issues:
        key = issue.key
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        resolved_date = issue.fields.resolutiondate

        # Worklogs processing
        worklogs = []
        if issue.fields.worklog and issue.fields.worklog.worklogs:
            for log in issue.fields.worklog.worklogs:
                log_date = datetime.strptime(log.started.split("T")[0], "%Y-%m-%d")
                worklogs.append(log_date)

        # Append in-progress tasks (logged)
        for log_date in worklogs:
            data.append({
                "Issue key": key,
                "Assignee": assignee,
                "Status": "In progress",
                "Date": log_date
            })

        # Append resolved tasks
        if resolved_date:
            data.append({
                "Issue key": key,
                "Assignee": assignee,
                "Status": "Resolved",
                "Date": datetime.strptime(resolved_date.split("T")[0], "%Y-%m-%d")
            })

    return pd.DataFrame(data)

def generate_report(data, month, project):
    data["Week"] = data["Date"].dt.strftime("%Y-W%U")
    data["Assignee"] = data["Assignee"].fillna("Unassigned")

    # Group by Assignee and Week
    grouped_data = data.groupby(["Assignee", "Week"]).apply(
        lambda x: "; ".join(f"{row['Status']}: {row['Issue key']}" for _, row in x.iterrows())
    ).unstack(fill_value="")

    # Save to Excel
    output_file = f"jira_report_{project}_{month}.xlsx"
    grouped_data.to_excel(output_file)
    print(f"Report successfully created: {output_file}")

def main():
    jira_url, jira_username, jira_password, project, month = parse_arguments_and_config()

    # Connect to JIRA
    jira = JIRA(server=jira_url, basic_auth=(jira_username, jira_password), options={"verify":"bundle-ca"})

    # Fetch data
    data = fetch_jira_data(jira, project, month)

    # Generate and save report
    generate_report(data, month, project)

if __name__ == "__main__":
    main()

