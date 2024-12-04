# -*- coding: utf-8 -*-
import os
import sys
import argparse
import logging
import codecs
from configparser import ConfigParser
from datetime import datetime
import pytz
from jira import JIRA

# Configurations
CONFIG_FILE = "config.ini"
CONFIG_POINT_LOCAL = "jira"
CONFIG_BASE_URL = "jira-url"
CONFIG_USER = "username"
CONFIG_PASSWORD = "password"


def main():
    # Argument parsing
    tool_description = 'Manage Log Work in JIRA using JIRA API'
    parser = argparse.ArgumentParser(description=tool_description,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-d', '--date', dest='date', help='Date for the log work (YYYY-MM-DD)')
    parser.add_argument('-c', '--comment', dest='comment', help='Comment for the log work')
    parser.add_argument('-s', '--timeSpent', dest='timeSpent', help='Time spent (e.g., 1h, 2d)')
    parser.add_argument('--config', dest='config', default=CONFIG_FILE, help='Path to the configuration file')
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('-t', '--task', dest='task_key', help='Task key for worklog')
    options = parser.parse_args()

    # Set logging level
    level = logging.DEBUG if options.verbose else logging.INFO
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=level)

    # Read configuration
    config = ConfigParser(allow_no_value=False, comment_prefixes=('#', ';'), inline_comment_prefixes='#')
    config.read_file(codecs.open(options.config, 'r', encoding='utf-8-sig'))

    base_url = config.get(CONFIG_POINT_LOCAL, CONFIG_BASE_URL)
    username = config.get(CONFIG_POINT_LOCAL, CONFIG_USER)
    password = config.get(CONFIG_POINT_LOCAL, CONFIG_PASSWORD)

    if not base_url or not username or not password:
        raise ValueError(
            "Invalid configuration: ensure base URL, username, and password are specified in the config file.")

    # Prepare JIRA options
    jira_options = {"server": base_url}
    if os.path.exists("bundle-ca"):
        jira_options["verify"] = "bundle-ca"
    else:
        jira_options["verify"] = True

    # Connect to JIRA using Basic Authentication
    jira = JIRA(basic_auth=(username, password), options=jira_options)

    log_date = options.date or datetime.today().strftime("%Y-%m-%d")
    time_spent = options.timeSpent
    comment = options.comment or ""
    task_key = options.task_key or choose_task_or_modify(jira, username)

    if not task_key:
        print("No task selected. Exiting.")
        sys.exit(0)

    if task_key.startswith("MODIFY"):
        modify_task_key = task_key.split(" ", 1)[1]
        modify_logged_work(jira, modify_task_key)
    else:
        if not time_spent:
            time_spent = input("Enter time spent (e.g., 1h, 2d, or a number for hours): ").strip()
            if time_spent.isdigit():
                time_spent = f"{time_spent}h"

        add_log_work(jira, task_key, log_date, time_spent, comment)
        print(f"Log Work successfully added: {time_spent} to task {task_key}.")


def choose_task_or_modify(jira, user):
    """Prompt the user to choose a task or modify a worklog."""
    jql = f"assignee = {user} AND statusCategory != Done"
    issues = jira.search_issues(jql, maxResults=10)

    print("Select a task:")
    print("0. Modify worklog for task (input 0 <task number, e.g. 1, 2, 3 ... or 0 TASK-1>)")
    for idx, issue in enumerate(issues, start=1):
        print(f"{idx}. {issue.key} - {issue.fields.summary}")

    user_input = input("Enter your choice: ").strip()
    if user_input.startswith("0"):
        modify_key = user_input.split(" ", 1)[1]
        return f"MODIFY {modify_key}"
    elif user_input.isdigit():
        idx = int(user_input) - 1
        if 0 <= idx < len(issues):
            return issues[idx].key
    print("Invalid selection.")
    return None


def add_log_work(jira, task_key, date, time_spent, comment):
    """Add Log Work to the specified task."""
    # Parse the date and convert it to a datetime object with timezone info
    local_timezone = pytz.timezone("UTC")  # Replace "UTC" with your desired timezone
    started = local_timezone.localize(datetime.strptime(date, "%Y-%m-%d"))

    # Log work
    issue = jira.issue(task_key)
    jira.add_worklog(issue, timeSpent=time_spent, started=started, comment=comment)


def modify_logged_work(jira, task_key):
    """Modify logged work for the specified task."""
    issue = jira.issue(task_key)
    worklogs = jira.worklogs(issue)

    if not worklogs:
        print(f"No logged work found for task {task_key}.")
        return

    print(f"Logged work for task {task_key}:")
    for idx, worklog in enumerate(worklogs, start=1):
        print(f"{idx}. {worklog.author.displayName} - {worklog.timeSpent} - {worklog.comment or 'No comment'}")

    modify_idx = int(input("Enter the number of the log work to modify: ")) - 1
    if not (0 <= modify_idx < len(worklogs)):
        print("Invalid choice. Exiting.")
        return

    selected_worklog = worklogs[modify_idx]
    new_time = input("Enter new time spent (e.g., 1h, 2d, or a number for hours): ").strip()
    if new_time.isdigit():
        new_time = f"{new_time}h"

    new_comment = input("Enter new comment (or leave empty to keep the current comment): ").strip()
    new_comment = new_comment or selected_worklog.comment

    jira.update_worklog(selected_worklog, timeSpent=new_time, comment=new_comment)
    print(f"Work log updated: {new_time}, Comment: {new_comment}")


if __name__ == "__main__":
    sys.exit(main())
