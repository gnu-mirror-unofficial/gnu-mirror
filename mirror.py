#!/usr/bin/env python3.9

import json
import re
import subprocess
# import concurrent.futures
from pathlib import Path

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
SAVANNAH_CVS_FORMAT = ':pserver:anonymous@cvs.savannah.gnu.org:/web/{}'
MIRROR_GITHUB_ORG = 'gnu-mirror-unofficial'
MIRROR_GIT_FORMAT = f'https://github.com/{MIRROR_GITHUB_ORG}/{{}}'
GNU_PROJECT_REGEX = re.compile(r'\.\./projects/(.*)')
# not even newlines are allowed in github repo descs lol
MIRROR_DESCRIPTION_FORMAT = (
    '{original_desc} '
    'Official repo link below. '
    "Please read this organisation's pinned readme for info."
)


def get_all_projects() -> dict[str, str]:
    print('Fetching project list.')
    search_url = SAVANNAH_SEARCH_FORMAT.format(rows=SAVANNAH_SEARCH_ROWS)
    response = requests.get(search_url)
    soup = BeautifulSoup(response.content, 'html.parser')

    search_table = soup.find('table', class_='box')
    table_rows = search_table.find_all('tr', class_='boxitem') + search_table.find_all('tr', class_='boxitemalt')

    project_links = [row.find('a') for row in table_rows]
    projects = {
            re.match(GNU_PROJECT_REGEX, link['href'])[1]: link.string for link in project_links
    }
    print(f'Fetched {len(projects)} projects.')

    return projects


def run_git_command(directory: Path, command: str):
    command_list = command.split()
    return subprocess.run([GIT, '-C', str(directory), *command_list])


# https://cli.github.com/manual/
def get_existing_repos(owner: str = MIRROR_GITHUB_ORG) -> list[str]:
    gh_process = subprocess.run([GH, 'repo', 'list', owner, '--json', 'name'], stdout=subprocess.PIPE)
    gh_result_json = json.loads(gh_process.stdout)
    repos = [r['name'] for r in gh_result_json]
    return repos


# noinspection PyDefaultArgument
def sync_project(
        project: str, project_desc: str,
        workdir: Path, mirror_exists: bool = False,
        cvs_installed: list[bool] = [True]
):
    print(f'Mirroring project {project}.')
    # todo: remove once done testing
    input(f'Press enter to sync {project}:\n')

    work_tree = workdir / project
    origin_remote = SAVANNAH_GIT_FORMAT.format(project)
    mirror_remote = MIRROR_GIT_FORMAT.format(project)
    project_link = SAVANNAH_PROJECT_FORMAT.format(project)

    # clone repo if it doesn't exist
    if not work_tree.is_dir():
        print('Local copy does not exist, cloning.')
        clone_success = run_git_command(workdir, f'clone {origin_remote}')
        if clone_success.returncode == 128:
            if not cvs_installed[0]:
                print('git-cvs not installed, skipping.')
                return
            print(f'Project {project} not hosted on git, cloning with cvsimport.')
            cvs_success = run_git_command(
                workdir, f'cvsimport -d {SAVANNAH_CVS_FORMAT.format(project)} {project}'
            )
            if cvs_success.returncode == 1:
                print('git-cvs not installed, skipping.')
                cvs_installed[0] = False
                return
    else:
        print('Local copy already exists.')

    # create mirror github repo if it doesn't exist
    if not mirror_exists:
        print('Mirror repo does not exist, creating.')
        repo_description = MIRROR_DESCRIPTION_FORMAT.format(original_desc=project_desc)
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
    run_git_command(work_tree, f'push {mirror_remote}')


def sync_all_projects(workdir: Path):
    projects = get_all_projects()
    existing_repos = get_existing_repos()

    # with concurrent.futures.ProcessPoolExecutor() as executor:
    #     executor.map(lambda p: sync_project(p, workdir, mirror_exists=(p in existing_repos)), projects)
    for project_name, project_desc in projects.items():
        sync_project(project_name, project_desc, workdir, mirror_exists=(project_name in existing_repos))


def main():
    workdir = Path().resolve().parent
    input(f'Running in {workdir}. Press enter:\n')
    sync_all_projects(workdir)


if __name__ == '__main__':
    main()
