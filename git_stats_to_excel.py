import subprocess
import argparse
import os
from openpyxl import Workbook
from datetime import datetime


def get_git_log(repo_path, branch, since, until):
    if repo_path:
        os.chdir(repo_path)
    cmd = [
        "git", "log", branch,
        f"--since={since}",
        f"--until={until}",
        "--pretty=format:%H|%an|%ad|%s",
        "--numstat",
        "--date=short"
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    lines = result.stdout.splitlines()

    commits = []
    current_commit = None

    for line in lines:
        if '|' in line:
            if current_commit:
                commits.append(current_commit)
            parts = line.strip().split("|", 3)
            current_commit = {
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "subject": parts[3],
                "insertions": 0,
                "deletions": 0
            }
        elif line.strip():
            parts = line.strip().split("\t")
            if len(parts) == 3:
                added, deleted, _ = parts
                added = int(added) if added.isdigit() else 0
                deleted = int(deleted) if deleted.isdigit() else 0
                current_commit["insertions"] += added
                current_commit["deletions"] += deleted

    if current_commit:
        commits.append(current_commit)

    return commits


def save_to_excel(commits, output_filename):
    wb = Workbook()
    ws = wb.active
    ws.title = "Git Stats"

    # Заголовки
    ws.append(["Commit", "Author", "Date", "Additions", "Deletions", "Subject"])

    for c in commits:
        ws.append([
            c["hash"],
            c["author"],
            c["date"],
            c["insertions"],
            c["deletions"],
            c["subject"]
        ])

    wb.save(output_filename)
    print(f"[✔] Сохранено в файл: {output_filename}")


def main():
    parser = argparse.ArgumentParser(description="Git commit statistics to Excel")
    parser.add_argument("--repo", help="Path to the git repository (optional)")
    parser.add_argument("--branch", required=True, help="Branch name to scan")
    parser.add_argument("--since", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--until", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", default="git_stats.xlsx", help="Output Excel file name")

    args = parser.parse_args()

    commits = get_git_log(args.repo, args.branch, args.since, args.until)
    save_to_excel(commits, args.output)


if __name__ == "__main__":
    main()
