import asana

client = asana.Client.access_token('')

org = 'Unidata'
repo = 'metpy'

for workspace in client.workspaces.find_all():
    if workspace['name'].lower == org.lower():
        break
else:
    raise RuntimeError('Could not find workspace for: {}'.format(org))


for project in client.projects.find_all({'workspace': workspace['id']}):
    if project['name'].lower() == repo.lower():
        break
else:
    raise RuntimeError('Could not find appropriate project for: {}'.format(repo))

result = client.tasks.create_in_workspace(workspace['id'],
                                            {'name': 'Learn to use Nunchucks',
                                            'notes': 'Note: This is a test task created with the python-asana client.',
                                            'projects': [project['id']]})
