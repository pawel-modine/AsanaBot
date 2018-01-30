import json
import logging
import os
import os.path

import asana
from flask import Flask, jsonify, redirect, request, session
import github

from sync import AsanaSync, logger

app = Flask(__name__)
logger.setLevel(logging.DEBUG)

@app.route('/')
def hello():
    return 'Hello World!'

@app.route('/sync', methods=['POST'])
def sync():
    payload = request.get_json()
    event = github_client.create_from_raw_data(github.IssueEvent.IssueEvent, payload)
    if event.issue is not None:
        logger.debug('Syncing: %s (%d)', event.issue.title, event.issue.number)
        task = syncer.sync_issue(event.issue)
        return jsonify(task)
    else:
        logger.debug('Event had no issue. %s', str(payload)[:100])
        return jsonify({})

def get_asana_client():
    """Handle the details of setting up OAUTH2 access to Asana."""
    ASANA_CLIENT_ID = os.environ['ASANA_CLIENT_ID']
    ASANA_SECRET_ID = os.environ['ASANA_CLIENT_SECRET']
    token_file = 'asana-token'

    def save_token(token):
        with open(token_file, 'w') as fobj:
            fobj.write(json.dumps(token))

    if os.path.exists(token_file):
        with open(token_file, 'r') as fobj:
            token = json.load(fobj)
    else:
        token = json.loads(os.environ['ASANA_OAUTH_TOKEN'])
        save_token(token)

    return asana.Client.oauth(client_id=ASANA_CLIENT_ID, client_secret=ASANA_SECRET_ID, token=token,
                              auto_refresh_url='https://app.asana.com/-/oauth_token',
                              auto_refresh_kwargs={'client_id': ASANA_CLIENT_ID, 'client_secret': ASANA_SECRET_ID},
                              token_updater=save_token, redirect_uri='urn:ietf:wg:oauth:2.0:oob')

github_client = github.Github(os.environ.get('GITHUB_TOKEN'))
syncer = AsanaSync(get_asana_client())

if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    