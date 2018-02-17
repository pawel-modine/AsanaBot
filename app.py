import hashlib
import hmac
import json
import logging
import os
import os.path
import secrets
import urllib.parse

import asana
from flask import (Flask, Response, jsonify, redirect, render_template_string,
                   request, session, url_for)

from sync import AsanaSync, IssueInfo

app = Flask('asana-sync')
app.secret_key = 'set this to something secret'
app.logger.setLevel(logging.DEBUG)
app.logger.addHandler(logging.StreamHandler())


@app.route('/')
def main_page():
    token = session.get('token')
    if token:
        return 'Hello World!'
    else:
        return render_template_string('''
<p><input type="button" class="btn btn-info" value="Input Button" onclick="location.href = '{{ auth_url }}';"></p>
''', auth_url=url_for('github_login'))


@app.route('/github/login')
def github_login():
    github_auth_url = 'http://github.com/login/oauth/authorize?'
    query = {'client_id': 'Iv1.8c1199b7a74722cc',
             'redirect_uri': request.url_root + 'github/auth',
             'state': 'mystatehere'}
    app.logger.debug('Redirect_uri: %s', request.url_root + 'github/auth')
    return redirect(github_auth_url + urllib.parse.urlencode(query))

#https://tbzpe7fgh3.execute-api.us-east-1.amazonaws.com/dev/github/auth

@app.route('/github/auth')
def github_auth():
    app.logger.debug('In auth')
    return 'Handle authorization'


@app.route('/github/setup')
def github_setup():
    return 'Handle setup'


@app.route('/hooks/github', methods=['POST'])
def sync():
    try:
        if not 'localhost' in request.url_root:
            check_signature(request)
        task = {}
        body = request.get_json()
        headers = {'Accept': 'application/vnd.github.machine-man-preview+json'}
        issue = IssueInfo.from_json(body, api_headers=headers)
        app.logger.debug('Handling issue: %s', issue)
        task = syncer.sync_issue(issue)
    except ValueError:
        app.logger.info('Unhandled json event type: %s', json.dumps(body)[:100])
        task['message'] = 'Not an event for me.'
    except UnauthorizedError as e:
        app.logger.debug('Handling unauthorized access.')
        return Response(str(e), 401)
    except Exception as e:
        app.logger.exception('Exception:', exc_info=e)
        raise e
    return jsonify(task)


def check_signature(request):
    if 'X-HUB-SIGNATURE' not in request.headers:
        raise UnauthorizedError('Missing X-HUB-SIGNATURE header.')

    alg, header_sig = request.headers['X-HUB-SIGNATURE'].split('=')
    digest = hmac.HMAC(os.environ['GITHUB_WEBHOOK_SECRET'].encode('ascii'),
                       request.data, digestmod=getattr(hashlib, alg))
    sig = digest.hexdigest()
    app.logger.debug('Comparing signatures. Got: %s Calculated: %s', header_sig, sig)

    if not secrets.compare_digest(header_sig, sig):
        raise UnauthorizedError('Signatures do not match.')


def get_asana_client():
    """Handle the details of setting up OAUTH2 access to Asana."""
    ASANA_CLIENT_ID = os.environ['ASANA_CLIENT_ID']
    ASANA_SECRET_ID = os.environ['ASANA_CLIENT_SECRET']
    token_file = os.path.join(os.path.dirname(__file__), 'asana-token')

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


class UnauthorizedError(Exception):
    pass