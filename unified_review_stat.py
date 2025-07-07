# -*- coding: utf-8 -*-
import requests
import re
import csv
import openpyxl
import os
import sys
import logging
import urllib.parse
from datetime import datetime
from requests.auth import HTTPBasicAuth
from configparser import ConfigParser

CONFIG_FILE = "config.ini"
OUTPUT_FILE = "review_summary.xlsx"
INPUT_FILE = "input.txt"

HEADERS = [
    "Name", "Login", "PR_Name", "PR_URL", "PR_State",
    "PR_Created_Date", "PR_Merged_Date", "branch", "Repo",
    "Additions", "Deletions", "Reviewers"
]

def load_config():
    config = ConfigParser()
    config.read(CONFIG_FILE, encoding="utf-8-sig")
    return config

def init_session(token=None):
    s = requests.Session()
    if token:
        s.headers = {"Private-Token": token}
    s.verify = 'bundle-ca' if os.path.exists("bundle-ca") else True
    return s

def parse_links(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

# ---------------------- Gitee / GitCode ----------------------
def process_gitee_or_gitcode(url, config, platform):
    base_url = config.get(platform, f"{platform}-url")
    token = config.get(platform, "token")
    session = init_session(token)

    m_pr = re.match(r"https://(gitee\.com|gitcode\.net)/([^/]+)/([^/]+)/pulls/(\d+)", url)
    if m_pr:
        _, owner, repo, pr_id = m_pr.groups()
        api_url = f"{base_url}/api/v5/repos/{owner}/{repo}/pulls/{pr_id}"
        files_url = f"{api_url}/files"
        pr = session.get(api_url).json()
        files = session.get(files_url).json()

        additions = sum(int(f['additions']) for f in files)
        deletions = sum(int(f['deletions']) for f in files)
        reviewers = ', '.join([r['login'] for r in pr.get('assignees', []) if r.get('accept', True)])

    return [
        pr['user']['name'], pr['user']['login'], pr['title'], url,
        pr['state'], pr['created_at'], pr['merged_at'],
        pr['base']['ref'], f"{owner}/{repo}", additions, deletions, reviewers
    ]

    m_commit = re.match(r"https://(gitee\.com|gitcode\.net)/([^/]+)/([^/]+)/commit/([0-9a-fA-F]+)", url)
    if m_commit:
        _, owner, repo, sha = m_commit.groups()
        commit_url = f"{base_url}/api/v5/repos/{owner}/{repo}/commits/{sha}"
        commit = session.get(commit_url).json()

        additions = commit.get('stats', {}).get('additions', 0)
        deletions = commit.get('stats', {}).get('deletions', 0)
        return [
            commit['author']['name'], commit['author']['name'], commit['commit']['message'].splitlines()[0], url,
            'committed', commit['commit']['author']['date'], '',
            '', f"{owner}/{repo}", additions, deletions, ''
        ]

    return None

# ---------------------- GitLab ----------------------
def process_gitlab(url, config):
    base_url = config.get("gitlab", "gitlab-url")
    token = config.get("gitlab", "token")
    session = init_session(token)
    m = re.match(r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)", url.replace('#/', ''))
    if not m:
        return None
    domain, repo_path, mr_id = m.groups()

    encoded_path = urllib.parse.quote(repo_path, safe='')
    api_url = f"{base_url}/api/v4/projects/{encoded_path}/merge_requests/{mr_id}"
    changes_url = f"{api_url}/changes"
    pr = session.get(api_url).json()
    changes = session.get(changes_url).json()

    additions = sum(f['additions'] for f in changes.get('changes', []))
    deletions = sum(f['deletions'] for f in changes.get('changes', []))
    reviewers = pr.get('reviewed_by', [])
    reviewer_names = ', '.join([r['name'] for r in reviewers]) if reviewers else ""

    return [
        pr['author']['name'], pr['author']['username'], pr['title'], url,
        pr['state'], pr['created_at'], pr['merged_at'],
        pr['target_branch'], repo_path, additions, deletions, reviewer_names
    ]


# ---------------------- CodeHub ----------------------
def process_codehub(url, config, platform):
    base_url = config.get(platform, f"{platform}-url")
    token = config.get(platform, "token")
    session = init_session(token)

    if platform == "opencodehub":
        mr_match = re.match(r"https://([^/]+)/OpenSourceCenter_CR/([^/]+/[^/]+)/-/change_requests/(\d+)", url.replace('#/', ''))
        commit_match = re.match(r"https://([^/]+)/OpenSourceCenter_CR/([^/]+/[^/]+)/-/commit/([0-9A-Fa-f]+)", url.replace('#/', ''))
        project_prefix = "OpenSourceCenter_CR%2F"
    elif platform == "codehub-y":
        mr_match = re.match(r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)", url.replace('#/', ''))
        commit_match = re.match(r"https://([^/]+)/([^/]+/[^/]+)/files/commit/([0-9A-Fa-f]+)", url.replace('#/', ''))
    elif platform == "cr-y.codehub":
        mr_match = re.match(r"https://([^/]+)/([^/]+/[^/]+)/change_requests/(\d+)", url.replace('#/', ''))
        commit_match = re.match(r"https://([^/]+)/([^/]+/[^/]+)/files/commit/([0-9A-Fa-f]+)", url.replace('#/', ''))
    else:
        mr_match = re.match(r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)", url.replace('#/', ''))
        commit_match = re.match(r"https://([^/]+)/([^/]+/[^/]+)/files/commit/([0-9A-Fa-f]+)", url.replace('#/', ''))
        project_prefix = ""

    if mr_match:
        domain, repo_path, mr_id = mr_match.groups()
        encoded_path = urllib.parse.quote(repo_path, safe='')
        api_url = f"{base_url}/api/v4/projects/{project_prefix}{encoded_path}/isource/merge_requests/{mr_id}"
        changes_url = f"{api_url}/changes"
        pr = session.get(api_url).json()
        changes = session.get(changes_url).json()

        additions = sum(int(f['added_lines']) for f in changes.get('changes', []))
        deletions = sum(int(f['removed_lines']) for f in changes.get('changes', []))
        reviewers = pr.get('merge_request_reviewer_list', [])
        reviewer_names = ', '.join([r['name'] for r in reviewers]) if reviewers else ""

        return [
            pr['author']['name'], pr['author']['username'], pr['title'], url,
            pr['state'], pr['created_at'], pr['merged_at'],
            pr['target_branch'], repo_path, additions, deletions, reviewer_names
        ]

    if commit_match:
        domain, repo_path, commit_id = commit_match.groups()
        encoded_path = urllib.parse.quote(repo_path, safe='')
        api_url = f"{base_url}/api/v4/projects/{project_prefix}{encoded_path}/repository/commits/{commit_id}"
        commit = session.get(api_url).json()
        additions = commit.get('stats', {}).get('additions', 0)
        deletions = commit.get('stats', {}).get('deletions', 0)

        return [
            commit['author_name'], commit['author_name'], commit['title'], url,
            'committed', commit['created_at'], '', '', repo_path,
            additions, deletions, ''
        ]

    return None


# ---------------------- Gerrit ----------------------
def process_gerrit(url, config):
    m = re.match(r"https?://([^/#]+)/.*/(\d+)/?", url)
    if not m:
        return None
    domain, change_id = m.groups()
    base_url = config.get("gerrit", "gerrit-url")
    username = config.get("gerrit", "username")
    password = config.get("gerrit", "password")
    auth = HTTPBasicAuth(username, password)
    session = init_session()

    api_url = f"{base_url}/a/changes/{change_id}/detail"
    resp = session.get(api_url, auth=auth)
    if resp.status_code != 200:
        return None
    raw_text = resp.text.lstrip(")]}'\n")
    data = requests.utils.json.loads(raw_text)

    owner = data['owner']
    revisions = list(data['revisions'].values())[0]
    stats = revisions.get('insertions', 0), revisions.get('deletions', 0)

    reviewers = data.get('reviewers', {}).get('REVIEWER', [])
    reviewer_names = ', '.join([r['name'] for r in reviewers if r['name'] != owner['name']])

    return [
        owner['name'], owner['username'], data['subject'], url,
        data['status'].lower(), data['created'], data.get('submitted'),
        data['branch'], data['project'], stats[0], stats[1], reviewer_names
    ]


# ---------------------- Export ----------------------
def export_to_excel(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    wb.save(OUTPUT_FILE)
    print(f"Saved report to {OUTPUT_FILE}")


# ---------------------- Main ----------------------
def main():
    config = load_config()
    links = parse_links(INPUT_FILE)
    results = []
    for link in links:
        try:
            if 'gitee.com' in link:
                row = process_gitee_or_gitcode(link, config, 'gitee')
            elif 'gitcode.net' in link:
                row = process_gitee_or_gitcode(link, config, 'gitcode')
            elif 'gitlab' in link:
                row = process_gitlab(link, config)
            elif 'codehub-y' in link:
                row = process_codehub(link, config, 'codehub-y')
            elif 'cr-y.codehub' in link:
                row = process_codehub(link, config, 'cr-y.codehub')
            elif 'open.codehub' in link:
                row = process_codehub(link, config, 'opencodehub')
            elif 'codehub' in link:
                row = process_codehub(link, config, 'codehub')
            elif 'gerrit' in link or 'mgit' in link:
                row = process_gerrit(link, config)
            else:
                print(f"Unknown platform in URL: {link}")
                continue
            if row:
                results.append(row)
            else:
                print(f"Failed to fetch data for: {link}")
        except Exception as e:
            print(f"Error processing {link}: {e}")

    export_to_excel(results)


if __name__ == '__main__':
    main()
