#!/usr/bin/env python3.9

import argparse
import json
import re
import subprocess
import sys
import concurrent.futures
from pathlib import Path

import requests
from bs4 import BeautifulSoup


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
HEAD_REGEX = re.compile(r'ref: refs/heads/(.*)\n')
# not even newlines are allowed in github repo descs lol
MIRROR_DESCRIPTION_FORMAT = (
    '{original_desc} - '
    'Official repo link below. '
    "Please read this organisation's pinned readme for info."
)
THREADPOOL_WORKERS_DEFAULT = 10


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


def update_repo(project: str, owner: str = MIRROR_GITHUB_ORG):
    print(f'{project}: Updating settings.')
    subprocess.run(
        [
            GH,
            'api',
            f'repos/{owner}/{project}',
            '--silent',
            '-X', 'PATCH',
            '-F', 'has_issues=false',
            '-F', 'has_projects=false',
            '-F', 'has_wiki=false',
        ]
    )


def create_repo(
        project: str, project_desc: str, project_link: str,
        owner: str = MIRROR_GITHUB_ORG
):
    # todo: figure out why this prints 'error: remote origin already exists.'
    repo_description = MIRROR_DESCRIPTION_FORMAT.format(original_desc=project_desc)
    subprocess.run(
        [
            GH, 'repo', 'create',
            f'{owner}/{project}',
            '--homepage', project_link,
            '--description', repo_description,
            '--public', '-y',
        ]
    )


# memoization hack
# noinspection PyDefaultArgument
def clone_origin(
        project: str, origin_remote: str, workdir: Path,
        cvs_installed: list[bool] = [True]
) -> bool:
    clone_success = run_git_command(workdir, f'clone {origin_remote}')
    # todo: handle some cvs-only repos having empty git servers instead of nonexistent ones
    if clone_success.returncode == 128:
        if not cvs_installed[0]:
            print(f'{project}: git-cvs not installed, skipping.')
            return False
        print(f'{project}: Not hosted on git, cloning with cvsimport.')
        cvs_success = run_git_command(
            workdir, f'cvsimport -d {SAVANNAH_CVS_FORMAT.format(project)} {project} -C {project}'
        )
        if cvs_success.returncode == 1:
            print(f'{project}: git-cvs not installed, skipping.')
            cvs_installed[0] = False
            return False

    return True


def sync_project(
        project: str, project_desc: str,
        workdir: Path, mirror_exists: bool = False
):
    print(f'{project}: Mirroring project.')
    # for testing
    # input(f'Press enter to sync {project}:\n')

    work_tree = workdir / project
    origin_remote = SAVANNAH_GIT_FORMAT.format(project)
    mirror_remote = MIRROR_GIT_FORMAT.format(project)
    project_link = SAVANNAH_PROJECT_FORMAT.format(project)
    print('\n'.join([project_link, origin_remote, mirror_remote]))

    # clone repo if it doesn't exist
    if not work_tree.is_dir():
        print(f'{project}: Local copy does not exist, cloning.')
        clone_success = clone_origin(project, origin_remote, workdir)
        if not clone_success:
            return
    else:
        print(f'{project}: Local copy already exists.')

    # create mirror github repo if it doesn't exist
    if not mirror_exists:
        print(f'{project}: Mirror repo does not exist, creating.')
        create_repo(project, project_desc, project_link)
        # you might say I should just change these settings on repo creation.
        # but the repo create endpoint doesn't have some fields so whatever
        update_repo(project)
    else:
        print(f'{project}: Mirror repo already exists.')
        run_git_command(work_tree, 'pull')

    run_git_command(work_tree, f'push {mirror_remote} --all')

    return project


def sync_all_projects(workdir: Path, threadpool_workers: int):
    projects = get_all_projects()
    existing_repos = get_existing_repos()

    if threadpool_workers:
        if threadpool_workers == -1:
            threadpool_workers = None
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=threadpool_workers)
        results = executor.map(
            lambda p: sync_project(p, projects[p], workdir, mirror_exists=(p in existing_repos)),
            projects
        )
        try:
            for done_project in results:
                print(f'{done_project}: Done.')
        except KeyboardInterrupt:
            print('\nReceived KeyBoardInterRupt.\n')
        finally:
            print('Shutting down thread pool...')
            executor.shutdown(cancel_futures=True)
            print('Shut down thread pool.')
    else:
        for project_name, project_desc in projects.items():
            sync_project(project_name, project_desc, workdir, mirror_exists=(project_name in existing_repos))


class Args(argparse.Namespace):
    def __init__(self, **kwargs):
        self.threadpool_workers = THREADPOOL_WORKERS_DEFAULT
        super().__init__(**kwargs)


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '-w', '--threadpool-workers', type=int, default=THREADPOOL_WORKERS_DEFAULT,
        help='number of thread pool workers to use, -1 for system default, 0 for a loop instead of a thread pool'
    )
    return parser


def main():
    parser = get_parser()
    args = parser.parse_args(namespace=Args())

    workdir = Path().resolve().parent
    print(f'Running in {workdir}.')
    # input('Press enter:\n')
    sync_all_projects(workdir, args.threadpool_workers)


if __name__ == '__main__':
    main()
