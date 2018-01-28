from functools import lru_cache
import json
import os
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
            return asana.Client.oauth(client_id=ASANA_CLIENT_ID, token=token,
                                      auto_refresh_url='https://app.asana.com/-/oauth_token',
                                      auto_refresh_kwargs={'client_id': ASANA_CLIENT_ID, 'client_secret': ASANA_SECRET_ID},
                                      token_updater=save_token)
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


class AsanaSync:
    def __init__(self, client):
        self._client = client

    @lru_cache()
    def find_workspace(self, org: str):
        """Find the Asana workspace to go with a GitHub organization."""
        org = org.lower()
        for workspace in self._client.workspaces.find_all():
            if workspace['name'].lower() == org:
                return workspace
        else:
            raise ValueError('Could not find workspace for: {}'.format(org))

    @lru_cache()
    def find_project(self, workspace: int, repo: str):
        """Find the project to go with the repository."""
        repo = repo.lower()
        for project in self._client.projects.find_all({'workspace': workspace}):
            if project['name'].lower().replace(' ', '-') == repo:
                return project
        raise ValueError('Could not find appropriate project for: {}'.format(repo))

    @lru_cache()
    def find_github_tag(self, workspace: int):
        """Find the GitHub tag on Asana."""
        tag_name = 'GitHub'
        for tag in self._client.tags.find_by_workspace(workspace):
            if tag['name'].lower() == tag_name.lower():
                break
        else:  # Did not find one
            tag = self._client.tags.create_in_workspace(workspace, dict(name=tag_name))

        return tag['id']

    @lru_cache()
    def github_to_asana_user(self, workspace: int, github_user: str):
        """Figure out the Asana user that corresponds to a GitHub user."""
        for user in self._client.users.find_by_workspace(workspace):
            if user['name'] == github_user:
                return user
        return 'null'

    def sync_issue(self, issue):
        """Synchronize a GitHub issue to an Asana task.

        Either create a new task or update attributes of existing task.
        """
        repo = issue.repository
        org = repo.organization
        workspace = self.find_workspace(org.name)['id']

        sync_attrs = {}
        if issue.assignee:
            sync_attrs['assignee'] = self.github_to_asana_user(workspace, issue.assignee.name)
        else:
            sync_attrs['assignee'] = 'null'

        sync_attrs['completed'] = issue.state == 'closed'

        # Find the Asana task that goes with this issue
        try:
            task_id = self.find_task(issue)
            task = self._client.tasks.update(task_id, sync_attrs)
        except ValueError:
            if should_make_new_task(issue):
                project = self.find_project(workspace, repo.name)['id']
                task = self.create_task(workspace, project, issue, sync_attrs)
            else:
                task = {}

        return task

    def find_task(self, issue):
        """Find task corresponding to the issue."""
        try:
            return self._client.tasks.find_by_id('external:' + issue_to_id(issue))['id']
        except asana.error.NotFoundError as e:
            raise ValueError('No task found for issue.') from e

    def create_task(self, workspace: int, project: int, issue, attrs: dict):
        """Create a task corresponding to a GitHub issue."""
        github_tag = self.find_github_tag(workspace)
        params = {'external': {'id': issue_to_id(issue)},
                  'name': '{0.title} (#{0.number})'.format(issue),
                  'notes': '\n\n'.join((issue.html_url, issue.body)),
                  'projects': [project],
                  'tags': [github_tag]}
        params.update(attrs)
        return self._client.tasks.create_in_workspace(workspace, params)


def should_make_new_task(issue):
    """Decide whether a new Task is justified at this time."""
    # We don't make *new* tasks for closed issues
    if issue.state != 'open':
        return False

    # Always want to have a new task for an open PR
    if issue.pull_request is not None:
        return True

    # If this issue lacks a milestone, but there are milestones for the
    # repository, don't make a new issue
    if issue.milestone is None and any(issue.repository.get_milestones()):
        return False

    return True


def issue_to_id(issue):
    """Create a unique id from an issue."""
    return '{0.repository.organization.name}-{0.repository.name}-{0.number:d}'.format(issue)

if __name__ == '__main__':
    syncer = AsanaSync(get_asana_client())
    github_client = github.Github(os.environ.get('GITHUB_TOKEN'))

    rate = github_client.get_rate_limit().rate
    print('API calls remaining: {0} (Resets at {1})'.format(rate.remaining, rate.reset))

    org = 'Unidata'
    repo = 'MetPy'

    for issue in get_issues(org, repo):
        syncer.sync_issue(issue)
