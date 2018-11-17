from collections import namedtuple
from functools import lru_cache
import json
import logging
import os

import asana
import boto3
import requests

logger = logging.getLogger('asanabot')
logger.setLevel(logging.DEBUG)

s3 = boto3.resource('s3')

def process_payload(event, context):
    """Take the in-bound message and feed to syncing code."""
    try:
        asana_client = get_asana_client()
    except Exception as e:
        logger.exception('Error initializing Asana client:', exc_info=e)
        raise

    try:
        logger.debug('Event: %s', event)
        for record in event['Records']:
            if record['EventSource'] == 'aws:sns':
                logger.info('Received: %s', record['Sns']['MessageId'])
                body = json.loads(record['Sns']['Message'])
                headers = {'Accept': 'application/vnd.github.machine-man-preview+json'}
                issue = IssueInfo.from_json(body, api_headers=headers)
                logger.debug('Handling issue: %s', issue)
                syncer = AsanaSync(asana_client)
                syncer.sync_issue(issue)
    except ValueError as e:
        logger.info('Unhandled json event type: %s', json.dumps(body)[:100])
        logger.info('Not an event for me. ({})'.format(e))
    except Exception as e:
        logger.exception('Exception:', exc_info=e)
        raise e

def get_asana_client():
    """Handle the details of setting up OAUTH2 access to Asana."""
    creds_obj = s3.Object('unidata-python', 'asanabot/asana_client')
    creds = json.loads(creds_obj.get()['Body'].read())

    ASANA_CLIENT_ID = creds['ASANA_CLIENT_ID']
    ASANA_SECRET_ID = creds['ASANA_CLIENT_SECRET']
    token_key = 'asanabot/asana_token'

    def save_token(token):
        token_obj = s3.Object('unidata-python', token_key)
        token_obj.put(Body=json.dumps(token))

    token_obj = s3.Object('unidata-python', token_key)
    token = json.loads(token_obj.get()['Body'].read())

    return asana.Client.oauth(client_id=ASANA_CLIENT_ID, client_secret=ASANA_SECRET_ID, token=token,
                              auto_refresh_url='https://app.asana.com/-/oauth_token',
                              auto_refresh_kwargs={'client_id': ASANA_CLIENT_ID, 'client_secret': ASANA_SECRET_ID},
                              token_updater=save_token, redirect_uri='urn:ietf:wg:oauth:2.0:oob')


_IssueInfo = namedtuple('IssueInfo', ['number', 'organization', 'repository',
                                      'title', 'state', 'milestoned', 'assignee',
                                      'is_pr', 'html_url', 'body', 'repo_has_milestones'])
class IssueInfo(_IssueInfo):
    @classmethod
    def from_json(cls, json: dict, api_headers={}):
        try:
            fields = {}
            fields['organization'] = json['organization']['login']
            fields['repository'] = json['repository']['name']
            fields['repo_has_milestones'] = cls._check_for_milestones(json['repository'],
                                                                      api_headers)
            fields['is_pr'] = 'pull_request' in json
            nested = json['pull_request'] if fields['is_pr'] else json['issue']
            fields['number'] = nested['number']
            fields['title'] = nested['title']
            fields['state'] = nested['state']
            fields['milestoned'] = bool(nested['milestone'])
            fields['html_url'] = nested['html_url']
            fields['body'] = nested['body']
            if nested['assignee']:
                fields['assignee'] = cls._get_user_name(nested['assignee'], api_headers)
            elif nested.get('requested_reviewers'):
                logger.debug('Choosing from requested reviewers: %s', str(nested['requested_reviewers']))
                pick = fields['number'] % len(nested['requested_reviewers'])
                picked_user = nested['requested_reviewers'][pick]
                fields['assignee'] = cls._get_user_name(picked_user, api_headers)
            else:
                fields['assignee'] = None
            return cls(**fields)
        except KeyError as e:
            logger.debug('Event missing something: %s', e)
            raise ValueError('Improper event json')

    @staticmethod
    def _check_for_milestones(repo_json, headers={}):
        url = repo_json['milestones_url'].rsplit('{', maxsplit=1)[0]
        resp = requests.get(url, headers=headers)
        return bool(resp.json())

    @staticmethod
    def _get_user_name(user_json, headers={}):
        resp = requests.get(user_json['url'], headers=headers)
        return resp.json()['name']

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

    @lru_cache()
    def find_done_section(self, project: int):
        """Find the done section of a project if there is one."""
        for section in self._client.sections.find_by_project(project):
            if section['name'].lower() == 'done':
                return section['id']
        return None

    def sync_issue(self, issue: IssueInfo):
        """Synchronize a GitHub issue to an Asana task.

        Either create a new task or update attributes of existing task.
        """
        repo = issue.repository
        org = issue.organization

        logger.debug('Syncing for %s/%s', org, repo)
        workspace = self.find_workspace(org)['id']
        project = self.find_project(workspace, repo)['id']

        sync_attrs = {}
        if issue.assignee:
            sync_attrs['assignee'] = self.github_to_asana_user(workspace, issue.assignee)
        else:
            sync_attrs['assignee'] = 'null'

        sync_attrs['completed'] = issue.state == 'closed'

        logger.debug('Syncing attributes: %s', str(sync_attrs))

        # Create a new task if appropriate
        create_new = should_make_new_task(issue)
        logger.debug('Should we create a new task: %s', create_new)
        try:
            if create_new:
                logger.debug('Trying to create a new task...')
                task = self.create_task(workspace, project, issue, sync_attrs)
                logger.info('Created new task: %s', task)
                return
        except asana.error.InvalidRequestError as e:  # Already exists
            logger.exception('Invalid request creating task (likely dupe): %s', e)

        # Ok, it already exists or it's not worthy of a new issue. Try syncing...
        try:
            task = self.find_task(issue)
            logger.info('Found task: %s', task)

            # Check to see if this task was already assigned. If so, don't
            # re-assign.
            if task['assignee']:
                sync_attrs.pop('assignee', None)

            task = self._client.tasks.update(task['id'], sync_attrs)
            logger.debug('Updated task.')

            # If we completed, try to move to Done section
            if sync_attrs['completed']:
                done_section = self.find_done_section(project)
                if done_section is not None:
                    self._client.tasks.add_project(task['id'], {'project': project,
                                                                'section': done_section})
                    logger.debug('Moved to completed column.')

            return
        except ValueError:
            # Only an error in the event that it meets the criteria for creation
            if create_new:
                logger.error('Somehow could not find task for %d event though'
                            ' we think we had a duplicate.', issue.number)

        logger.debug('No task created.')

    def find_task(self, issue):
        """Find task corresponding to the issue."""
        try:
            return self._client.tasks.find_by_id('external:' + issue_to_id(issue))
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
    if issue.is_pr:
        return True

    # If it's been assigned, create a task
    if issue.assignee is not None:
        return True

    # If the repo has milestones, look at whether this issue has one assigned
    # if issue.repo_has_milestones:
    #     return issue.milestoned

    # Not a PR, not assigned, and no milestones--so ignore it
    # return False
    # For now, create new tasks as long as it's not closed/merged
    return True


def issue_to_id(issue):
    """Create a unique id from an issue."""
    return '{0.organization}-{0.repository}-{0.number:d}'.format(issue)