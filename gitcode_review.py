import requests
import json

# Constants
BASE_URL = "https://api.gitcode.com/api/v5"   # api https://docs.gitcode.com/docs/openapi/
ACCESS_TOKEN = "your_access_token_here"  # Replace with your personal access token
REPO_OWNER = "owner"  # Replace with the owner of the repository
REPO_NAME = "repository"  # Replace with the repository name


def fetch_pull_requests(owner, repo):
    """
    Fetch pull requests for a given repository.
    """
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Accept": "application/json"
    }

    params = {
        "state": "all",  # Fetch both open and closed pull requests
        "per_page": 100  # Fetch up to 100 pull requests at a time
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: Unable to fetch pull requests (Status Code: {response.status_code})")
        return []


def get_pull_request_stats(pull_requests):
    """
    Extract statistics for pull requests.
    """
    stats = []
    for pr in pull_requests:
        pr_data = {
            "author": pr.get("user", {}).get("username", "N/A"),
            "size": pr.get("changes", {}).get("total", 0),
            "link": pr.get("html_url"),
            "headline": pr.get("title")
        }
        stats.append(pr_data)
    return stats


def print_pull_request_stats(stats):
    """
    Print the pull request statistics in a readable format.
    """
    print(f"{'Author':<20} {'Size':<10} {'Link':<50} {'Headline'}")
    print("=" * 100)
    for stat in stats:
        print(f"{stat['author']:<20} {stat['size']:<10} {stat['link']:<50} {stat['headline']}")


if __name__ == "__main__":
    # Fetch pull requests from the specified repository
    pull_requests = fetch_pull_requests(REPO_OWNER, REPO_NAME)

    # Extract and print statistics
    if pull_requests:
        pr_stats = get_pull_request_stats(pull_requests)
        print_pull_request_stats(pr_stats)
