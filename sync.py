from functools import lru_cache
import json
import sys

import asana
import github

ASANA_CLIENT_ID = ''
ASANA_SECRET_ID = ''

def get_asana_client():
    """Handle the details of setting up OAUTH2 access to Asana."""
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


def get_issues(org, repo):
    """Get the relevant issues that need to be synced to Asana."""
    org = github_client.get_organization(org)
    repo = org.get_repo(repo)
    for ind, issue in enumerate(repo.get_issues(state='all')):
        yield issue
        if ind > 1:
            break


def parse_payload(request):
    """Parse GitHub webhook payload to get the updated issue."""
    raise NotImplementedError


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
def github_to_asana_user(workspace: int, github_user: str):
    """Figure out the Asana user that corresponds to a GitHub user."""
    for user in asana_client.users.find_by_workspace(workspace):
        if user['name'] == github_user:
            return user
    return 'null'


def sync_issue(issue):
    """Synchronize a GitHub issue to an Asana task.

    Either create a new task or update attributes of existing task.
    """
    repo = issue.repository
    org = repo.organization
    workspace = find_workspace(org.name)['id']

    sync_attrs = {}
    if issue.assignee:
        sync_attrs['assignee'] = github_to_asana_user(workspace, issue.assignee.name)
    else:
        sync_attrs['assignee'] = 'null'

    sync_attrs['completed'] = issue.state == 'closed'

    # Find the Asana task that goes with this issue
    try:
        task = find_task(issue)
        asana_client.tasks.update(task, sync_attrs)
    except ValueError:
        if issue.state == 'open' and issue.milestone is not None:
            project = find_project(workspace, repo.name)['id']
            task = create_task(workspace, project, issue, sync_attrs)


def find_task(issue):
    """Find task corresponding to the issue."""
    try:
        return asana_client.tasks.find_by_id('external:' + issue_to_id(issue))['id']
    except asana.error.NotFoundError as e:
        raise ValueError('No task found for issue.') from e


def issue_to_id(issue):
    """Create a unique id from an issue."""
    return '{0.repository.organization.name}-{0.repository.name}-{0.number:d}'.format(issue)


def create_task(workspace: int, project: int, issue, attrs: dict):
    """Create a task corresponding to a GitHub issue."""
    github_tag = find_github_tag(workspace)
    params = {'external': {'id': issue_to_id(issue)},
              'name': '{0.title} (#{0.number})'.format(issue),
              'notes': '\n\n'.join((issue.html_url, issue.body)),
              'projects': [project],
              'tags': [github_tag]}
    params.update(attrs)
    return asana_client.tasks.create_in_workspace(workspace, params)


if __name__ == '__main__':
    asana_client = get_asana_client()
    github_client = github.Github(GITHUB_TOKEN)

    rate = github_client.get_rate_limit().rate
    print('API calls remaining: {0} (Resets at {1})'.format(rate.remaining, rate.reset))

    org = 'Unidata'
    repo = 'MetPy'

    for issue in get_issues(org, repo):
        sync_issue(issue)