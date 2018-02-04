import json
import logging
import os
import os.path

import asana
from chalice import Chalice

from chalicelib.sync import AsanaSync, logger

app = Chalice(app_name='asana-sync')
logger.setLevel(logging.DEBUG)

@app.route('/')
def hello():
    return 'Hello World!'

@app.route('/hooks/github')#, methods=['POST'])
def sync():
    payload = app.current_request.json_body
    task = {}
    return task

def get_asana_client():
    """Handle the details of setting up OAUTH2 access to Asana."""
    ASANA_CLIENT_ID = os.environ['ASANA_CLIENT_ID']
    ASANA_SECRET_ID = os.environ['ASANA_CLIENT_SECRET']
    token_file = os.path.join(os.path.dirname(__file__), 'chalicelib', 'asana-token')

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

syncer = AsanaSync(get_asana_client())
