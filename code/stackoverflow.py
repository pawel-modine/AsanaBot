import json
import logging
import xml.etree.ElementTree as ET

import asana
import boto3
import urllib.request

from sync import get_asana_client

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

xmlns = {'atom': 'http://www.w3.org/2005/Atom'}
s3 = boto3.resource('s3')

def get_config():
    config_obj = s3.Object('unidata-python', 'asanabot/stackoverflow_config.json')
    return json.loads(config_obj.get()['Body'].read())

def update_config(config):
    config_obj = s3.Object('unidata-python', 'asanabot/stackoverflow_config.json')
    config_obj.put(Body=json.dumps(config))

def check_stack_overflow(event, context):
    asana = AsanaSubmit(get_asana_client())
    config = get_config()

    for item in config:
        xml = urllib.request.urlopen('https://stackoverflow.com/feeds/tag?tagnames={}&sort=newest'.format(item['tag']))
        content = xml.read()
        root = ET.fromstring(content)
        last_update = item['updated']
        for question in root.iterfind('atom:entry', xmlns):
            update_time = question.find('atom:updated', xmlns).text
            if update_time > last_update:
                logger.debug('Adding task for question:',
                             question.find('atom:title', xmlns).text)
                asana.submit(question, item)

        item['updated'] = root.find('atom:updated', xmlns).text

    update_config(config)


class AsanaSubmit:
    def __init__(self, client):
        self._client = client

    def find_unidata(self):
        """Find the Unidata Asana workspace."""
        for workspace in self._client.workspaces.find_all():
            if workspace['name'] == 'Unidata':
                return workspace
        else:
            raise ValueError('Could not find workspace for Unidata.')

    def find_project(self, workspace: int, name: str):
        """Find a project by name."""
        for project in self._client.projects.find_all({'workspace': workspace}):
            if project['name'] == name:
                return project
        raise ValueError('Could not find appropriate project for: {}'.format(name))

    def find_stackoverflow_tag(self, workspace: int):
        """Find the StackOverflow tag on Asana."""
        tag_name = 'StackOverflow'
        for tag in self._client.tags.find_by_workspace(workspace):
            if tag['name'].lower() == tag_name.lower():
                break
        else:  # Did not find one
            tag = self._client.tags.create_in_workspace(workspace, dict(name=tag_name))

        return tag['id']

    def find_asana_user(self, workspace: int, name: str):
        """Find an asana user by name."""
        for user in self._client.users.find_by_workspace(workspace):
            if user['name'] == name:
                return user
        return 'null'

    def submit(self, question, config):
        """Synchronize a GitHub issue to an Asana task.

        Either create a new task or update attributes of existing task.
        """
        workspace = self.find_unidata()['id']
        project = self.find_project(workspace, config['project'])['id']

        sync_attrs = {}
        sync_attrs['assignee'] = self.find_asana_user(workspace, config["owner"])
        sync_attrs['completed'] = False

        logger.debug('Syncing attributes: %s', str(sync_attrs))

        try:
            return self.create_task(workspace, project, question, sync_attrs)
            logger.debug('Created new task.')
        except asana.error.InvalidRequestError:  # Already exists
            pass

        # Ok, it already exists or it's not worthy of a new issue. Try syncing...
        try:
            task = self.find_task(question)
            task_id = task['id']
            logger.debug('Found task: %d', task_id)

            # Check to see if this task was already assigned. If so, don't
            # re-assign.
            if task['assignee']:
                sync_attrs.pop('assignee', None)

            task = self._client.tasks.update(task_id, sync_attrs)
        except ValueError:
            # Only an error in the event that it meets the criteria for creation
            logger.error('Somehow could not find task for %d event though'
                        ' we think we had a duplicate.', question)

        logger.debug('No task created.')

    def find_task(self, question):
        """Find task corresponding to the issue."""
        try:
            return self._client.tasks.find_by_id('external:' + question_to_id(question))
        except asana.error.NotFoundError as e:
            raise ValueError('No task found for issue.') from e

    def create_task(self, workspace: int, project: int, question, attrs: dict):
        """Create a task corresponding to a GitHub issue."""
        tag = self.find_stackoverflow_tag(workspace)
        title = question.find('atom:title', xmlns).text
        params = {'external': {'id': question_to_id(question)},
                  'name': title,
                  'notes': '\n\n'.join((question.find('atom:id', xmlns).text,
                                        question.find('atom:summary', xmlns).text)),
                  'projects': [project],
                  'tags': [tag]}
        params.update(attrs)
        return self._client.tasks.create_in_workspace(workspace, params)

def question_to_id(question):
    """Create a unique id from a question."""
    _, question_id = question.find('atom:id', xmlns).text.rsplit('/', maxsplit=1)
    return 'stackoverflow-{}'.format(question_id)


if __name__ == '__main__':
    check_stack_overflow()