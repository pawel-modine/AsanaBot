import hashlib
import hmac
import logging
import os
import secrets

import boto3

logger = logging.getLogger('asanabot')
logger.setLevel(logging.INFO)

sns = boto3.client('sns')
ssm = boto3.client('ssm')

def enqueue_event(event, context):
    """Handle getting an event from GitHub and putting it into the pipeline."""
    try:
        headers = event['headers']
        logger.debug('Headers: %s', headers)
        body = event['body']
        logger.debug('Body: %s', body)
        check_signature(headers, body)
        msg = sns.publish(TopicArn=os.environ['SNS_TOPIC_NAME'], Message=body)
    except UnauthorizedError as e:
        logger.debug('Handling unauthorized access.')
        return dict(statusCode=401, headers={'Content-Type': 'application/json'},
                    body=str(e))
    except Exception as e:
        logger.exception('Exception:', exc_info=e)
        raise e
    return dict(statusCode=200,
                headers={'Content-Type': 'application/json'},
                body=msg['MessageId'])


def check_signature(headers, body):
    """Verify that the payload is properly signed."""
    if 'X-Hub-Signature' not in headers:
        raise UnauthorizedError('Missing X-Hub-Signature header.')

    alg, header_sig = headers['X-Hub-Signature'].split('=')
    secret_key = ssm.get_parameter(Name='/asanabot/GitHubToken',
                                   WithDecryption=True)['Parameter']['Value']
    digest = hmac.HMAC(secret_key.encode('ascii'), body.encode('utf-8'),
                       digestmod=getattr(hashlib, alg))
    sig = digest.hexdigest()
    logger.debug('Comparing signatures. Got: %s Calculated: %s', header_sig, sig)

    if not secrets.compare_digest(header_sig, sig):
        raise UnauthorizedError('Signatures do not match.')


class UnauthorizedError(Exception):
    pass