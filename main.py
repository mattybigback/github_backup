from github import Auth, Github
from git import Repo
from secret_files import gh_creds

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

def main():
    repo_list = get_repo_data()
    for repository in repo_list:
        Repo.clone_from(f"{gh_url}{repository['full_name']}", f"./backup/{repository['user']}/{repository['name']}_{repository['head_commit']}")
        print(f"{repository['name']} - {repository['default_branch']} - {repository['head_commit']}")
main()