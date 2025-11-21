import os
import shutil
import time
import sys
from datetime import datetime
import requests
import jwt
from git import Repo, GitCommandError
from secret_files import gh_creds

BACKUP_TEMP_PATH = "./temp"
BACKUP_ZIP_PATH = "./backup_zips"
GITHUB_API_URL = "https://api.github.com"
GITHUBN_PK_FILE = "./secret_files/gh_pk.pem"

def get_github_app_private_key() -> str:
    """Read the GitHub App private key from a PEM file."""
    with open(GITHUBN_PK_FILE, "r") as pk_file:
        return pk_file.read()

def generate_app_jwt() -> str:
    """
    Generate a short-lived JWT for the GitHub App using RS256, as required by GitHub.
    """
    now = int(time.time())
    payload = {
        "iat": now - 60,               # issued at (a little in the past to allow for clock skew)
        "exp": now + (10 * 60),        # max 10 minutes for GitHub app JWTs
        "iss": gh_creds.GITHUB_APP_ID,          # GitHub App ID
    }

    encoded = jwt.encode(payload, get_github_app_private_key(), algorithm="RS256")
    # PyJWT may return bytes or str depending on version; normalize to str
    return encoded if isinstance(encoded, str) else encoded.decode("utf-8")

def get_installation_token() -> str:
    """
    Exchange the app JWT for an installation access token.

    This token is what we use to call the GitHub API AND to git-clone via HTTPS.
    """
    jwt_token = generate_app_jwt()

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    url = f"{GITHUB_API_URL}/app/installations/{gh_creds.GITHUB_INSTALLATION_ID}/access_tokens"
    try:
        resp = requests.post(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error getting installation token: {e}")
        sys.exit(1)

    data = resp.json()
    token = data["token"]
    expires_at = data["expires_at"]
    print(f"\nGot installation token (expires at {expires_at})")
    return token

def github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }



def get_repo_data():
    """
    Get list of repositories accessible to this app installation, including
    default branch and short head commit SHA.
    """
    print("Connecting to GitHub API...", end="", flush=True)

    token = get_installation_token()
    headers = github_headers(token)

    repo_list = []
    url = f"{GITHUB_API_URL}/installation/repositories?per_page=100"

    try:
        while url:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 401:
                print("\nInvalid GitHub App credentials. Aborting.")
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
                branch_resp = requests.get(branch_url, headers=headers, timeout=10)
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
                print(f"\nRepo found...{full_name}")

            # Pagination
            url = resp.links.get("next", {}).get("url")

    except requests.exceptions.RequestException as e:
        print(f"\nConnection error. Aborting. ({e})")
        sys.exit(1)

    if not repo_list:
        print("\nNo repos found for this app installation.")
        sys.exit(1)

    print("\nSuccess!")
    return repo_list, token

def build_clone_url(token: str, full_name: str) -> str:
    """
    Build an HTTPS URL suitable for cloning with a GitHub App installation token.
    """
    # Using x-access-token as the username is the recommended pattern for app tokens.
    # https://github.com/orgs/community/discussions/48186  (and related docs) :contentReference[oaicite:8]{index=8}
    return f"https://x-access-token:{token}@github.com/{full_name}"


def delete_folder_contents(folder_path):
    '''Delete all files from temp directory'''
    # Check if the folder exists and handle
    if not os.path.exists(folder_path):
        return

    # List all the entries in the folder
    for entry in os.listdir(folder_path):
        entry_path = os.path.join(folder_path, entry)
        # Check if path is a file or a directory and handle
        if os.path.isfile(entry_path):
            os.remove(entry_path)  # Delete the file
        elif os.path.isdir(entry_path):
            shutil.rmtree(entry_path)  # Delete the directory and all its contents

    print("Folder contents deleted.")

def main():
    folder_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    delete_folder_contents(BACKUP_TEMP_PATH)
    repo_list, token = get_repo_data()
    for repository in repo_list:
        repo_folder_name = f"{repository['name']}_{repository['head_commit']}"
        dest_path = f"{BACKUP_TEMP_PATH}/{repository['user']}/{repo_folder_name}"
        clone_url = build_clone_url(token, repository["full_name"])

        retries = 0
        max_retries = 10  # Maximum number of retries
        retry_delay = 10  # Delay between retries in seconds

        while retries < max_retries:
            print(f"Cloning repo {repository['full_name']}...", end="", flush=True)
            try:
                Repo.clone_from(clone_url, dest_path)
                print(f"Success! {repository['default_branch']} - {repository['head_commit']}")
                break  # Exit the retry loop on success
            except GitCommandError as e:
                retries += 1
                print(f" Failed. Attempt {retries} of {max_retries}. ({e})")

                if retries < max_retries:
                    time.sleep(retry_delay)  # Wait a bit before retrying
                else:
                    print(f"Failed to clone repo {repository['name']} after {max_retries} attempts. Aborting.")
                    delete_folder_contents(BACKUP_TEMP_PATH)
                    sys.exit()

    print("Creating archive...", end="", flush=True)
    try:
        shutil.make_archive(
            f"{BACKUP_ZIP_PATH}/MFT_Github_Backup_{folder_timestamp}",
            'zip',
            BACKUP_TEMP_PATH)
    except Exception as e:
        print(f"\nFailure. Could not create archive: {e}")
        sys.exit(1)
    print("Success!")
    delete_folder_contents(BACKUP_TEMP_PATH)

if __name__ == "__main__":
    main()
