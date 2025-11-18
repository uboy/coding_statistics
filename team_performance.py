# team_performance.py

import pandas as pd
from datetime import datetime
import logging
import re

# Configure logging only if not already configured
logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def calculate_team_performance(data: pd.DataFrame, assignees: list[str]) -> pd.DataFrame:
    """
    Calculate performance metrics for each team member based on Jira data.

    Args:
        data (pd.DataFrame): Jira data with columns: Status, Assignee, Resolution_Date, Type, Summary.
        assignees (list[str]): List of team member names to evaluate.

    Returns:
        pd.DataFrame: DataFrame with metrics: Resolved_Tasks, Bugs_Resolved, Blocked_Tasks,
                      Avg_Resolution_Time, Reopened_Tasks, Score, Rank.
    """
    # Filter for resolved tasks only
    resolved = data[data["Status"] == "Resolved"].copy()

    # Convert Resolution_Date to datetime, handling invalid dates with NaT
    resolved["Resolution_Date"] = pd.to_datetime(resolved["Resolution_Date"], errors="coerce")

    metrics = []
    for person in assignees:
        # Extract data for the current team member
        person_data = resolved[resolved["Assignee"] == person]

        # Calculate basic metrics
        total_tasks = len(person_data)
        bug_count = len(person_data[person_data["Type"] == "Bug"])
        blocked_count = len(person_data[person_data["Summary"].str.contains("block", case=False, na=False)])

        # Calculate average resolution time in days
        # Use Created_Date if available, otherwise fall back to approximation
        if not person_data["Resolution_Date"].empty:
            # Check if Created_Date column exists and has valid data
            if "Created_Date" in person_data.columns:
                person_data_with_dates = person_data[
                    person_data["Resolution_Date"].notna() & 
                    person_data["Created_Date"].notna() & 
                    (person_data["Created_Date"] != "")
                ]
                if not person_data_with_dates.empty:
                    # Calculate actual resolution time per task
                    resolution_times = (
                        pd.to_datetime(person_data_with_dates["Resolution_Date"]) - 
                        pd.to_datetime(person_data_with_dates["Created_Date"])
                    ).dt.days
                    avg_resolution_days = resolution_times.mean()
                else:
                    # Fallback: use time span approximation
                    if len(person_data) > 1:
                        duration = (person_data["Resolution_Date"].max() - person_data["Resolution_Date"].min()).days
                        avg_resolution_days = duration / len(person_data)
                    else:
                        avg_resolution_days = None
            else:
                # Fallback: use time span approximation if Created_Date not available
                if len(person_data) > 1:
                    duration = (person_data["Resolution_Date"].max() - person_data["Resolution_Date"].min()).days
                    avg_resolution_days = duration / len(person_data)
                else:
                    avg_resolution_days = None
        else:
            avg_resolution_days = None

        # Compile metrics for the team member
        metrics.append({
            "Assignee": person,
            "Resolved_Tasks": total_tasks,
            "Bugs_Resolved": bug_count,
            "Blocked_Tasks": blocked_count,
            "Avg_Resolution_Time": round(avg_resolution_days, 2) if pd.notnull(avg_resolution_days) else None,
            "Reopened_Tasks": 0  # Placeholder: Update if reopened task data is available
        })

    # Create DataFrame from metrics
    df = pd.DataFrame(metrics)

    # Calculate performance score with weighted metrics
    # Bug fixes are now rewarded (positive) as they represent valuable work
    df["Score"] = (
            df["Resolved_Tasks"] * 2  # Reward task completion
            + df["Bugs_Resolved"] * 1.5  # Reward bug fixes (valuable work)
            - df["Blocked_Tasks"] * 1  # Penalize blocked tasks
            - df["Reopened_Tasks"] * 2  # Penalize reopened tasks
            - df["Avg_Resolution_Time"].fillna(0) * 0.5  # Penalize longer resolution times
    )

    # Assign ranks based on score (higher score = better rank)
    df["Rank"] = df["Score"].rank(method="min", ascending=False).astype(int)
    return df.sort_values("Rank")


def export_team_performance_to_excel(df: pd.DataFrame, output_file: str, sheet_name="Team Performance"):
    """
    Export team performance metrics to an Excel file.

    Args:
        df (pd.DataFrame): DataFrame with team performance metrics.
        output_file (str): Path to the output Excel file.
        sheet_name (str): Name of the sheet to write to (default: "Team Performance").
    """
    import os
    # Use append mode if file exists, otherwise create new file
    file_mode = "a" if os.path.exists(output_file) else "w"
    with pd.ExcelWriter(output_file, engine="openpyxl", mode=file_mode, if_sheet_exists="replace") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


def add_team_performance_to_docx(df: pd.DataFrame, doc_path: str):
    """
    Add team performance ranking table to a Word document.

    Args:
        df (pd.DataFrame): DataFrame with team performance metrics.
        doc_path (str): Path to the Word document (with or without .docx extension).
    """
    from docx import Document
    from docx.shared import Pt

    # Ensure .docx extension is present
    if not doc_path.endswith('.docx'):
        doc_path = f"{doc_path}.docx"
    doc = Document(doc_path)
    doc.add_page_break()
    doc.add_heading("Team Performance Ranking", level=1)

    # Create table with headers
    table = doc.add_table(rows=1, cols=len(df.columns))
    table.style = "Table Grid"
    hdr_cells = table.rows[0].cells
    for i, column in enumerate(df.columns):
        hdr_cells[i].text = column

    # Populate table with data
    for _, row in df.iterrows():
        row_cells = table.add_row().cells
        for i, value in enumerate(row):
            row_cells[i].text = str(value)

    # Set font size for table content
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)

    doc.save(doc_path)
    print(f"Team Performance Ranking section added to: {doc_path}")


def calculate_role_metrics(jira_df: pd.DataFrame, members_df: pd.DataFrame, pr_df: pd.DataFrame):
    """
    Calculate role-specific metrics for engineers, test engineers, and project managers.

    Args:
        jira_df (pd.DataFrame): Jira data with columns: Status, Assignee, Type, Summary, Description,
                                Labels, Priority, Creator, Links.
        members_df (pd.DataFrame): Member data with columns: name, role, gitee_account, feedback_score (optional).
        pr_df (pd.DataFrame): PR data with columns: Login, Additions, Deletions, Reviewers.

    Returns:
        tuple: (pd.DataFrame, pd.Series) with role-based metrics and team averages.

    Requirements:
        - Jira data must include issue links with "relates to" relationships for Code Quality metric.
        - Labels (`testdev`, `test`, `testperf`, `documentation`, `critical`, `milestone`) must be consistently applied.
        - PR data must match `gitee_account` to `Login` for engineer metrics.
    """
    # Validate input DataFrames
    required_member_cols = ["name", "role", "gitee_account"]
    if not all(col in members_df.columns for col in required_member_cols):
        raise ValueError(f"members.xlsx must contain columns: {required_member_cols}")

    # Validate PR DataFrame columns only if it's not empty
    required_pr_cols = ["Login", "Additions", "Deletions", "Reviewers"]
    if not pr_df.empty:
        missing_cols = [col for col in required_pr_cols if col not in pr_df.columns]
        if missing_cols:
            # Create missing columns with default values instead of raising error
            for col in missing_cols:
                if col == "Reviewers":
                    pr_df[col] = ""
                else:
                    pr_df[col] = 0
            logger.warning(f"PR statistics file missing columns {missing_cols}, using default values")

    # Clean and preprocess input data
    members_df = members_df.copy()
    members_df["gitee_account"] = members_df["gitee_account"].fillna("")
    members_df["role"] = members_df["role"].str.lower().fillna("")
    members_df["name"] = members_df["name"].fillna("")

    jira_df["Labels"] = jira_df["Labels"].fillna("")
    jira_df["Summary"] = jira_df["Summary"].fillna("")
    jira_df["Description"] = jira_df["Description"].fillna("")
    jira_df["Priority"] = jira_df["Priority"].fillna("")
    jira_df["Creator"] = jira_df["Creator"].fillna("")
    jira_df["Links"] = jira_df["Links"].fillna("")  # Ensure Links column is available
    
    # Safely handle Reviewers column in pr_df (already created if missing above, but ensure it's filled)
    if not pr_df.empty and "Reviewers" in pr_df.columns:
        pr_df["Reviewers"] = pr_df["Reviewers"].fillna("")

    # Filter for resolved tasks
    resolved = jira_df[jira_df["Status"] == "Resolved"].copy()

    results = []
    for _, member in members_df[members_df["role"].isin(["engineer", "test engineer", "project manager"])].iterrows():
        name = member["name"]
        role = member["role"]
        gitee = member["gitee_account"]

        # Extract data for the current member
        person_data = resolved[resolved["Assignee"] == name]
        person_prs = pr_df[pr_df["Login"] == gitee] if gitee and not pr_df.empty else pd.DataFrame()

        if role == "engineer":
            # Calculate code volume from PR additions and deletions
            code_volume = person_prs[["Additions", "Deletions"]].sum().sum() if not person_prs.empty else 0

            # Calculate code quality: Count bugs linked to engineer's resolved tasks via "relates to"
            # Escape issue keys to prevent regex interpretation
            if not person_data.empty:
                escaped_keys = [re.escape(key) for key in person_data["Issue_key"].unique() if key]
                if escaped_keys:
                    keys_pattern = "|".join(escaped_keys)
                    bugs_on_tasks = len(jira_df[
                                            (jira_df["Type"] == "Bug") &
                                            (jira_df["Assignee"] != name) &
                                            (jira_df["Links"].str.contains("relates to", case=False, na=False)) &
                                            (jira_df["Links"].str.contains(keys_pattern, case=False, na=False, regex=True))
                                            ])
                else:
                    bugs_on_tasks = 0
            else:
                bugs_on_tasks = 0
            
            if bugs_on_tasks == 0 and not person_data.empty:
                logger.warning(f"No linked bugs found for engineer {name}")

            # Count documentation tasks
            doc_tasks = len(person_data[person_data["Labels"].str.contains("documentation", case=False, na=False)])

            # Count critical tasks (highest priority or critical label)
            criticals = len(person_data[
                                (person_data["Priority"].str.lower() == "highest") |
                                (person_data["Labels"].str.contains("critical", case=False, na=False))
                                ])

            # Count PR reviews where the engineer is a reviewer but not the author
            if not pr_df.empty and "Reviewers" in pr_df.columns and "Login" in pr_df.columns:
                reviewers = len(pr_df[
                                    (pr_df["Login"] != gitee) &
                                    (pr_df["Reviewers"].str.contains(name, case=False, na=False))
                                    ])
            else:
                reviewers = 0

            results.append({
                "Name": name,
                "Role": role,
                "Code Volume": code_volume,
                "Code Quality (Bugs)": bugs_on_tasks,
                "Documentation Quantity": doc_tasks,
                "Critical Tasks": criticals,
                "PR Reviews": reviewers
            })

        elif role == "test engineer":
            # Count test scenarios: Resolved issues with testdev or test labels
            test_cases = len(person_data[
                                 person_data["Labels"].str.contains("testdev|test", case=False, na=False, regex=True)
                             ])
            if test_cases == 0:
                logger.warning(f"No testdev or test labels found for test engineer {name}")

            # Count bugs reported by the test engineer
            reported_bugs = len(jira_df[
                                    (jira_df["Type"] == "Bug") &
                                    (jira_df["Creator"] == name)
                                    ])

            # Count performance benchmark tasks
            benchmarks = len(person_data[
                                 (person_data["Labels"].str.contains("testperf", case=False, na=False, regex=True)) &
                                 (person_data["Summary"].str.contains("benchmark|performance", case=False, na=False, regex=True) |
                                  person_data["Description"].str.contains("benchmark|performance", case=False, na=False, regex=True))
                                 ])

            results.append({
                "Name": name,
                "Role": role,
                "Test Cases": test_cases,
                "Bugs Reported": reported_bugs,
                "Performance Benchmarks": benchmarks
            })

        elif role == "project manager":
            # Count milestone tasks
            milestones = len(person_data[person_data["Labels"].str.contains("milestone", case=False, na=False)])

            # Count all resolved tasks, including Epics
            total_tasks = len(person_data[person_data["Type"] != "Epic"]) + \
                          len(person_data[person_data["Type"] == "Epic"])

            # Include optional feedback score from members.xlsx
            feedback_score = member.get("feedback_score", None)

            result = {
                "Name": name,
                "Role": role,
                "Milestones Closed": milestones,
                "Resolved Tasks": total_tasks
            }
            if feedback_score is not None:
                result["Feedback Score"] = feedback_score

            results.append(result)

    # Create DataFrame from results and calculate team averages
    df = pd.DataFrame(results)
    team_avg = df.mean(numeric_only=True)
    return df, team_avg


def export_role_metrics_to_excel(df: pd.DataFrame, team_avg: pd.Series, output_file: str):
    """
    Export role-based metrics to an Excel file with team averages.

    Args:
        df (pd.DataFrame): DataFrame with role-based metrics.
        team_avg (pd.Series): Series with team average metrics.
        output_file (str): Path to the output Excel file.
    """
    import os
    # Use append mode if file exists, otherwise create new file
    file_mode = "a" if os.path.exists(output_file) else "w"
    with pd.ExcelWriter(output_file, engine="openpyxl", mode=file_mode, if_sheet_exists="replace") as writer:
        df.to_excel(writer, sheet_name="Role-Based Metrics", index=False)

        # Append team averages to the sheet
        avg_row = pd.DataFrame([team_avg], columns=team_avg.index)
        avg_row.insert(0, "Name", "Team Average")
        avg_row.insert(1, "Role", "-")
        avg_row.to_excel(writer, sheet_name="Role-Based Metrics", index=False, header=False, startrow=len(df) + 2)


def add_role_metrics_to_docx(df: pd.DataFrame, team_avg: pd.Series, doc_path: str):
    """
    Add role-based metrics table to a Word document.

    Args:
        df (pd.DataFrame): DataFrame with role-based metrics.
        team_avg (pd.Series): Series with team average metrics.
        doc_path (str): Path to the Word document (with or without .docx extension).
    """
    from docx import Document
    from docx.shared import Pt

    # Ensure .docx extension is present
    if not doc_path.endswith('.docx'):
        doc_path = f"{doc_path}.docx"
    doc = Document(doc_path)
    doc.add_page_break()
    doc.add_heading("Role-Based Team Metrics", level=1)

    # Create table with headers
    table = doc.add_table(rows=1, cols=len(df.columns))
    table.style = "Table Grid"
    hdr_cells = table.rows[0].cells
    for i, col in enumerate(df.columns):
        hdr_cells[i].text = str(col)

    # Populate table with data
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val) if pd.notnull(val) else ""

    # Add team average row
    avg_cells = table.add_row().cells
    avg_cells[0].text = "Team Average"
    avg_cells[1].text = "-"
    for i, val in enumerate(team_avg.items(), start=2):
        avg_cells[i].text = f"{val[1]:.2f}" if pd.notnull(val[1]) else ""

    # Set font size for table content
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)

    doc.save(doc_path)