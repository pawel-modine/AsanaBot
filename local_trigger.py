"""Trigger GitHub events based on date."""
from datetime import datetime
import json

import github
import boto3

# Set up an SNS client
sns = boto3.client('sns')

with open('/Users/rmay/repos/github-utils/token', 'rt') as f:
    token = f.readline()[:-1]
g = github.Github(token)

unidata = g.get_organization('Unidata')

for repo_name in ['MetPy', 'siphon', 'python-gallery', 'python-workshop']:
    repo = unidata.get_repo(repo_name)
    print(repo)
    for issue in repo.get_issues(state='all', since=datetime(2019, 10, 1)):
        print(f'Syncing {issue.number}...', end='')
        payload = dict(repository=repo.raw_data, organization=unidata.raw_data,
                       issue=issue.raw_data)
        if issue.pull_request:
            payload['pull_request'] = repo.get_pull(issue.number).raw_data

        sns.publish(TopicArn='arn:aws:sns:us-east-1:363610688368:asanabot-GitHubMessagePipe-1C6HPH30762BJ',
                    Message=json.dumps(payload))
        print('Done.')
