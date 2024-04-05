from github import Auth, Github, BadCredentialsException
from git import Repo, GitCommandError
from secret_files import gh_creds
from datetime import datetime
import os
import shutil
import time

backup_temp_path = "./temp/"
backup_zip_path = "./backup_zips/"

github_token = Auth.Token(gh_creds.github_token)
gh_url = f"https://{gh_creds.gh_username}:{gh_creds.github_token}@github.com/"

def get_repo_data():
    repo_list = []
    gh = Github(auth=github_token)
    for repo in gh.get_user().get_repos():
        repo_data = {
            "name": repo.name,
            "user": repo.owner.login,
            "full_name": repo.full_name,
            "default_branch": repo.default_branch,
            "head_commit": str(gh.get_repo(repo.full_name).get_branch(repo.default_branch).commit)[12:19]
        }
        repo_list.append(repo_data)
    return repo_list

def delete_folder_contents(folder_path):
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
    delete_folder_contents(backup_temp_path)
    try:
        repo_list = get_repo_data()
    except BadCredentialsException:
        print("Invalid credentials. Aborting.")
        quit()

    for repository in repo_list:
        repo_folder_name = f"{repository['name']}_{repository['head_commit']}"
        retries = 0
        max_retries = 10  # Maximum number of retries
        retry_delay = 10  # Delay between retries in seconds
        
        while retries < max_retries:
            try:
                Repo.clone_from(f"{gh_url}{repository['full_name']}", f"{backup_temp_path}{repository['user']}/{repo_folder_name}")
                print(f"Successfully cloned {repository['name']} - {repository['default_branch']} - {repository['head_commit']}")
                break  # Exit the retry loop on success
            except GitCommandError as e:
                print(f"Error cloning repository {repository['name']}. Attempt {retries + 1} of {max_retries}.")
                retries += 1
                if retries < max_retries:
                    time.sleep(retry_delay)  # Wait a bit before retrying
                else:
                    print(f"Failed to clone repo {repository['name']} after {max_retries} attempts. Aborting.")
                    delete_folder_contents(backup_temp_path)
                    quit()
    
    shutil.make_archive(f"{backup_zip_path}MFT_Github_Backup_{folder_timestamp}", 'zip', backup_temp_path)
    delete_folder_contents(backup_temp_path)

main()