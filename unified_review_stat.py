# -*- coding: utf-8 -*-
"""
Скрипт для сбора статистики по замерженному коду из различных Git-платформ.
Поддерживает: Gitee, GitCode, GitLab, CodeHub, Gerrit.
"""
import requests
import re
import openpyxl
import os
import sys
import logging
import urllib.parse
import json
from datetime import datetime
from requests.auth import HTTPBasicAuth
from configparser import ConfigParser
from typing import List, Optional, Dict, Any
from time import sleep

# Константы
CONFIG_FILE = "config.ini"
OUTPUT_FILE = "review_summary.xlsx"
INPUT_FILE = "input.txt"
MAX_RETRIES = 3
RETRY_DELAY = 2  # секунды

HEADERS = [
    "Name", "Login", "PR_Name", "PR_URL", "PR_State",
    "PR_Created_Date", "PR_Merged_Date", "branch", "Repo",
    "Additions", "Deletions", "Reviewers"
]

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('review_stats.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_config() -> ConfigParser:
    """Загружает конфигурацию из INI-файла."""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Файл конфигурации {CONFIG_FILE} не найден!")
        sys.exit(1)

    config = ConfigParser()
    config.read(CONFIG_FILE, encoding="utf-8-sig")
    return config


def init_session(token: Optional[str] = None) -> requests.Session:
    """Инициализирует сессию с необходимыми заголовками."""
    s = requests.Session()
    if token:
        s.headers = {"Private-Token": token}
    s.verify = 'bundle-ca' if os.path.exists("bundle-ca") else True
    return s


def make_api_request(session: requests.Session, url: str,
                     auth: Optional[HTTPBasicAuth] = None,
                     max_retries: int = MAX_RETRIES) -> Optional[Dict[Any, Any]]:
    """
    Выполняет API-запрос с повторными попытками при ошибках.

    Args:
        session: Сессия requests
        url: URL для запроса
        auth: Объект аутентификации (опционально)
        max_retries: Максимальное количество повторных попыток

    Returns:
        JSON-ответ или None при ошибке
    """
    for attempt in range(max_retries):
        try:
            resp = session.get(url, auth=auth, timeout=30)
            resp.raise_for_status()

            # Специальная обработка для Gerrit (префикс )]}')
            text = resp.text
            if text.startswith(")]}'\n"):
                text = text[5:]

            return json.loads(text)

        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP ошибка {e.response.status_code} для {url}")
            if e.response.status_code == 404:
                logger.error(f"Ресурс не найден: {url}")
                return None
            if e.response.status_code == 401:
                logger.error(f"Ошибка аутентификации для {url}")
                return None

        except requests.exceptions.RequestException as e:
            logger.warning(f"Попытка {attempt + 1}/{max_retries} не удалась для {url}: {e}")

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON для {url}: {e}")
            return None

        if attempt < max_retries - 1:
            sleep(RETRY_DELAY)

    logger.error(f"Не удалось получить данные после {max_retries} попыток: {url}")
    return None


def parse_links(file_path: str) -> List[str]:
    """Читает ссылки из входного файла."""
    if not os.path.exists(file_path):
        logger.error(f"Входной файл {file_path} не найден!")
        sys.exit(1)

    with open(file_path, 'r', encoding='utf-8') as f:
        links = [line.strip() for line in f if line.strip()]

    logger.info(f"Загружено {len(links)} ссылок из {file_path}")
    return links


def safe_get(data: Dict, *keys, default=0):
    """Безопасное получение вложенных значений из словаря."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, {})
        else:
            return default
    return data if data != {} else default


# ---------------------- Gitee / GitCode ----------------------
def process_gitee_or_gitcode(url: str, config: ConfigParser,
                             platform: str) -> Optional[List]:
    """Обрабатывает ссылки Gitee, GitCode.net или GitCode.com (PR и коммиты)."""
    try:
        base_url = config.get(platform, f"{platform}-url")
        token = config.get(platform, "token", fallback=None)
    except Exception as e:
        logger.error(f"Ошибка чтения конфигурации для {platform}: {e}")
        return None

    session = init_session(token)

    # Проверка PR
    m_pr = re.match(r"https://(gitee\.com|gitcode\.net|gitcode\.com)/([^/]+)/([^/]+)/pull(s)?/(\d+)", url)
    if m_pr:
        _, owner, repo, pr_id = m_pr.groups()
        api_url = f"{base_url}/api/v5/repos/{owner}/{repo}/pulls/{pr_id}"
        files_url = f"{api_url}/files"

        pr = make_api_request(session, api_url)
        if not pr:
            return None

        files = make_api_request(session, files_url)
        if not files:
            files = []

        additions = sum(int(f.get('additions', 0)) for f in files)
        deletions = sum(int(f.get('deletions', 0)) for f in files)
        reviewers = ', '.join([r['login'] for r in pr.get('assignees', [])
                               if r.get('accept', True)])

        return [
            safe_get(pr, 'user', 'name', default='Unknown'),
            safe_get(pr, 'user', 'login', default='Unknown'),
            pr.get('title', 'No title'),
            url,
            pr.get('state', 'unknown'),
            pr.get('created_at', ''),
            pr.get('merged_at', ''),
            safe_get(pr, 'base', 'ref', default=''),
            f"{owner}/{repo}",
            additions,
            deletions,
            reviewers
        ]

    # Проверка коммита
    m_commit = re.match(r"https://(gitee\.com|gitcode\.net|gitcode\.com)/([^/]+)/([^/]+)/commit/([0-9a-fA-F]+)", url)
    if m_commit:
        _, owner, repo, sha = m_commit.groups()
        commit_url = f"{base_url}/api/v5/repos/{owner}/{repo}/commits/{sha}"
        commit = make_api_request(session, commit_url)

        if not commit:
            return None

        additions = safe_get(commit, 'stats', 'additions')
        deletions = safe_get(commit, 'stats', 'deletions')

        return [
            safe_get(commit, 'author', 'name', default='Unknown'),
            safe_get(commit, 'author', 'name', default='Unknown'),
            safe_get(commit, 'commit', 'message', default='').splitlines()[0],
            url,
            'committed',
            safe_get(commit, 'commit', 'author', 'date', default=''),
            '',
            '',
            f"{owner}/{repo}",
            additions,
            deletions,
            ''
        ]

    logger.warning(f"URL не соответствует формату Gitee/GitCode: {url}")
    return None


# ---------------------- GitLab ----------------------
def process_gitlab(url: str, config: ConfigParser) -> Optional[List]:
    """Обрабатывает ссылки GitLab."""
    try:
        base_url = config.get("gitlab", "gitlab-url")
        token = config.get("gitlab", "token", fallback=None)
    except Exception as e:
        logger.error(f"Ошибка чтения конфигурации для GitLab: {e}")
        return None

    session = init_session(token)
    m = re.match(r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)", url.replace('#/', ''))

    if not m:
        logger.warning(f"URL не соответствует формату GitLab: {url}")
        return None

    domain, repo_path, mr_id = m.groups()
    encoded_path = urllib.parse.quote(repo_path, safe='')
    api_url = f"{base_url}/api/v4/projects/{encoded_path}/merge_requests/{mr_id}"
    changes_url = f"{api_url}/changes"

    pr = make_api_request(session, api_url)
    if not pr:
        return None

    changes = make_api_request(session, changes_url)
    if not changes:
        changes = {}

    additions = sum(f.get('additions', 0) for f in changes.get('changes', []))
    deletions = sum(f.get('deletions', 0) for f in changes.get('changes', []))
    reviewers = pr.get('reviewed_by', [])
    reviewer_names = ', '.join([r['name'] for r in reviewers]) if reviewers else ""

    return [
        safe_get(pr, 'author', 'name', default='Unknown'),
        safe_get(pr, 'author', 'username', default='Unknown'),
        pr.get('title', 'No title'),
        url,
        pr.get('state', 'unknown'),
        pr.get('created_at', ''),
        pr.get('merged_at', ''),
        pr.get('target_branch', ''),
        repo_path,
        additions,
        deletions,
        reviewer_names
    ]


# ---------------------- CodeHub ----------------------
def process_codehub(url: str, config: ConfigParser, platform: str) -> Optional[List]:
    """Обрабатывает ссылки CodeHub (различные варианты)."""
    try:
        base_url = config.get(platform, f"{platform}-url")
        token = config.get(platform, "token", fallback=None)
    except Exception as e:
        logger.error(f"Ошибка чтения конфигурации для {platform}: {e}")
        return None

    session = init_session(token)
    url_clean = url.replace('#/', '')

    # Определение паттернов для разных платформ
    patterns = {
        "opencodehub": {
            "mr": r"https://([^/]+)/OpenSourceCenter_CR/([^/]+/[^/]+)/-/change_requests/(\d+)",
            "commit": r"https://([^/]+)/OpenSourceCenter_CR/([^/]+/[^/]+)/-/commit/([0-9A-Fa-f]+)",
            "prefix": "OpenSourceCenter_CR%2F"
        },
        "codehub-y": {
            "mr": r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)",
            "commit": r"https://([^/]+)/([^/]+/[^/]+)/files/commit/([0-9A-Fa-f]+)",
            "prefix": ""
        },
        "cr-y.codehub": {
            "mr": r"https://([^/]+)/(.*)/-/change_requests/(\d+)",
            "commit": r"https://([^/]+)/(.*)/files/commit/([0-9A-Fa-f]+)",
            "prefix": ""
        },
        "codehub": {
            "mr": r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)",
            "commit": r"https://([^/]+)/([^/]+/[^/]+)/files/commit/([0-9A-Fa-f]+)",
            "prefix": ""
        }
    }

    pattern_config = patterns.get(platform, patterns["codehub"])
    mr_match = re.match(pattern_config["mr"], url_clean)
    commit_match = re.match(pattern_config["commit"], url_clean)
    project_prefix = pattern_config["prefix"]

    if mr_match:
        domain, repo_path, mr_id = mr_match.groups()
        encoded_path = urllib.parse.quote(repo_path, safe='')
        api_url = f"{base_url}/api/v4/projects/{project_prefix}{encoded_path}/isource/merge_requests/{mr_id}"
        changes_url = f"{api_url}/changes"

        pr = make_api_request(session, api_url)
        if not pr:
            return None

        changes = make_api_request(session, changes_url)
        if not changes:
            changes = {}

        additions = sum(int(f.get('added_lines', 0)) for f in changes.get('changes', []))
        deletions = sum(int(f.get('removed_lines', 0)) for f in changes.get('changes', []))
        reviewers = pr.get('merge_request_reviewer_list', [])
        reviewer_names = ', '.join([r['name'] for r in reviewers]) if reviewers else ""

        return [
            safe_get(pr, 'author', 'name', default='Unknown'),
            safe_get(pr, 'author', 'username', default='Unknown'),
            pr.get('title', 'No title'),
            url,
            pr.get('state', 'unknown'),
            pr.get('created_at', ''),
            pr.get('merged_at', ''),
            pr.get('target_branch', ''),
            repo_path,
            additions,
            deletions,
            reviewer_names
        ]

    if commit_match:
        domain, repo_path, commit_id = commit_match.groups()
        encoded_path = urllib.parse.quote(repo_path, safe='')
        api_url = f"{base_url}/api/v4/projects/{project_prefix}{encoded_path}/repository/commits/{commit_id}"

        commit = make_api_request(session, api_url)
        if not commit:
            return None

        additions = safe_get(commit, 'stats', 'additions')
        deletions = safe_get(commit, 'stats', 'deletions')

        return [
            commit.get('author_name', 'Unknown'),
            commit.get('author_name', 'Unknown'),
            commit.get('title', 'No title'),
            url,
            'committed',
            commit.get('created_at', ''),
            '',
            '',
            repo_path,
            additions,
            deletions,
            ''
        ]

    logger.warning(f"URL не соответствует формату {platform}: {url}")
    return None


# ---------------------- Gerrit ----------------------
def process_gerrit(url: str, config: ConfigParser) -> Optional[List]:
    """Обрабатывает ссылки Gerrit."""
    m = re.match(r"https?://([^/#]+)/.*/(\d+)/?", url)
    if not m:
        logger.warning(f"URL не соответствует формату Gerrit: {url}")
        return None

    domain, change_id = m.groups()

    try:
        base_url = config.get("gerrit", "gerrit-url")
        username = config.get("gerrit", "username")
        password = config.get("gerrit", "password")
    except Exception as e:
        logger.error(f"Ошибка чтения конфигурации для Gerrit: {e}")
        return None

    auth = HTTPBasicAuth(username, password)
    session = init_session()

    api_url = f"{base_url}/a/changes/{change_id}/detail"
    data = make_api_request(session, api_url, auth=auth)

    if not data:
        return None

    owner = data.get('owner', {})
    revisions = list(data.get('revisions', {}).values())

    if revisions:
        insertions = revisions[0].get('insertions', 0)
        deletions = revisions[0].get('deletions', 0)
    else:
        insertions = deletions = 0

    reviewers = data.get('reviewers', {}).get('REVIEWER', [])
    owner_name = owner.get('name', 'Unknown')
    reviewer_names = ', '.join([r['name'] for r in reviewers
                                if r.get('name') != owner_name])

    return [
        owner_name,
        owner.get('username', 'Unknown'),
        data.get('subject', 'No subject'),
        url,
        data.get('status', 'unknown').lower(),
        data.get('created', ''),
        data.get('submitted', ''),
        data.get('branch', ''),
        data.get('project', ''),
        insertions,
        deletions,
        reviewer_names
    ]


# ---------------------- Export ----------------------
def export_to_excel(rows: List[List], output_file: str = OUTPUT_FILE) -> None:
    """Экспортирует данные в Excel файл."""
    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Review Summary"

        # Заголовки
        ws.append(HEADERS)

        # Данные
        for row in rows:
            ws.append(row)

        # Автоматическая ширина колонок
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width

        wb.save(output_file)
        logger.info(f"✓ Данные успешно сохранены в {output_file}")
        logger.info(f"  Всего записей: {len(rows)}")

    except Exception as e:
        logger.error(f"Ошибка при сохранении Excel файла: {e}")
        sys.exit(1)


# ---------------------- Main ----------------------
def main():
    """Основная функция скрипта."""
    logger.info("=" * 60)
    logger.info("Запуск скрипта сбора статистики по коду")
    logger.info("=" * 60)

    config = load_config()
    links = parse_links(INPUT_FILE)

    results = []
    processed = 0
    failed = 0

    for idx, link in enumerate(links, 1):
        logger.info(f"[{idx}/{len(links)}] Обработка: {link}")

        try:
            row = None

            if 'gitee.com' in link:
                row = process_gitee_or_gitcode(link, config, 'gitee')
            elif 'gitcode.net' in link or 'gitcode.com' in link:
                row = process_gitee_or_gitcode(link, config, 'gitcode')
            elif 'gitlab' in link:
                row = process_gitlab(link, config)
            elif 'cr-y.codehub' in link:
                row = process_codehub(link, config, 'cr-y.codehub')
            elif 'codehub-y' in link:
                row = process_codehub(link, config, 'codehub-y')
            elif 'open.codehub' in link:
                row = process_codehub(link, config, 'opencodehub')
            elif 'codehub' in link:
                row = process_codehub(link, config, 'codehub')
            elif 'gerrit' in link or 'mgit' in link:
                row = process_gerrit(link, config)
            else:
                logger.warning(f"Неизвестная платформа в URL: {link}")
                failed += 1
                continue

            if row:
                results.append(row)
                processed += 1
                logger.info(f"  ✓ Успешно обработано")
            else:
                failed += 1
                logger.error(f"  ✗ Не удалось получить данные")

        except Exception as e:
            failed += 1
            logger.error(f"  ✗ Ошибка при обработке: {e}", exc_info=True)

    logger.info("=" * 60)
    logger.info(f"Обработка завершена:")
    logger.info(f"  Успешно: {processed}")
    logger.info(f"  Ошибок: {failed}")
    logger.info("=" * 60)

    if results:
        export_to_excel(results)
    else:
        logger.warning("Нет данных для экспорта!")
        sys.exit(1)


if __name__ == '__main__':
    main()