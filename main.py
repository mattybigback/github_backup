import os
import shutil
import sys
import time
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import structlog
import requests
import jwt
from git import Repo, GitCommandError
from envconfig import read_secret, ConfigError


os.makedirs("./logs", exist_ok=True)
log_handler_json = TimedRotatingFileHandler(
    "./logs/github_backup.log",
    when="midnight",
    interval=1,
    utc=True)
log_handler_console = logging.StreamHandler(sys.stderr)

log_handler_console.setFormatter(
    structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=False)
    )
)

log_handler_json.setFormatter(
    structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
    )
)

root = logging.getLogger()
root.setLevel(logging.INFO)
root.addHandler(log_handler_json)
root.addHandler(log_handler_console)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.EventRenamer("msg"),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
)
logger = structlog.getLogger(__name__)

BACKUP_TEMP_PATH = "./temp"
BACKUP_ZIP_PATH = "./backup_zips"
GITHUB_API_URL = "https://api.github.com"

try:
    GITHUB_APP_ID = read_secret("GITHUB_APP_ID", required=True)
    GITHUB_INSTALLATION_ID = read_secret(
        "GITHUB_INSTALLATION_ID", required=True)
    GITHUB_PK = read_secret("GITHUB_PK", required=True)
    GH_ARCHIVE_ZIP_PATH = read_secret(
        "GH_ARCHIVE_ZIP_PATH", default="./backup_zips")
    GH_ARCHIVE_ZIP_PREFIX = read_secret(
        "GH_ARCHIVE_ZIP_PREFIX", default="Github_Backup_")
    NO_COLOR = read_secret("NO_COLOR", default=None)
except ConfigError as e:
    logger.error(f"Configuration error: {e}")
    sys.exit(1)

ansi_color = False if NO_COLOR is not None else True

log_handler_console.setFormatter(
    structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=ansi_color)
    )
)

def generate_app_jwt() -> str:
    """
    Generate a short-lived JWT for the GitHub App using RS256, as required by GitHub.
    """
    now = int(time.time())
    payload = {
        # issued at (a little in the past to allow for clock skew)
        "iat": now - 60,
        "exp": now + (10 * 60),        # max 10 minutes for GitHub app JWTs
        "iss": GITHUB_APP_ID,          # GitHub App ID
    }

    try:
        encoded = jwt.encode(payload, GITHUB_PK, algorithm="RS256")
    except jwt.exceptions.InvalidKeyError as e:
        logger.error(f"Error generating JWT: {e}")
        return None
    except ValueError as e:
        logger.error(f"Error generating JWT: {e}")
        return None
    except AttributeError as e:
        logger.error(f"Unexpected error generating JWT: {e}")
        return None
    # PyJWT may return bytes or str depending on version; normalize to str
    return encoded if isinstance(encoded, str) else encoded.decode("utf-8")


def get_installation_token() -> str:
    """
    Exchange the app JWT for an installation access token.

    This token is what we use to call the GitHub API AND to git-clone via HTTPS.
    """

    jwt_token = generate_app_jwt()
    if jwt_token is None:
        return None

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    url = f"{GITHUB_API_URL}/app/installations/{GITHUB_INSTALLATION_ID}/access_tokens"
    try:
        resp = requests.post(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting installation token: {e}")
        sys.exit(1)

    data = resp.json()
    token = data["token"]
    expires_at = data["expires_at"]
    logger.info(f"Got installation token (expires at {expires_at})")
    return token


def github_headers(token: str) -> dict:
    """
    Creates a correctly formatted header for the github API
    """
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_repo_data(token: str) -> list[dict]:
    """
    Get list of repositories accessible to this app installation, including
    default branch and short head commit SHA.
    """
    logger.info("Attempting to connect to GitHub API")

    headers = github_headers(token)

    repo_list = []
    url = f"{GITHUB_API_URL}/installation/repositories?per_page=100"

    try:
        while url:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 401:
                logger.error("\nInvalid GitHub App credentials. Aborting.")
                sys.exit(1)
            resp.raise_for_status()

            data = resp.json()
            repos = data.get("repositories", [])
            for repo in repos:
                owner = repo["owner"]["login"]
                name = repo["name"]
                full_name = repo["full_name"]
                default_branch = repo["default_branch"]

                # Get latest commit on default branch
                branch_url = f"{GITHUB_API_URL}/repos/{owner}/{name}/branches/{default_branch}"
                branch_resp = requests.get(
                    branch_url, headers=headers, timeout=10)
                branch_resp.raise_for_status()
                branch_data = branch_resp.json()
                commit_sha = branch_data["commit"]["sha"][:7]

                repo_data = {
                    "name": name,
                    "user": owner,
                    "full_name": full_name,
                    "default_branch": default_branch,
                    "head_commit": commit_sha,
                }
                repo_list.append(repo_data)
                logger.info(
                    f"Found repository: {full_name} ({default_branch} - {commit_sha})")

            # Pagination
            url = resp.links.get("next", {}).get("url")

    except requests.exceptions.RequestException as e:
        logger.error(f"Connection error. Aborting. ({e})")
        sys.exit(1)

    if not repo_list:
        logger.warning("\nNo repos found for this app installation.")
        sys.exit(1)

    logger.info(f"Total repositories to back up: {len(repo_list)}")
    return repo_list


def build_clone_url(token: str, full_name: str) -> str:
    """
    Build an HTTPS URL suitable for cloning with a GitHub App installation token.
    """
    # Using x-access-token as the username is the recommended pattern for app tokens.

    return f"https://x-access-token:{token}@github.com/{full_name}"


def delete_folder_contents(folder_path):
    '''Delete all files from temp directory'''
    # Check if the folder exists and handle
    if not os.path.exists(folder_path):
        logger.info(
            f"Folder {folder_path} does not exist. No contents to delete.")

    # List all the entries in the folder
    for entry in os.listdir(folder_path):
        entry_path = os.path.join(folder_path, entry)
        try:
            # Check if path is a file or a directory and handle
            if os.path.isfile(entry_path):
                os.remove(entry_path)  # Delete the file
                logger.info(f"Deleted file {entry_path}")
            elif os.path.isdir(entry_path):
                # Delete the directory and all its contents
                shutil.rmtree(entry_path)
                logger.info(f"Deleted directory {entry_path}")
        except PermissionError as e:
            logger.warning(f"Could not delete locked path {entry_path}: {e}")
        except OSError as e:
            logger.warning(f"Could not delete path {entry_path}: {e}")


def main():
    """
    Get a list of github repos, clone them into a temporary location and then create a zip file.
    """
    logger.info("Starting GitHub backup process.")
    folder_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    delete_folder_contents(BACKUP_TEMP_PATH)
    token = get_installation_token()
    if token is None:
        sys.exit(1)
    repo_list = get_repo_data(token)
    for repository in repo_list:
        repo_folder_name = f"{repository['name']}_{repository['head_commit']}"
        dest_path = f"{BACKUP_TEMP_PATH}/{repository['user']}/{repo_folder_name}"
        clone_url = build_clone_url(token, repository["full_name"])

        retries = 0
        max_retries = 10  # Maximum number of retries
        retry_delay = 10  # Delay between retries in seconds

        while retries < max_retries:
            logger.info(f"Cloning repo {repository['name']} to {dest_path}")
            try:
                Repo.clone_from(clone_url, dest_path)
                logger.info(f"Successfully cloned {repository['name']}")
                break  # Exit the retry loop on success
            except GitCommandError as e:
                retries += 1
                logger.warning(
                    f"Failed to clone repo {repository['name']}. Attempt {retries} of {max_retries}. ({e})")

                if retries < max_retries:
                    time.sleep(retry_delay)  # Wait a bit before retrying
                else:
                    logger.error(
                        f"Failed to clone repo {repository['name']} after {max_retries} attempts. Aborting.")
                    delete_folder_contents(BACKUP_TEMP_PATH)
                    sys.exit()

    logger.info(f"Creating archive at {BACKUP_ZIP_PATH}")
    try:
        shutil.make_archive(
            f"{BACKUP_ZIP_PATH}/{GH_ARCHIVE_ZIP_PREFIX}{folder_timestamp}",
            'zip',
            BACKUP_TEMP_PATH)
    except Exception as e:
        logger.error(f"\nFailure. Could not create archive: {e}")
        sys.exit(1)
    logger.info(
        f"Backup archive created at {BACKUP_ZIP_PATH}/{GH_ARCHIVE_ZIP_PREFIX}{folder_timestamp}.zip")
    delete_folder_contents(BACKUP_TEMP_PATH)
    logger.info("GitHub backup process completed successfully.")


if __name__ == "__main__":
    main()
