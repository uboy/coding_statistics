import pandas as pd
import random

# Настройки проекта
project_key = "TEST"
issue_types = ["Epic", "Story", "Bug", "Task"]
number_of_issues = 100
epic_count = 5
issues_per_epic = 15

# Генерация данных
data = []
epic_keys = []

for i in range(number_of_issues):
    issue_type = "Epic" if i < epic_count else random.choice(issue_types[1:])
    summary = f"{issue_type} Summary {i+1}"
    description = f"Description for {summary}"
    key = f"{project_key}-{i+1}"

    if issue_type == "Epic":
        epic_keys.append(key)
        epic_name = f"Epic {i+1}"
    else:
        epic_name = random.choice(epic_keys) if len(epic_keys) > 0 else ""

    row = {
        "Issue Key": key,
        "Project Key": project_key,
        "Issue Type": issue_type,
        "Summary": summary,
        "Description": description,
        "Epic Link": epic_name if issue_type != "Epic" else ""
    }
    data.append(row)

# Создание DataFrame
df = pd.DataFrame(data)

# Сохранение в CSV
file_path = "jira_import_test.csv"
df.to_csv(file_path, index=False)

file_path
