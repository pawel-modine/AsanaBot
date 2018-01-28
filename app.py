import asana

asana_client = asana.Client.access_token('')

def get_issues(org, repo, assigned=True, milestoned=True):
    return []

def parse_payload(req):
    pass

def find_workspace(org: str):
    """Find the Asana workspace to go with a GitHub organization."""
    org = org.lower()
    for workspace in asana_client.workspaces.find_all():
        if workspace['name'].lower() == org:
            return workspace
    else:
        raise ValueError('Could not find workspace for: {}'.format(org))


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


def create_task(workspace: int, project: int, issue: dict):
    """Create a task corresponding to the """
    # TODO: Pull apart issue
    result = asana_client.tasks.create_in_workspace(workspace,
                                            {'name': 'Replace NCL',
                                            'notes': 'Note: This is a test task created with the python-asana client.',
                                            'projects': [project]})


if __name__ == '__main__':
    # TODO: These need to be pulled from the github payload
    org = 'Unidata'
    repo = 'MetPy'

    workspace, project = get_ids(org, repo)
    for issue in get_issues(org, repo):
        create_task(workspace, project, issue)
