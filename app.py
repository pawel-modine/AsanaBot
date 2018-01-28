from functools import lru_cache
import json
import sys

import asana
import github

ASANA_CLIENT_ID = ''
ASANA_SECRET_ID = ''

def get_asana_client():
    token_file = 'asana-token'
    def save_token(token):
        with open(token_file, 'w') as fobj:
            fobj.write(json.dumps(token))

    try:
        with open(token_file, 'r') as fobj:
            token = json.load(fobj)
            return asana.Client.oauth(client_id=ASANA_CLIENT_ID, token=token)
    except IOError:
        asana_client = asana.Client.oauth(client_id=ASANA_CLIENT_ID, client_secret=ASANA_SECRET_ID,
                                        redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        url, state = asana_client.session.authorization_url()

        print(url)
        print("Copy and paste the returned code from the browser and press enter:")
        code = sys.stdin.readline().strip()
        token = asana_client.session.fetch_token(code=code)
        save_token(token)
        return asana.Client.oauth(client_id=ASANA_CLIENT_ID, token=token,
                                  auto_refresh_url='https://app.asana.com/-/oauth_token',
                                  auto_refresh_kwargs={'client_id': ASANA_CLIENT_ID, 'client_secret': ASANA_SECRET_ID},
                                  token_updater=save_token)


def get_issues(org, repo, assigned=False, milestoned=True):
    org = github_client.get_organization(org)
    repo = org.get_repo(repo)
    for issue in repo.get_issues():
        if assigned and not issue.assignee:
            continue
        if milestoned and not issue.milestone:
            continue
        if issue.state == 'open':
            yield issue
            break

def parse_payload(req):
    pass


@lru_cache()
def find_workspace(org: str):
    """Find the Asana workspace to go with a GitHub organization."""
    org = org.lower()
    for workspace in asana_client.workspaces.find_all():
        if workspace['name'].lower() == org:
            return workspace
    else:
        raise ValueError('Could not find workspace for: {}'.format(org))


@lru_cache()
def find_project(workspace: int, repo: str):
    """Find the project to go with the repository."""
    repo = repo.lower()
    for project in asana_client.projects.find_all({'workspace': workspace}):
        if project['name'].lower() == repo:
            return project
    else:
        raise ValueError('Could not find appropriate project for: {}'.format(repo))


def get_ids(org: str, repo: str):
    """Get the Asana ids to go with GitHub information."""
    workspace = find_workspace(org)
    project = find_project(workspace['id'], repo)
    return workspace['id'], project['id']


@lru_cache()
def find_github_tag(workspace: int):
    """Find the GitHub tag on Asana."""
    tag_name = 'GitHub'
    for tag in asana_client.tags.find_by_workspace(workspace):
        if tag['name'].lower() == tag_name.lower():
            break
    else:  # Did not find one
        tag = asana_client.tags.create_in_workspace(workspace, dict(name=tag_name))

    return tag['id']


@lru_cache()
def github_to_asana_user(user):
    pass


def sync_issue(issue):
    print(issue.title)

    # Find the Asana task that goes with this issue
    try:
        task = find_task(issue)
        asana_client.tasks.update(task, {})
    except ValueError:
        repo = issue.repository
        org = issue.repository.organization
        workspace, project = get_ids(org.name, repo.name)
        task = create_task(workspace, project, issue)


def find_task(issue):
    """Find task corresponding to the issue."""
    try:
        return asana_client.tasks.find_by_id('external:' + issue_to_id(issue))['id']
    except asana.error.NotFoundError as e:
        raise ValueError('No task found for issue.') from e


def issue_to_id(issue):
    """Create a unique id from an issue"""
    return '{0.repository.organization.name}-{0.repository.name}-{0.number:d}'.format(issue)


def create_task(workspace: int, project: int, issue):
    """Create a task corresponding to the """
    github_tag = find_github_tag(workspace)
    return asana_client.tasks.create_in_workspace(workspace,
                                                  {'external': {'id': issue_to_id(issue)},
                                                   'name': '{0.title} (#{0.number})'.format(issue),
                                                   'notes': '\n'.join((issue.body, issue.html_url)),
                                                   'projects': [project],
                                                   'tags': [github_tag]})


if __name__ == '__main__':
    asana_client = get_asana_client()
    github_client = github.Github('')

    # TODO: These need to be pulled from the github payload
    rate = github_client.get_rate_limit().rate
    print('API calls remaining: {0} (Resets at {1})'.format(rate.remaining, rate.reset))

    org = 'Unidata'
    repo = 'MetPy'

    for issue in get_issues(org, repo):
        sync_issue(issue)

    rate = github_client.get_rate_limit().rate
    print('API calls remaining: {0} (Resets at {1})'.format(rate.remaining, rate.reset))
