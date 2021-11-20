#!/usr/bin/env python3.9

import json
import re
import subprocess
import concurrent.futures
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# todo: make config more dynamic - cfg file, cli args
GIT_POSIX = '/usr/bin/git'
GH_POSIX = '/usr/bin/gh'
GIT_WIN = r'C:\Program Files\Git\cmd\git.exe'
GH_WIN = r'C:\Program Files (x86)\GitHub CLI\gh.exe'
if sys.platform == 'win32':
    GIT = GIT_WIN
    GH = GH_WIN
else:
    GIT = GIT_POSIX
    GH = GH_POSIX
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
    '{original_desc} - '
    'Official repo link below. '
    "Please read this organisation's pinned readme for info."
)
PROCESS_POOL_MAX_WORKERS = 10
USE_PROCESS_POOL = True


# todo: fix errors pushing refs making some mirror repos empty


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


def run_git_command(directory: Path, command: str) -> subprocess.CompletedProcess:
    command_list = command.split()
    completed_process = subprocess.run(
        [GIT, '-C', str(directory), *command_list], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    print(completed_process.stdout.decode())
    return completed_process


# https://cli.github.com/manual/
def get_existing_repos(owner: str = MIRROR_GITHUB_ORG) -> list[str]:
    print('Fetching existing mirror repos.')
    gh_process = subprocess.run(
        [GH, 'repo', 'list', owner, '--json', 'name', '--limit', str(SAVANNAH_SEARCH_ROWS)],
        stdout=subprocess.PIPE
    )
    gh_result_json = json.loads(gh_process.stdout)
    repos = [r['name'] for r in gh_result_json]

    print(f'Fetched {len(repos)} existing mirror repos.')
    return repos


# noinspection PyDefaultArgument
def sync_project(
        project: str, project_desc: str,
        workdir: Path, mirror_exists: bool = False,
        cvs_installed: list[bool] = [True]
):
    print(f'Mirroring project {project}.')
    # for testing
    # input(f'Press enter to sync {project}:\n')

    work_tree = workdir / project
    origin_remote = SAVANNAH_GIT_FORMAT.format(project)
    mirror_remote = MIRROR_GIT_FORMAT.format(project)
    project_link = SAVANNAH_PROJECT_FORMAT.format(project)

    # clone repo if it doesn't exist
    if not work_tree.is_dir():
        print('Local copy does not exist, cloning.')
        clone_success = run_git_command(workdir, f'clone {origin_remote}')
        # todo: handle some cvs-only repos having empty git servers instead of nonexistent ones
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
        # todo: figure out why this prints 'error: remote origin already exists.'
        # todo: disable issues, prs, releases, packages
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

    if USE_PROCESS_POOL:
        with concurrent.futures.ThreadPoolExecutor(max_workers=PROCESS_POOL_MAX_WORKERS) as executor:
            try:
                executor.map(
                    lambda p: sync_project(p, projects[p], workdir, mirror_exists=(p in existing_repos)),
                    projects
                )
            except KeyboardInterrupt:
                print('Shutting down thread pool...')
                executor.shutdown(cancel_futures=True)
    else:
        for project_name, project_desc in projects.items():
            sync_project(project_name, project_desc, workdir, mirror_exists=(project_name in existing_repos))


def main():
    workdir = Path().resolve().parent
    print(f'Running in {workdir}.')
    # input('Press enter:\n')
    sync_all_projects(workdir)


if __name__ == '__main__':
    main()
