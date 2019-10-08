import json
import logging
import xml.etree.ElementTree as ET

import asana
import boto3
import urllib.request

from sync import get_asana_client

logger = logging.getLogger('asanabot')
logger.setLevel(logging.INFO)

xmlns = {'atom': 'http://www.w3.org/2005/Atom'}
s3 = boto3.resource('s3')

class Config:
    def __init__(self):
        self._obj = s3.Object('unidata-python', 'asanabot/stackoverflow_config.json')
        self._data = json.loads(self._obj.get()['Body'].read())

    def __iter__(self):
        return iter(self._data)

    def save(self):
        self._obj.put(Body=json.dumps(self._data))


# Use a global to keep it cached
config = Config()


def check_stack_overflow(event, context):
    asana = AsanaSubmit(get_asana_client())

    for item in config:
        xml = urllib.request.urlopen('https://stackoverflow.com/feeds/tag?tagnames={}&sort=newest'.format(item['tag']))
        content = xml.read()
        root = ET.fromstring(content)
        last_update = item['updated']
        for question in root.iterfind('atom:entry', xmlns):
            update_time = question.find('atom:updated', xmlns).text
            if update_time > last_update:
                logger.info('Adding task for question: %s',
                            question.find('atom:title', xmlns).text)
                asana.submit(question, item)

        item['updated'] = root.find('atom:updated', xmlns).text

    config.save()


class AsanaSubmit:
    def __init__(self, client):
        self._client = client
        self._unidata_gid = None
        self._tag_gid = None

    @property
    def unidata(self):
        """The Unidata Asana workspace gid."""
        if self._unidata_gid is None:
            for workspace in self._client.workspaces.find_all():
                if workspace['name'] == 'Unidata':
                    self._unidata_gid = workspace['gid']
                    logger.debug('Found Unidata workspace: %s', workspace)
                    break
            else:
                raise ValueError('Could not find workspace for Unidata.')
        return self._unidata_gid

    @property
    def stackoverflow_tag(self):
        """Find the StackOverflow tag on Asana."""
        if self._tag_gid is None:
            tag_name = 'StackOverflow'
            for tag in self._client.tags.find_by_workspace(self.unidata):
                if tag['name'].lower() == tag_name.lower():
                    self._tag_gid = tag['gid']
                    break
            else:  # Did not find one
                tag = self._client.tags.create_in_workspace(workspace, dict(name=tag_name))
                self._tag_gid = tag['gid']

        return self._tag_gid

    def find_project(self, workspace: int, name: str):
        """Find a project by name."""
        for project in self._client.projects.find_all({'workspace': workspace}):
            if project['name'] == name:
                return project
        raise ValueError('Could not find appropriate project for: {}'.format(name))

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
        project = self.find_project(self.unidata, config['project'])
        logger.debug('Got project for %s: %s', config['project'], project)
        project = project['gid']

        sync_attrs = {}
        sync_attrs['assignee'] = self.find_asana_user(self.unidata, config['owner'])
        sync_attrs['completed'] = False

        logger.debug('Syncing attributes: %s', str(sync_attrs))

        try:
            return self.create_task(self.unidata, project, question, sync_attrs)
        except asana.error.InvalidRequestError as e:  # Already exists
            logger.debug('Error from creating task: %s', e)

        # Ok, it already exists or an error occurred. Try syncing...
        try:
            task = self.find_task(question)
            task_id = task['gid']
            logger.debug('Found task: %s', task_id)

            # Check to see if this task was already assigned and is not closed.
            # If so, don't re-assign.
            if task['assignee'] and not task['completed']:
                sync_attrs.pop('assignee', None)

            return self._client.tasks.update(task_id, sync_attrs)
        except ValueError as e:
            # Only an error in the event that it meets the criteria for creation
            logger.exception('Somehow could not find task for %s event though'
                             ' we think we had a duplicate.', question_to_id(question),
                             exc_info=e)
        except Exception as e:
            logger.exception('Something else went wrong.', exc_info=e)

    def find_task(self, question):
        """Find task corresponding to the issue."""
        try:
            return self._client.tasks.find_by_id('external:' + question_to_id(question))
        except asana.error.NotFoundError as e:
            raise ValueError('No task found for issue.') from e

    def create_task(self, workspace: int, project: int, question, attrs: dict):
        """Create a task corresponding to a GitHub issue."""
        title = question.find('atom:title', xmlns).text
        params = {'external': {'gid': question_to_id(question)},
                  'name': title,
                  'notes': '\n\n'.join((question.find('atom:id', xmlns).text,
                                        question.find('atom:summary', xmlns).text)),
                  'projects': [project],
                  'tags': [self.stackoverflow_tag]}
        params.update(attrs)
        return self._client.tasks.create_in_workspace(workspace, params)

def question_to_id(question):
    """Create a unique gid from a question."""
    _, question_id = question.find('atom:id', xmlns).text.rsplit('/', maxsplit=1)
    return 'stackoverflow-{}'.format(question_id)


if __name__ == '__main__':
    check_stack_overflow(None, None)