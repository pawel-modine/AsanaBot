import hashlib
import hmac
import json
import logging
import os
import secrets

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def enqueue_event(event, context):
    """Handle getting an event from GitHub and putting it into the pipeline."""
    try:
        headers = event['headers']
        logger.debug('Headers: %s', headers)
        body = event['body']
        logger.debug('Body: %s', body)
        check_signature(headers, body)
        topic = boto3.session.Session().resource('sns').Topic(os.environ['SNS_TOPIC_NAME'])
        msg = topic.publish(Message=body)
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
    s3 = boto3.resource('s3')
    secret_key = s3.Object('unidata-python', 'asanabot/github')
    digest = hmac.HMAC(secret_key.get()['Body'].read(),
                       body.encode('utf-8'), digestmod=getattr(hashlib, alg))
    sig = digest.hexdigest()
    logger.debug('Comparing signatures. Got: %s Calculated: %s', header_sig, sig)

    if not secrets.compare_digest(header_sig, sig):
        raise UnauthorizedError('Signatures do not match.')


class UnauthorizedError(Exception):
    pass