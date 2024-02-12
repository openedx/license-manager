"""
Script designed for local execution.
Reads a CSV file of email addresses and target subscription plan uuid
as input, then chunks those up in calls to the ``assign`` view.

To use:
```
# os environ names are meaningful and should correspond to the requested environment
# this allows us to fetch a JWT before each request, so you don't have to 
# worry about your JWT expiring in the middle of the script execution.
export CLIENT_SECRET_LOCAL=[your-client-secret]
export CLIENT_ID_LOCAL=[your-client-id]

pip install -r scripts/local_assignment_requirements.txt

python local_assignment.py \
  --input-file=your-input-file.csv \
  --subscription-plan-uuid=[the-plan-uuid] \
  --output-file=local-assignment-output.csv \
  --chunk-size=10 \
  --environment=local \
  --sleep-interval=5 \
  --fetch-jwt
```

Options:
* ``input-file`` is your input file - it should be a single-column csv 
(or just a list delimited by newlines, really) of valid email addresses.  This 
script does not attempt to do any validation. Required.

* ``subscription-plan-uuid`` is the uuid of the plan to assign license to. Required.

* ``output-file`` is where results of the call to the assignment view are stored.
It'll be a CSV with three columns: the chunk id, email address, and assigned license uuid.

* ``chunk-size`` is how many emails will be contained in each chunk. Default is 100.

* ``environment`` Which environment to execute against. Choices are 'local', 'stage', or 'prod'.

* ``sleep-interval`` is useful for not overwhelming the license-manager celery broker.
The assignment endpoints causes several different asychronous tasks to be submitted
downstream of successful assignment.
"""
import csv
import json
import os
import time

import click
import requests


DEFAULT_CHUNK_SIZE = 100

DEFAULT_SLEEP_INTERVAL = 0.5

ENVIRONMENTS = {
    'local': 'http://localhost:18170/api/v1/subscriptions/{subscription_plan_uuid}/licenses/assign/',
    'stage': 'https://license-manager.stage.edx.org/api/v1/subscriptions/{subscription_plan_uuid}/licenses/assign/',
    'prod': 'https://license-manager.edx.org/api/v1/subscriptions/{subscription_plan_uuid}/licenses/assign/',
}

ACCESS_TOKEN_URL_BY_ENVIRONMENT = {
    'local': 'http://localhost:18000/oauth2/access_token/',
    'stage': 'https://courses.stage.edx.org/oauth2/access_token/',
    'prod': 'https://courses.edx.org/oauth2/access_token/',
}

def _get_jwt(fetch_jwt=False, environment='local'):
    if fetch_jwt:
        client_id = os.environ.get(f'CLIENT_ID_{environment}'.upper())
        client_secret = os.environ.get(f'CLIENT_SECRET_{environment}'.upper())
        assert client_id and client_secret, 'client_id and client_secret must be set if fetch_jwt is true'
        request_payload = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'client_credentials',
            'token_type': 'jwt',
        }
        # we want to sent with a Content-Type of 'application/x-www-form-urlencoded'
        # so send in the `data` param instead of `json`.
        response = requests.post(
            ACCESS_TOKEN_URL_BY_ENVIRONMENT.get(environment),
            data=request_payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        response.raise_for_status()
        return response.json().get('access_token')
    else:
        return os.environ.get('LICENSE_MANAGER_JWT')


def get_already_processed_emails(results_file):
    """
    Reads a headerless CSV with rows representing `chunk_id,email,assigned_license_uuid`
    and returns a dictionary mapping already processed emails to their chunk_id.
    """
    already_processed_emails = {}
    with open(results_file, 'r') as f_in:
        reader = csv.reader(f_in, delimiter=',')
        for (chunk_id, email, license_uuid) in reader:
            already_processed_emails[email] = chunk_id
    return already_processed_emails


def get_email_chunks(input_file_path, chunk_size=DEFAULT_CHUNK_SIZE):
    """
    Yield chunks of email addresses from the given input file.  Given the same input file and chunk_size,
    this will always yield rows with the same chunk id for each provided email.
    """
    current_chunk = []
    chunk_id = 0
    with open(input_file_path, 'r') as f_in:
        reader = csv.reader(f_in, delimiter=',')
        for row in reader:
            email = row[0]
            current_chunk.append(email)
            if len(current_chunk) == chunk_size:
                yield chunk_id, current_chunk
                current_chunk = []
                chunk_id += 1

    if current_chunk:
        yield chunk_id, current_chunk


def request_assignments(subscription_plan_uuid, chunk_id, emails_for_chunk, environment='local', fetch_jwt=False):
    """
    Makes the request to the ``assign`` endpoint for the given subscription plan
    to assign liceses for `emails_for_chunk`.
    """
    print('\nSending assignment request for chunk id', chunk_id, 'with num emails', len(emails_for_chunk))

    url_pattern = ENVIRONMENTS[environment]
    url = url_pattern.format(subscription_plan_uuid=subscription_plan_uuid)

    payload = {
        'user_emails': emails_for_chunk,
        'notify_users': False,
    }
    headers = {
        "Authorization": "JWT {}".format(_get_jwt(fetch_jwt, environment=environment)),
    }

    response = requests.post(url, json=payload, headers=headers)

    response.raise_for_status()
    response_data = response.json()

    results_for_chunk = []
    for assignment in response_data['license_assignments']:
        results_for_chunk.append([str(chunk_id), assignment['user_email'], str(assignment['license'])])

    print('Num assigned by assignment API:', response_data['num_successful_assignments'])
    print('Num already associated from assignment API:', response_data['num_already_associated'])
    print('Successfully sent assignment request for chunk id', chunk_id, 'with num emails', len(results_for_chunk))

    return results_for_chunk


def do_assignment_for_chunk(
    subscription_plan_uuid, chunk_id, email_chunk,
    results_file, environment='local', fetch_jwt=False, sleep_interval=DEFAULT_SLEEP_INTERVAL
):
    """
    Given a "chunk" list emails for which assignments should be requested, checks if the given
    email has already been processed for the given email.  If not, adds it to a list for this
    chunk to be requested, then requests license assignment in the given subscription plan.
    On successful request, appends results including chunk id, email, and license uuid
    to results_file.
    """
    already_processed = {}
    if results_file:
        already_processed = get_already_processed_emails(results_file)

    payload_for_chunk = []
    for email in email_chunk:
        if email in already_processed:
            continue
        payload_for_chunk.append(email)

    results_for_chunk = []
    if payload_for_chunk:
        results_for_chunk = request_assignments(
            subscription_plan_uuid, chunk_id, payload_for_chunk, environment, fetch_jwt,
        )
        with open(results_file, 'a') as f_out:
            writer = csv.writer(f_out, delimiter=',')
            writer.writerows(results_for_chunk)
        if sleep_interval:
            print(f'Sleeping for {sleep_interval} seconds.')
            time.sleep(sleep_interval)
    else:
        print('No assignments need to be made for chunk_id', chunk_id, 'with size', len(email_chunk))


@click.command()
@click.option(
    '--input-file',
    help='Path of local file containing email addresses to assign.',
)
@click.option(
    '--subscription-plan-uuid',
    help='Subscription plan to which licenses should be assigned.',
)
@click.option(
    '--output-file',
    default=None,
    help='CSV file of emails that we have processed.',
)
@click.option(
    '--chunk-size',
    help='Size of email chunks to operate on.',
    default=DEFAULT_CHUNK_SIZE,
    show_default=True,
)
@click.option(
    '--environment',
    help='Which environment to operate in.',
    default='local',
    type=click.Choice(['local', 'stage', 'prod'], case_sensitive=False),
    show_default=True,
)
@click.option(
    '--sleep-interval',
    help='How long, in seconds, to sleep between each chunk.',
    default=DEFAULT_SLEEP_INTERVAL,
    show_default=True,
)
@click.option(
    '--fetch-jwt',
    help='Whether to fetch JWT based on stored client id and secret.',
    is_flag=True,
)

def run(input_file, subscription_plan_uuid, output_file, chunk_size, environment, sleep_interval, fetch_jwt):
    """
    Entry-point for this script.
    """
    for chunk_id, email_chunk in get_email_chunks(input_file, chunk_size):
        do_assignment_for_chunk(
            subscription_plan_uuid, chunk_id, email_chunk,
            output_file, environment, fetch_jwt, sleep_interval,
        )

if __name__ == '__main__':
    run()
