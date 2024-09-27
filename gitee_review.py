# -*- coding: utf-8 -*-
import json
import sys  ###
import requests  ###
import csv  ###
import codecs  ### used for text encoding in config parser
import argparse  ### good argument parser
import logging  ###
import re  ### for parsing ticket no from description
from openpyxl import load_workbook  ###
from configparser import ConfigParser  ### able to read configuration file
from datetime import datetime  ### used for manipulations with dates

#from pkg_resources import empty_provider

CONFIG_POINT_LOCAL = "gitee"
CONFIG_POINT_GLOBAL = "global"
CONFIG_FILE = "config.ini"
CONFIG_BASE_URL = "gitee-url"
CONFIG_TOKEN = "token"
CONFIG_MEMBER_LIST = "member-list"
CONFIG_BRANCH = "branch"
CONFIG_REPOSITORY = "repository"


def main():
    ### argument parsing section
    tool_description = 'Track commit by using Gitee API'
    parser = argparse.ArgumentParser(description=tool_description,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-t', '--token', dest='token', help='token')
    parser.add_argument('-l', '--url-link', dest='base_url', help='the gitee url')
    parser.add_argument('-f', '--file', dest='member_list_file', help='Group member list file')
    parser.add_argument('-b', '--branch', dest='branch',
                        help='Branch to get report for all projects. Can be comma separated list like "master,dev,main"')
    parser.add_argument('-p', '--project', dest='project',
                        help='Specify project for report path with namespace. Possible to specify several project separated by comma"')
    parser.add_argument('-d', '--date', dest='date_since', required=True,
                        help='query date string since, eg. 2019-06-25')
    parser.add_argument('-u', '--until', dest='date_until', required=False,
                        help='query date string until, eg. 2019-12-25')
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='enable verbose (debug) logging')
    options = parser.parse_args()
    level = logging.DEBUG if options.verbose else logging.INFO
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=level)

    base_url = options.base_url
    token = options.token
    since = options.date_since
    until = options.date_until
    branch = options.branch
    project_name = options.project

    if until is None:
        until = datetime.today().strftime('%Y-%m-%d')
    member_list_file = options.member_list_file
    ###
    ### config file section
    config = ConfigParser()
    config.read_file(codecs.open(CONFIG_FILE, 'r', encoding='utf-8-sig'))

    if base_url is None:
        base_url = config.get(CONFIG_POINT_LOCAL, CONFIG_BASE_URL)
    if token is None:
        token = config.get(CONFIG_POINT_LOCAL, CONFIG_TOKEN)
    if branch is None:
        branch_list = config.get(CONFIG_POINT_LOCAL, CONFIG_BRANCH).split(",")
    if member_list_file is None:
        member_list_file = config.get(CONFIG_POINT_GLOBAL, CONFIG_MEMBER_LIST)
    ###

    if base_url is None or token is None or member_list_file is None or branch_list is None:
        raise ValueError("url or token or file is invalid")

    member_list = read_member_list("members.xlsx")
    s = requests.Session()
    s.headers = {'Private-Token': token}
    ### bundle-ca is a text file with certificate in Base64 format of intermediate CA and root CA. Used for self-signed certificates which does not exist in certifi
    #s.verify = 'bundle-ca'
    if project_name is None:
        #ids = get_contribute_project_ids(base_url, s, since, until)
        ids = config.get(CONFIG_POINT_LOCAL, CONFIG_REPOSITORY).split("/")[0]
    else:
        #ids = get_project_id_by_name(base_url, s, project_name)
        ids = project_name.split("/")[0]
    project_report = []
    project_num = len(ids)
#https://gitee.com/api/v5/repos/openharmony/arkui_ace_engine/pulls?base=master&since=2024-09-25T00:00:00Z&per_page=100&page=1
    # get comma-separated reposotories with projects
    repositories = config.get(CONFIG_POINT_LOCAL, CONFIG_REPOSITORY).split(",")
    for repository in repositories:
        branches = config.get(CONFIG_POINT_LOCAL, CONFIG_BRANCH)
        repo_string = repository.split('/')
        repo_owner = repo_string[0]
        repo = repo_string[1]

        for branch in branches:
            prs = get_all_prs(s, base_url, repo_owner, repo, branch, since)
            for c in prs:
                user_name = c['user']['name']
                user_login = c['user']['login']
                pr_title = c['title']
                pr_url = c['html_url']
                pr_state = c['state']
                pr_date = c['created_at']
                pr_merged_date = c['merged_at']
                description = c['body']
                ### combining all data into array
                project_report.append({
                    'Name': user_name['Name'],
                    'Project': "project_info['path_with_namespace']",
                    'Date': pr_date,
                    'Gitlab id': pr_url,
                    'branch': branch,
                    'description': description,
                    'LOC': total
                })
            idx += 1
    ### TODO comments in other team member's code and KLOCs reviewed
    # get_users_comments
    ### Create a report file with headlines
    file_name = "gitlab-commits-" + since + ".csv"
    create_csv_file(file_name)

    with open(file_name, "a", encoding='utf-8-sig', newline='') as csvfile:
        writer = csv.writer(csvfile)
        for commit in project_report:
            writer.writerow([commit['Name'],
                             commit['Project'],
                             str(commit['Date']),
                             str(commit['Gitlab id']),
                             commit['branch'],
                             commit['description'],
                             str(commit['LOC']),
                             commit['Reviewed By'],
                             commit['AR'],
                             str(commit['change_inner_group_comments_count']),
                             str(commit['change_outer_group_comments_count'])
                             ])
    print("All done!")
    return 0


def get_contribute_project_ids(base_url, session, since, until):
    '''

    :param base_url:
    :param session:
    :param since:
    :param until:
    :return:
    '''
    res = {}
    next_page = 1
    while next_page != '':
        ### TODO, fix after and before for events, currently they do not include borders
        url = '{}/api/v4/events?per_page=100&page={}&action=pushed&after={}&before={}'.format(base_url, next_page, "",
                                                                                              "")
        resp = session.get(url)
        next_page = resp.headers.get('X-Next-Page')
        for event in resp.json():
            project_id = event['project_id']
            if not res.__contains__(project_id):
                res[project_id] = True
    return res


def get_all_prs(session, base_url, project_id, repository, branch, since):
    res = []
    next_page = 1
    total_pages: int = 1 # at this stage total pages is not known
    # see https://gitee.com/api/v5/swagger#/getV5ReposOwnerRepoPulls
    url_format = '{}/api/v5/repos/{}/{}/pulls?base={}&since={}&per_page=100&page={}'
    while True:
        url = url_format.format(base_url, project_id, repository, branch, since + "T00:00:00Z", next_page)
        resp = session.get(url)
        total_pages = int(resp.headers.get('total_page'))
        res.extend(resp.json())
        if total_pages - next_page == 0:
            break
        else:
            next_page += 1
    return res


def get_commit_detail(base_url, session, project_id, commit_id):
    url = '{}/api/v5/projects/{}/repository/commits/{}'.format(base_url, project_id, commit_id)
    resp = session.get(url)
    return resp.json()


def get_commit_comments_count(base_url, session, project_id, commit_id, member_list, commit_author):
    url = '{}/api/v4/projects/{}/repository/commits/{}/comments'.format(base_url, project_id, commit_id)
    resp = session.get(url)
    inner = 0
    outer = 0
    reviewers = []
    for comment in resp.json():
        if commit_author != comment['author']['username']:
            filter_result = list(
                filter(lambda author: author['Username'] == comment['author']['username'], member_list))
            if filter_result:
                inner += 1
                reviewers.append(comment['author']['name'])
            else:
                outer += 1
    return (inner, outer, reviewers)


def read_member_list(member_list_file):
    wb = load_workbook(member_list_file)
    sheet = wb.active
    has_name = "name" == sheet.cell(row=1, column=1).value
    has_mail = "email" == sheet.cell(row=1, column=2).value
    has_username = "username" == sheet.cell(row=1, column=3).value
    has_giteeaccount = "gitee_account" == sheet.cell(row=1, column=4).value

    member_list = []
    if has_name and has_mail and has_username and has_giteeaccount:
        for rx in range(2, sheet.max_row + 1):
            name = sheet.cell(row=rx, column=1).value
            mail = sheet.cell(row=rx, column=2).value
            username = sheet.cell(row=rx, column=3).value
            gitee_account = sheet.cell(row=rx, column=4).value
            member_list.append({'Name': name, 'Email': mail, 'Username': username, 'GiteeAccount': gitee_account})
    else:
        raise ValueError("The table format is incorrect")
    return member_list


def get_project_id_by_name(base_url, session, project_name):
    projects = project_name.split(",")
    project_id = []
    for project in projects:
        url = '{}/api/v4/search?scope=projects&search={}'.format(base_url, project)
        resp = session.get(url)
        project_id.append(resp.json()[0]['id'])
    return project_id


def create_csv_file(file_name):
    # Write Title
    with open(file_name, "w", encoding='utf-8-sig', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Name", "Project", "Date", "Gitlab id", "branch", "description", "LOC", "Reviewed By", "AR",
                         "change_inner_group_comments_count", "change_outer_group_comments_count"])



if __name__ == '__main__':
    sys.exit(main())  ### TODO check exit code
