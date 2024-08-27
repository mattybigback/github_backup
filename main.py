import os
import shutil
import time
import sys
from datetime import datetime
from requests.exceptions import ConnectionError
from github import Auth, Github, BadCredentialsException
from git import Repo, GitCommandError
from secret_files import gh_creds

BACKUP_TEMP_PATH = "./temp"
BACKUP_ZIP_PATH = "./backup_zips"

github_token = Auth.Token(gh_creds.github_token)
gh_url = f"https://{gh_creds.gh_username}:{gh_creds.github_token}@github.com/"

def get_repo_data():
    repo_list = []
    print("Connecting to Github API...", end="")
    gh = Github(auth=github_token)
    try:
        user_account = gh.get_user().login
    except BadCredentialsException:
        print("Invalid credentials. Aborting.")
        sys.exit()
    except ConnectionError:
        print("Connection error. Aborting.")
        sys.exit()
    print("Success!")
    print("Scanning repo data...")

    # Fetch all repositories at once (this might already be paginated by the library)
    repos = gh.get_user().get_repos()

    # Collect necessary data in one pass
    for repo in repos:
        try:
            branch = repo.default_branch
            commit_sha = repo.get_branch(branch).commit.sha[:7]  # Get the short SHA of the commit
            repo_data = {
                "name": repo.name,
                "user": repo.owner.login,
                "full_name": repo.full_name,
                "default_branch": branch,
                "head_commit": commit_sha
            }
            repo_list.append(repo_data)
            print(f"Repo found...{repo.name}")
        except BadCredentialsException:
            print("Invalid credentials. Aborting.")
            sys.exit()
        except ConnectionError:
            print("Connection error. Aborting.")
            sys.exit()
    if len(repo_list) == 0:
        print(f"No repos found for account {user_account}")
        sys.exit()

    return repo_list

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
    repo_list = get_repo_data()
    for repository in repo_list:
        repo_folder_name = f"{repository['name']}_{repository['head_commit']}"
        retries = 0
        max_retries = 10  # Maximum number of retries
        retry_delay = 10  # Delay between retries in seconds

        while retries < max_retries:
            print(f"Cloning repo {repository['full_name']}...", end="")
            try:
                Repo.clone_from(f"{gh_url}{repository['full_name']}", f"{BACKUP_TEMP_PATH}/{repository['user']}/{repo_folder_name}")
                print(f"Success! {repository['default_branch']} - {repository['head_commit']}")
                break  # Exit the retry loop on success
            except GitCommandError:
                print(f"Failed. Attempt {retries + 1} of {max_retries}.")
                retries += 1
                if retries < max_retries:
                    time.sleep(retry_delay)  # Wait a bit before retrying
                else:
                    print(f"Failed to clone repo {repository['name']} after {max_retries} attempts. Aborting.")
                    delete_folder_contents(BACKUP_TEMP_PATH)
                    sys.exit()

    print("Creating archive...", end="")
    try:
        shutil.make_archive(f"{BACKUP_ZIP_PATH}/MFT_Github_Backup_{folder_timestamp}", 'zip', BACKUP_TEMP_PATH)
    except:
        print("Failure. Could not create archive")
        sys.exit()
    print("Success!")
    delete_folder_contents(BACKUP_TEMP_PATH)
main()
