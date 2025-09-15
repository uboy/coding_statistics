#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import requests
import subprocess
import base64
import json
from configparser import ConfigParser
from tqdm import tqdm
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter

CONFIG_FILE = "config.ini"

class GiteeClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"token {token}"})

    def get_issue_templates(self, owner, repo):
        url = f"{self.base_url}/api/v5/repos/{owner}/{repo}/contents/.gitee/ISSUE_TEMPLATE"
        r = self.session.get(url)
        if r.status_code != 200:
            return []
        return r.json()

    def get_template_content(self, owner, repo, path):
        url = f"{self.base_url}/api/v5/repos/{owner}/{repo}/contents/{path}"
        r = self.session.get(url)
        if r.status_code != 200:
            return None
        content = base64.b64decode(r.json().get("content", "")).decode('utf-8')
        return content

    def create_issue(self, owner, repo, title, body, labels=[]):
        url = f"{self.base_url}/api/v5/repos/{owner}/{repo}/issues"
        data = {
            "title": title,
            "body": body,
            "labels": labels
        }
        r = self.session.post(url, json=data)
        r.raise_for_status()
        return r.json()

    def create_pull_request(self, owner, repo, title, body, head, base):
        url = f"{self.base_url}/api/v5/repos/{owner}/{repo}/pulls"
        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base
        }
        r = self.session.post(url, json=data)
        r.raise_for_status()
        return r.json()

    def list_pull_requests(self, owner, repo, state='open', author=None):
        url = f"{self.base_url}/api/v5/repos/{owner}/{repo}/pulls?state={state}"
        if author:
            url += f"&author={author}"
        r = self.session.get(url)
        r.raise_for_status()
        return r.json()

    def comment_pull_request(self, owner, repo, pr_number, comment):
        url = f"{self.base_url}/api/v5/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        data = {"body": comment}
        r = self.session.post(url, json=data)
        r.raise_for_status()
        return r.json()


def detect_git_repo():
    try:
        repo_url = subprocess.check_output(["git", "remote", "get-url", "origin"], stderr=subprocess.DEVNULL).decode().strip()
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        if "gitee.com" in repo_url:
            owner_repo = repo_url.split(":")[-1].replace(".git", "")
            owner, repo = owner_repo.split("/")
            return owner, repo, branch
    except:
        return None, None, None


def interactive_issue_input(template):
    sections = []
    for line in template.splitlines():
        if line.startswith("###"):
            q_chinese = line.strip("# ")
            q_english = translate_question(q_chinese)
            answer = prompt(f"{q_english}\n> ")
            sections.append(f"### {q_chinese}\n{answer}\n")
    return "\n".join(sections)

def translate_question(ch):
    translations = {
        "发生了什么问题？": "What happened?",
        "期望行为是什么？": "What was the expected behavior?",
        "如何复现该缺陷": "How to reproduce the issue?",
        "其他补充信息": "Other additional info",
        "版本或分支信息": "Version or branch info",
        "新需求提供了什么功能？": "What feature is provided?",
        "该需求带来的价值、应用场景？": "Value and application scenario of this feature?"
    }
    return translations.get(ch.strip(), ch)


def load_config():
    config = ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    base_url = config.get('gitee', 'gitee-url')
    token = config.get('gitee', 'token')
    return base_url, token


def main():
    parser = argparse.ArgumentParser(description="Gitee Utility Tool")
    subparsers = parser.add_subparsers(dest="command")

    # create-issue
    p_issue = subparsers.add_parser("create-issue")
    p_issue.add_argument("--repo", required=True)
    p_issue.add_argument("--type", choices=["bug", "feature"], required=True)
    p_issue.add_argument("--title")
    p_issue.add_argument("--desc-file")

    # create-pr
    p_pr = subparsers.add_parser("create-pr")
    p_pr.add_argument("--repo")
    p_pr.add_argument("--base", required=False)
    p_pr.add_argument("--desc-file")

    # comment-pr
    p_cmt = subparsers.add_parser("comment-pr")
    p_cmt.add_argument("--repo", required=True)
    p_cmt.add_argument("--pr-id")
    p_cmt.add_argument("--comment")

    # list-pr
    p_list = subparsers.add_parser("list-pr")
    p_list.add_argument("--repos")
    p_list.add_argument("--user")
    p_list.add_argument("--state", default="open")

    args = parser.parse_args()
    base_url, token = load_config()
    client = GiteeClient(base_url, token)

    if args.command == "create-issue":
        owner, repo = args.repo.split("/")
        templates = client.get_issue_templates(owner, repo)
        path = None
        for t in templates:
            if args.type in t['name']:
                path = t['path']
                break
        template = client.get_template_content(owner, repo, path) if path else ""
        if args.desc_file:
            with open(args.desc_file, 'r', encoding='utf-8') as f:
                body = f.read()
        else:
            body = interactive_issue_input(template or "")
        title = args.title or prompt("Issue Title > ")
        labels = ["Bug"] if args.type == "bug" else ["Enhancement"]
        result = client.create_issue(owner, repo, title, body, labels)
        print("✅ Issue created:", result['html_url'])

    elif args.command == "create-pr":
        owner, repo, branch = detect_git_repo()
        if not owner:
            repo_input = args.repo or prompt("Repository (owner/repo) > ")
            owner, repo = repo_input.split("/")
            branch = prompt("Current branch > ")
        base = args.base or prompt("Base branch > ")
        if args.desc_file:
            with open(args.desc_file, 'r', encoding='utf-8') as f:
                body = f.read()
        else:
            body = prompt("PR Description > ")
        title = body.splitlines()[0] if body else prompt("PR Title > ")
        print("Creating PR with the following info:")
        print("From branch:", branch)
        print("To branch:", base)
        print("Title:", title)
        confirm = prompt("Proceed? (yes/no) > ")
        if confirm.lower() == "yes":
            result = client.create_pull_request(owner, repo, title, body, branch, base)
            print("✅ PR created:", result['html_url'])

    elif args.command == "comment-pr":
        owner, repo = args.repo.split("/")
        pr_id = args.pr_id or prompt("Pull Request ID > ")
        comment = args.comment or prompt("Comment > ")
        result = client.comment_pull_request(owner, repo, pr_id, comment)
        print("✅ Comment added.")

    elif args.command == "list-pr":
        repos = args.repos.split(",") if args.repos else []
        user = args.user or prompt("Username > ")
        state = args.state
        for repo_full in repos:
            owner, repo = repo_full.split("/")
            print(f"\n📂 {repo_full}")
            prs = client.list_pull_requests(owner, repo, state, user)
            for pr in prs:
                print(f"- #{pr['number']} {pr['title']} [{pr['state']}] {pr['html_url']}")

if __name__ == "__main__":
    main()
