#!/usr/bin/env python3.9

import re
import subprocess
import concurrent.futures
from pathlib import Path

import requests
from bs4 import BeautifulSoup


GIT = '/usr/bin/git'
GH = '/usr/bin/gh'
SAVANNAH_SEARCH_FORMAT = 'https://savannah.gnu.org/search/?type_of_search=soft&words=*&type=1&max_rows={rows}'
SAVANNAH_SEARCH_ROWS = 1000
SAVANNAH_PROJECT_FORMAT = 'https://savannah.gnu.org/projects/{}'
SAVANNAH_GIT_FORMAT = 'https://git.savannah.gnu.org/git/{}.git'
MIRROR_GITHUB_ORG = 'git-mirror-unofficial'
MIRROR_GIT_FORMAT = f'https://github.com/{MIRROR_GITHUB_ORG}/{{}}'
REPO_LIST_REGEX = re.compile(fr'{MIRROR_GITHUB_ORG}/(.*)\s')
GNU_PROJECT_REGEX = re.compile(r'\.\./projects/(.*)')
MIRROR_DESCRIPTION_FORMAT = f"""\
{SAVANNAH_PROJECT_FORMAT}
Please read {MIRROR_GIT_FORMAT.format('gnu-mirror#readme')}
"""


def get_all_projects() -> list[str]:
    search_url = SAVANNAH_SEARCH_FORMAT.format(rows=SAVANNAH_SEARCH_ROWS)
    response = requests.get(search_url)
    soup = BeautifulSoup(response.content, 'html.parser')

    search_table = soup.find('table', class_='box')
    table_rows = search_table.find_all('tr', class_='boxitem') + search_table.find_all('tr', class_='boxitemalt')

    project_links = [row.find('a')['href'] for row in table_rows]
    project_names = [re.match(GNU_PROJECT_REGEX, link)[1] for link in project_links]

    return project_names


def run_git_command(directory: Path, command: str):
    command_list = command.split()
    subprocess.run([GIT, '-C', str(directory), *command_list])


# https://cli.github.com/manual/
def get_existing_repos(owner: str = MIRROR_GITHUB_ORG) -> list[str]:
    gh_process = subprocess.run([GH, 'repo', 'list', owner], stdout=subprocess.PIPE)
    gh_result = gh_process.stdout.decode()
    matches = re.findall(REPO_LIST_REGEX, gh_result)
    repos = [m[1] for m in matches]
    return repos


def sync_project(project: str, workdir: Path, mirror_exists: bool = False):
    work_tree = workdir / project
    origin_remote = SAVANNAH_GIT_FORMAT.format(project)
    mirror_remote = MIRROR_GIT_FORMAT.format(project)
    project_link = SAVANNAH_PROJECT_FORMAT.format(project)

    if not work_tree.is_dir():
        run_git_command(workdir, f'clone {origin_remote}')
    if not mirror_exists:
        repo_description = MIRROR_DESCRIPTION_FORMAT.format(project)
        subprocess.run(
            [
                GH, 'repo', 'create',
                f'{MIRROR_GITHUB_ORG}/{project}',
                '--homepage', project_link,
                '--description', repo_description,
                '--public', '-y',
            ]
        )

    run_git_command(work_tree, 'pull')
    run_git_command(work_tree, f'push {mirror_remote}')


def sync_all_projects(projects: list[str], workdir: Path):
    with concurrent.futures.ProcessPoolExecutor() as executor:
        executor.map(lambda p: sync_project(p, workdir), projects)


def main():
    sync_all_projects(get_all_projects(), Path().resolve())


if __name__ == '__main__':
    main()
