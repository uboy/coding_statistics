# -*- coding: utf-8 -*-
"""
Comprehensive Jira Report Generator
Generates detailed reports with task analysis, link extraction, and team performance ranking
"""

from jira import JIRA
from configparser import ConfigParser
import pandas as pd
from datetime import datetime
import argparse
import codecs
import os
import re
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows

# Configuration constants
CONFIG_FILE = "config.ini"
CONFIG_SECTION = "jira"
CONFIG_URL = "jira-url"
CONFIG_USERNAME = "username"
CONFIG_PASSWORD = "password"


def parse_arguments_and_config():
    """Parse command-line arguments and configuration file."""
    parser = argparse.ArgumentParser(description="Generate comprehensive Jira report.")
    parser.add_argument("-c", "--config", default=CONFIG_FILE, help="Path to config file")
    parser.add_argument("-u", "--username", help="Jira username")
    parser.add_argument("-p", "--password", help="Jira password")
    parser.add_argument("-l", "--url", help="Jira base URL")
    parser.add_argument("--project", help="Jira project key (e.g., ABC)")
    parser.add_argument("--start-date", help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", help="End date in YYYY-MM-DD format")
    parser.add_argument("--version", help="Fix version name")
    parser.add_argument("--epic", help="Epic key")
    parser.add_argument("--jql", help="Custom JQL query")
    parser.add_argument("--member-list-file", default="members.xlsx", help="Path to member list Excel file")
    parser.add_argument("--code-volume-file", help="Path to code volume Excel file")
    args = parser.parse_args()

    # Load config
    config = ConfigParser(allow_no_value=False, comment_prefixes=('#', ';'))
    config.read_file(codecs.open(args.config, 'r', encoding='utf-8-sig'))

    jira_url = args.url or config.get(CONFIG_SECTION, CONFIG_URL, fallback=None)
    jira_username = args.username or config.get(CONFIG_SECTION, CONFIG_USERNAME, fallback=None)
    jira_password = args.password or config.get(CONFIG_SECTION, CONFIG_PASSWORD, fallback=None)

    if not jira_url or not jira_username or not jira_password:
        raise ValueError("Jira URL, username, and password must be specified")

    return {
        'jira_url': jira_url,
        'jira_username': jira_username,
        'jira_password': jira_password,
        'project': args.project,
        'start_date': args.start_date,
        'end_date': args.end_date,
        'version': args.version,
        'epic': args.epic,
        'jql': args.jql,
        'member_list_file': args.member_list_file,
        'code_volume_file': args.code_volume_file
    }


def build_jql_query(params):
    """Build JQL query based on provided parameters."""
    if params['jql']:
        return params['jql']

    conditions = []

    if params['project']:
        conditions.append(f"project = {params['project']}")

    if params['start_date'] and params['end_date']:
        conditions.append(f"resolved >= '{params['start_date']}' AND resolved <= '{params['end_date']}'")

    if params['version']:
        conditions.append(f"fixVersion = '{params['version']}'")

    if params['epic']:
        conditions.append(f"'Epic Link' = {params['epic']}")

    if not conditions:
        raise ValueError("Must specify at least one of: project+dates, version, epic, or jql")

    return " AND ".join(conditions) + " ORDER BY created DESC"


def extract_urls_from_text(text):
    """Extract all URLs from text."""
    if not text:
        return []
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    return re.findall(url_pattern, text)


def fetch_jira_data(jira, jql_query):
    """
    Fetch Jira issues with all details including comments.

    Returns:
        list: List of dictionaries with issue details
    """
    start_at = 0
    max_results = 100
    all_issues = []

    print(f"Executing JQL: {jql_query}")

    while True:
        issues = jira.search_issues(
            jql_query,
            startAt=start_at,
            maxResults=max_results,
            fields=[
                "key", "summary", "assignee", "reporter", "resolutiondate",
                "created", "updated", "description", "comment", "labels",
                "priority", "status", "resolution", "issuetype",
                "timeestimate", "timespent", "timeoriginalestimate",
                "customfield_10000"  # Epic Link
            ],
            expand="changelog"
        )

        all_issues.extend(issues)

        if len(issues) < max_results:
            break
        start_at += max_results

    print(f"Fetched {len(all_issues)} issues")

    data = []
    all_links = []

    for issue in all_issues:
        # Basic fields
        key = issue.key
        summary = issue.fields.summary
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        assignee_name = issue.fields.assignee.name if issue.fields.assignee else ""
        reporter = issue.fields.reporter.displayName if issue.fields.reporter else ""
        reporter_name = issue.fields.reporter.name if issue.fields.reporter else ""

        # Dates
        created = issue.fields.created[:10] if issue.fields.created else ""
        resolved = issue.fields.resolutiondate[:10] if issue.fields.resolutiondate else ""

        # Time tracking (convert seconds to hours)
        original_estimate = issue.fields.timeoriginalestimate / 3600 if issue.fields.timeoriginalestimate else 0
        time_spent = issue.fields.timespent / 3600 if issue.fields.timespent else 0
        remaining = issue.fields.timeestimate / 3600 if issue.fields.timeestimate else 0

        # Description
        description = issue.fields.description or ""

        # Extract links from description
        desc_links = extract_urls_from_text(description)
        for link in desc_links:
            all_links.append({
                'Issue_Key': key,
                'Source': 'Description',
                'URL': link
            })

        # Comments
        comments = []
        comment_links = []
        if hasattr(issue.fields, 'comment') and issue.fields.comment.comments:
            for comment in issue.fields.comment.comments:
                comment_text = comment.body
                comment_author = comment.author.displayName if comment.author else "Unknown"
                comment_created = comment.created[:10] if comment.created else ""
                comments.append(f"[{comment_created}] {comment_author}: {comment_text}")

                # Extract links from comments
                links = extract_urls_from_text(comment_text)
                for link in links:
                    all_links.append({
                        'Issue_Key': key,
                        'Source': f'Comment by {comment_author}',
                        'URL': link
                    })

        all_comments = "\n---\n".join(comments)

        # Labels
        labels = ", ".join(issue.fields.labels) if issue.fields.labels else ""

        # Other fields
        priority = issue.fields.priority.name if issue.fields.priority else ""
        status = issue.fields.status.name if issue.fields.status else ""
        resolution = issue.fields.resolution.name if issue.fields.resolution else ""
        issue_type = issue.fields.issuetype.name if issue.fields.issuetype else ""
        epic_link = getattr(issue.fields, "customfield_10000", "")

        data.append({
            'Issue_Key': key,
            'Summary': summary,
            'Type': issue_type,
            'Status': status,
            'Resolution': resolution,
            'Priority': priority,
            'Assignee': assignee,
            'Assignee_Username': assignee_name,
            'Reporter': reporter,
            'Reporter_Username': reporter_name,
            'Created': created,
            'Resolved': resolved,
            'Original_Estimate_Hours': original_estimate,
            'Time_Spent_Hours': time_spent,
            'Remaining_Hours': remaining,
            'Description': description,
            'Comments': all_comments,
            'Labels': labels,
            'Epic_Link': epic_link
        })

    return pd.DataFrame(data), pd.DataFrame(all_links)


def read_member_list(member_list_file):
    """Read team member details from Excel file."""
    if not os.path.exists(member_list_file):
        print(f"Warning: Member list file '{member_list_file}' not found")
        return pd.DataFrame(columns=['name', 'email', 'username', 'role'])

    df = pd.read_excel(member_list_file)
    required_columns = ['name', 'username', 'role']

    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"Member list file must contain '{col}' column")

    return df


def read_code_volume(code_volume_file):
    """Read code volume data from Excel file."""
    if not code_volume_file or not os.path.exists(code_volume_file):
        return pd.DataFrame(columns=['username', 'code_volume'])

    df = pd.read_excel(code_volume_file)
    return df


def calculate_engineer_metrics(issues_df, members_df, code_volume_df):
    """Calculate metrics for Engineers."""
    metrics = []

    engineers = members_df[members_df['role'] == 'Engineer']

    for _, engineer in engineers.iterrows():
        username = engineer['username'].lower()
        name = engineer['name']

        # Get issues assigned to this engineer
        user_issues = issues_df[issues_df['Assignee_Username'].str.lower() == username]
        resolved_issues = user_issues[user_issues['Status'].isin(['Done', 'Resolved', 'Closed'])]

        # Code Volume (from external file)
        code_volume = 0
        if not code_volume_df.empty and 'username' in code_volume_df.columns:
            cv_row = code_volume_df[code_volume_df['username'].str.lower() == username]
            if not cv_row.empty:
                code_volume = cv_row.iloc[0].get('code_volume', 0)

        # Code Quality (Bugs / (Features + Improvements))
        bugs = resolved_issues[resolved_issues['Type'] == 'Bug'].shape[0]
        features = resolved_issues[resolved_issues['Type'].isin(['Story', 'New Feature', 'Improvement'])].shape[0]
        code_quality = bugs / features if features > 0 else 0

        # Quantity of documentation
        doc_tasks = \
        resolved_issues[resolved_issues['Labels'].str.contains('documentation', case=False, na=False)].shape[0]

        # Outstanding contribution (manual - placeholder)
        outstanding_contribution = 0

        # Assistance provided (manual - placeholder)
        assistance_provided = 0

        metrics.append({
            'Name': name,
            'Role': 'Engineer',
            'Code_Volume': code_volume,
            'Code_Quality_Score': round(1 / (1 + code_quality), 2) if features > 0 else 1.0,
            'Bugs': bugs,
            'Features': features,
            'Documentation_Tasks': doc_tasks,
            'Outstanding_Contribution': outstanding_contribution,
            'Assistance_Provided': assistance_provided,
            'Total_Resolved_Issues': resolved_issues.shape[0]
        })

    return pd.DataFrame(metrics)


def calculate_qa_metrics(issues_df, members_df):
    """Calculate metrics for QA Engineers."""
    metrics = []

    qa_engineers = members_df[members_df['role'] == 'QA Engineer']

    for _, qa in qa_engineers.iterrows():
        username = qa['username'].lower()
        name = qa['name']

        # Resolved test-related tasks
        user_issues = issues_df[issues_df['Assignee_Username'].str.lower() == username]
        resolved_issues = user_issues[user_issues['Status'].isin(['Done', 'Resolved', 'Closed'])]
        test_scenarios = resolved_issues[resolved_issues['Type'].isin(['Test', 'Task'])].shape[0]

        # Issues raised (created bugs)
        bugs_created = issues_df[
            (issues_df['Reporter_Username'].str.lower() == username) &
            (issues_df['Type'] == 'Bug')
            ].shape[0]

        # Performance benchmarks
        perf_tasks = resolved_issues[
            resolved_issues['Labels'].str.contains('arkoala_perf', case=False, na=False)
        ].shape[0]

        metrics.append({
            'Name': name,
            'Role': 'QA Engineer',
            'Test_Scenarios_Executed': test_scenarios,
            'Issues_Raised': bugs_created,
            'Performance_Benchmarks': perf_tasks,
            'Total_Resolved_Issues': resolved_issues.shape[0]
        })

    return pd.DataFrame(metrics)


def calculate_pm_metrics(issues_df, members_df, jira, jql_query):
    """Calculate metrics for Project Managers."""
    metrics = []

    pms = members_df[members_df['role'] == 'Project Manager']

    # Count epics from the query
    epic_count = issues_df[issues_df['Type'] == 'Epic'].shape[0]

    for _, pm in pms.iterrows():
        username = pm['username'].lower()
        name = pm['name']

        # Total closed tasks
        total_closed = issues_df[issues_df['Status'].isin(['Done', 'Resolved', 'Closed'])].shape[0]

        # Documentation tasks
        doc_tasks = issues_df[
            (issues_df['Status'].isin(['Done', 'Resolved', 'Closed'])) &
            (issues_df['Labels'].str.contains('documentation', case=False, na=False))
            ].shape[0]

        metrics.append({
            'Name': name,
            'Role': 'Project Manager',
            'Epics_Created': epic_count,
            'Total_Closed_Tasks': total_closed,
            'Documentation_Tasks': doc_tasks
        })

    return pd.DataFrame(metrics)


def export_to_excel(issues_df, links_df, engineer_metrics, qa_metrics, pm_metrics, output_file):
    """Export all data to Excel file with multiple sheets."""
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Issues sheet
        issues_df.to_excel(writer, sheet_name='Issues', index=False)

        # Links sheet
        if not links_df.empty:
            links_df.to_excel(writer, sheet_name='Links', index=False)

        # Team Performance sheets
        if not engineer_metrics.empty:
            engineer_metrics.to_excel(writer, sheet_name='Engineer_Performance', index=False)

        if not qa_metrics.empty:
            qa_metrics.to_excel(writer, sheet_name='QA_Performance', index=False)

        if not pm_metrics.empty:
            pm_metrics.to_excel(writer, sheet_name='PM_Performance', index=False)

        # Format sheets
        workbook = writer.book

        for sheet_name in workbook.sheetnames:
            worksheet = workbook[sheet_name]

            # Format header
            for cell in worksheet[1]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="CCE5FF", end_color="CCE5FF", fill_type="solid")
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

    print(f"Excel report created: {output_file}")


def main():
    """Main function."""
    params = parse_arguments_and_config()

    # Connect to Jira
    jira_options = {"verify": "bundle-ca"} if os.path.exists("bundle-ca") else {"verify": True}
    jira = JIRA(
        server=params['jira_url'],
        basic_auth=(params['jira_username'], params['jira_password']),
        options=jira_options
    )

    # Build and execute query
    jql_query = build_jql_query(params)
    issues_df, links_df = fetch_jira_data(jira, jql_query)

    if issues_df.empty:
        print("No issues found matching the query")
        return

    # Read member list
    members_df = read_member_list(params['member_list_file'])
    code_volume_df = read_code_volume(params['code_volume_file'])

    # Calculate metrics by role
    engineer_metrics = pd.DataFrame()
    qa_metrics = pd.DataFrame()
    pm_metrics = pd.DataFrame()

    if not members_df.empty:
        engineer_metrics = calculate_engineer_metrics(issues_df, members_df, code_volume_df)
        qa_metrics = calculate_qa_metrics(issues_df, members_df)
        pm_metrics = calculate_pm_metrics(issues_df, members_df, jira, jql_query)
    else:
        print("Warning: No member list found, skipping team performance calculations")

    # Generate output filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"jira_comprehensive_report_{timestamp}.xlsx"

    # Export to Excel
    export_to_excel(issues_df, links_df, engineer_metrics, qa_metrics, pm_metrics, output_file)

    # Print summary
    print("\n" + "=" * 60)
    print("REPORT SUMMARY")
    print("=" * 60)
    print(f"Total Issues: {len(issues_df)}")
    print(f"Total Links Found: {len(links_df)}")
    if not engineer_metrics.empty:
        print(f"Engineers Analyzed: {len(engineer_metrics)}")
    if not qa_metrics.empty:
        print(f"QA Engineers Analyzed: {len(qa_metrics)}")
    if not pm_metrics.empty:
        print(f"Project Managers Analyzed: {len(pm_metrics)}")
    print("=" * 60)


if __name__ == "__main__":
    main()