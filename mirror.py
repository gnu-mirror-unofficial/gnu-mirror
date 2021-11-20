#!/usr/bin/env python3.9

import json
import re
import subprocess
import concurrent.futures
from pathlib import Path
from typing import Union

import requests
from bs4 import BeautifulSoup


# GIT = '/usr/bin/git'
# GH = '/usr/bin/gh'
GIT = r'C:\Program Files\Git\cmd\git.exe'
GH = r'C:\Program Files (x86)\GitHub CLI\gh.exe'
SAVANNAH_SEARCH_FORMAT = 'https://savannah.gnu.org/search/?type_of_search=soft&words=*&type=1&max_rows={rows}'
SAVANNAH_SEARCH_ROWS = 1000
SAVANNAH_PROJECT_FORMAT = 'https://savannah.gnu.org/projects/{}'
SAVANNAH_GIT_FORMAT = 'https://git.savannah.gnu.org/git/{}.git'
MIRROR_GITHUB_ORG = 'gnu-mirror-unofficial'
MIRROR_GIT_FORMAT = f'https://github.com/{MIRROR_GITHUB_ORG}/{{}}'
GNU_PROJECT_REGEX = re.compile(r'\.\./projects/(.*)')
# not even newlines are allowed in github repo descs lol
MIRROR_DESCRIPTION_FORMAT = """\
Official repo link below. \
Please read this organisation's pinned readme for info.\
"""


def get_all_projects() -> list[str]:
    print('Fetching project list.')
    search_url = SAVANNAH_SEARCH_FORMAT.format(rows=SAVANNAH_SEARCH_ROWS)
    response = requests.get(search_url)
    soup = BeautifulSoup(response.content, 'html.parser')

    search_table = soup.find('table', class_='box')
    table_rows = search_table.find_all('tr', class_='boxitem') + search_table.find_all('tr', class_='boxitemalt')

    project_links = [row.find('a')['href'] for row in table_rows]
    project_names = [re.match(GNU_PROJECT_REGEX, link)[1] for link in project_links]
    print(f'Fetched {len(project_names)} projects.')

    return project_names


def run_git_command(directory: Path, command: Union[str, list]):
    if isinstance(command, str):
        command = command.split()
    print(command)
    subprocess.run([GIT, '-C', str(directory), *command])


# https://cli.github.com/manual/
def get_existing_repos(owner: str = MIRROR_GITHUB_ORG) -> list[str]:
    gh_process = subprocess.run([GH, 'repo', 'list', owner, '--json', 'name'], stdout=subprocess.PIPE)
    gh_result_json = json.loads(gh_process.stdout)
    repos = [r['name'] for r in gh_result_json]
    return repos


def sync_project(project: str, workdir: Path, mirror_exists: bool = False):
    print(f'Mirroring project {project}.')
    # todo: remove once done testing
    input(f'Press enter to sync {project}:\n')

    work_tree = workdir / project
    origin_remote = SAVANNAH_GIT_FORMAT.format(project)
    mirror_remote = MIRROR_GIT_FORMAT.format(project)
    project_link = SAVANNAH_PROJECT_FORMAT.format(project)

    if not work_tree.is_dir():
        print('Local copy does not exist, cloning.')
        run_git_command(workdir, f'clone {origin_remote}')
    else:
        print('Local copy already exists.')
    if not mirror_exists:
        print('Mirror repo does not exist, creating.')
        repo_description = MIRROR_DESCRIPTION_FORMAT
        subprocess.run(
            [
                GH, 'repo', 'create',
                f'{MIRROR_GITHUB_ORG}/{project}',
                '--homepage', project_link,
                '--description', repo_description,
                '--public', '-y',
            ]
        )
    else:
        print('Mirror repo already exists.')

    run_git_command(work_tree, 'pull')
    run_git_command(work_tree, ['push', mirror_remote])


def sync_all_projects(projects: list[str], workdir: Path):
    existing_repos = get_existing_repos()

    # with concurrent.futures.ProcessPoolExecutor() as executor:
    #     executor.map(lambda p: sync_project(p, workdir, mirror_exists=(p in existing_repos)), projects)
    for p in projects:
        sync_project(p, workdir, mirror_exists=(p in existing_repos))


def main():
    workdir = Path().resolve().parent
    input(f'Running in {workdir}. Press enter:\n')
    sync_all_projects(get_all_projects(), workdir)


if __name__ == '__main__':
    main()
