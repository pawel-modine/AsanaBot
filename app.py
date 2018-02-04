import hashlib
import hmac
import json
import logging
import os
import os.path
import secrets

import asana
from chalice import Chalice, UnauthorizedError

from chalicelib.sync import AsanaSync, IssueInfo

app = Chalice(app_name='asana-sync')
app.log.setLevel(logging.DEBUG)

@app.route('/')
def hello():
    return 'Hello World!'

@app.route('/github/auth')
def github_auth():
    return 'Handle authorization'

@app.route('/github/setup')
def github_setup():
    return 'Handle setup'

@app.route('/hooks/github', methods=['POST'])
def sync():
    check_signature(app.current_request)
    try:
        task = {}
        body = app.current_request.json_body
        issue = IssueInfo.from_json(body)
        app.log.debug('Handling issue: %s', issue)
        task = syncer.sync_issue(issue)
    except ValueError:
        app.log.info('Unhandled json event type: %s', json.dumps(body)[:100])
        task['message'] = 'Not an event for me.'
    except Exception as e:
        app.log.exception('Exception:', exc_info=e)
        raise e
    return task


def check_signature(request):
    if 'X-HUB-SIGNATURE' not in request.headers:
        raise UnauthorizedError('Missing X-HUB-SIGNATURE header.')

    alg, header_sig = request.headers['X-HUB-SIGNATURE'].split('=')
    digest = hmac.HMAC(os.environ['GITHUB_WEBHOOK_SECRET'].encode('ascii'),
                       request.raw_body, digestmod=getattr(hashlib, alg))
    sig = digest.hexdigest()
    app.log.debug('Comparing signatures. Got: %s Calculated: %s', header_sig, sig)

    if not secrets.compare_digest(header_sig, sig):
        raise UnauthorizedError('Signatures do not match.')


def get_asana_client():
    """Handle the details of setting up OAUTH2 access to Asana."""
    ASANA_CLIENT_ID = os.environ['ASANA_CLIENT_ID']
    ASANA_SECRET_ID = os.environ['ASANA_CLIENT_SECRET']
    token_file = os.path.join(os.path.dirname(__file__), 'chalicelib', 'asana-token')

    def save_token(token):
        # TODO: Write somewhere. S3?
        # with open(token_file, 'w') as fobj:
        #     fobj.write(json.dumps(token))
        os.environ['ASANA_OAUTH_TOKEN'] = json.dumps(token)

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
