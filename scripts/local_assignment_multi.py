"""
Script designed for local execution.
Reads a CSV file of email addresses and subscription plan uuids
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
  --output-file=local-assignment-output.csv \
  --chunk-size=10 \
  --environment=local \
  --sleep-interval=5 \
  --fetch-jwt
```

Options:
* ``input-file`` is your input file - it should contain columns ``email`` and ``subcription_plan_uuid``. 
This script does not attempt to do any validation. Required.

* ``output-file`` is where results of the call to the assignment view are stored.
It'll be a CSV with four columns: the chunk id, email address, subscription_plan_uuid, and assigned license uuid.

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
from pprint import pprint

import click
import requests

from utils import is_valid_email


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

OUTPUT_FIELDNAMES = ['chunk_id', 'subscription_plan_uuid', 'email', 'license_uuid']
INPUT_FIELDNAMES = ['university_name', 'email']
PLANS_BY_NAME_FIELDNAMES = ['university_name', 'subscription_plan_uuid']


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
    with open(results_file, 'a+', encoding='latin-1') as f_in:
        f_in.seek(0)
        reader = csv.DictReader(f_in, fieldnames=OUTPUT_FIELDNAMES, delimiter=',')

        try:
            # skip the header
            next(reader)
        except StopIteration:
            # it's an empty file created by "a+" above, so just exit
            return already_processed_emails

        for row in reader:
            email = row['email']
            subscription_plan_uuid = row['subscription_plan_uuid']
            already_processed_emails[email] = subscription_plan_uuid

    print('Read {} already processed emails'.format(len(already_processed_emails)))
    return already_processed_emails


def get_plan_uuids_by_name(plans_by_name_file):
    plans_by_name = {}
    with open(plans_by_name_file, 'a+', encoding='latin-1') as f_in:
        f_in.seek(0)
        reader = csv.DictReader(f_in, fieldnames=PLANS_BY_NAME_FIELDNAMES, delimiter=',')

        # skip the header
        next(reader)

        for row in reader:
            university_name = row['university_name']
            subscription_plan_uuid = row['subscription_plan_uuid']

            if university_name in plans_by_name:
                raise Exception('Duplicate university name in mapping')
            if subscription_plan_uuid in plans_by_name.values():
                print(subscription_plan_uuid)
                raise Exception('Duplicate subscription plan uuid in mapping')

            plans_by_name[university_name] = subscription_plan_uuid

    print('Read plans by name:')
    pprint(plans_by_name)

    return plans_by_name


def get_email_chunks(input_file_path, plans_by_name, chunk_size=DEFAULT_CHUNK_SIZE):
    """
    Yield chunks of (chunk_id, subscription_plan, email) from the given input file.  
    Given the same input file and chunk_size,
    this will always yield rows with the same chunk id for each provided email.

    Params:
      input_file_path: Filename of CSV containing headers `email`, `university_name`.
      plans_by_name: Dict mapping `university_name` to a subscription plan uuid.
    """
    current_chunk = []
    chunk_id = 0
    current_subscription_plan_uuid = None
    # CSVs can contain non-ascii characters, latin-1
    # is the encoding that currently works with our production input.
    # could eventually be parameterized as input to this command.
    with open(input_file_path, 'r', encoding='latin-1') as f_in:
        reader = csv.DictReader(f_in, fieldnames=INPUT_FIELDNAMES, delimiter=',')

        # read and skip the header
        next(reader)

        for row in reader:
            email = row['email']
            if not is_valid_email(email):
                print("Invalid email:", email)
                continue

            university_name = row['university_name']
            subscription_plan_uuid = plans_by_name.get(university_name)
            if not subscription_plan_uuid:
                print(f'No plan matches the given name: {university_name}')

            # This should only happen on the very first row we process
            if not current_subscription_plan_uuid:
                current_subscription_plan_uuid = subscription_plan_uuid

            if current_subscription_plan_uuid != subscription_plan_uuid:
                # we've hit a transition point to the next plan,
                # yield what we have and reset the chunk before
                # appending this email to a new chunk.
                yield chunk_id, current_subscription_plan_uuid, current_chunk
                current_chunk = []
                chunk_id += 1
                current_subscription_plan_uuid = subscription_plan_uuid

            current_chunk.append(email)

            if len(current_chunk) == chunk_size:
                # If we've reached the max chunk size, yield
                # and reset the chunk, but don't reset the current sub plan.
                yield chunk_id, current_subscription_plan_uuid, current_chunk
                current_chunk = []
                chunk_id += 1

    if current_chunk:
        yield chunk_id, current_subscription_plan_uuid, current_chunk


def _post_assignments(
    subscription_plan_uuid, emails_for_chunk, environment='local', fetch_jwt=False, notify_users=False,
):
    """
    Make the POST request to assign licenses.
    """
    url_pattern = ENVIRONMENTS[environment]
    url = url_pattern.format(subscription_plan_uuid=subscription_plan_uuid)

    payload = {
        'user_emails': emails_for_chunk,
        'notify_users': notify_users,
    }
    headers = {
        "Authorization": "JWT {}".format(_get_jwt(fetch_jwt, environment=environment)),
    }

    return requests.post(url, json=payload, headers=headers)


def request_assignments(subscription_plan_uuid, chunk_id, emails_for_chunk, environment='local', fetch_jwt=False):
    """
    Makes the request to the ``assign`` endpoint for the given subscription plan
    to assign liceses for `emails_for_chunk`.
    """
    print(
        '\nSending assignment request for plan', subscription_plan_uuid,
        'chunk id', chunk_id,
        'with num emails', len(emails_for_chunk),
    )

    response = _post_assignments(subscription_plan_uuid, emails_for_chunk, environment, fetch_jwt)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        # if it's a 401, try refetching the JWT and re-try the request
        print(response.content)
        if response.status_code == 401:
            print('EXPIRED JWT, REFETCHING...')
            response = _post_assignments(subscription_plan_uuid, emails_for_chunk, environment, fetch_jwt)
            response.raise_for_status()
        else:
            print('Continuing past this exception.')

    response_data = response.json()

    results_for_chunk = []
    for assignment in response_data['license_assignments']:
        results_for_chunk.append([
            str(chunk_id), subscription_plan_uuid, assignment['user_email'], str(assignment['license'])
        ])

    print('Num assigned by assignment API:', response_data['num_successful_assignments'])
    print('Num already associated from assignment API:', response_data['num_already_associated'])
    print(
        'Successfully sent assignment request for plan', subscription_plan_uuid,
        'chunk id', chunk_id,
        'with num emails', len(results_for_chunk),
    )

    return results_for_chunk


def do_assignment_for_chunk(
    subscription_plan_uuid, chunk_id, email_chunk,
    already_processed, results_file, environment='local', fetch_jwt=False, sleep_interval=DEFAULT_SLEEP_INTERVAL,
):
    """
    Given a "chunk" list emails for which assignments should be requested, checks if the given
    email has already been processed for the given email.  If not, adds it to a list for this
    chunk to be requested, then requests license assignment in the given subscription plan.
    On successful request, appends results including chunk id, email, and license uuid
    to results_file.
    """
    payload_for_chunk = []
    for email in email_chunk:
        if email in already_processed:
            continue
        payload_for_chunk.append(email)

    results_for_chunk = []
    if payload_for_chunk:
        try:
            results_for_chunk = request_assignments(
                subscription_plan_uuid, chunk_id, payload_for_chunk, environment, fetch_jwt,
            )
        except Exception as exc:
            print(exc)
            print('continuing on...')
            return
        with open(results_file, 'a+') as f_out:
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
    '--plans-by-name-file',
    help='Path to CSV mapping external names to internal subscription plan uuids',
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
@click.option(
    '--dry-run',
    help='Just prints what emails would be assigned to plan if true.',
    is_flag=True,
)

def run(input_file, plans_by_name_file, output_file, chunk_size, environment, sleep_interval, fetch_jwt, dry_run):
    """
    Entry-point for this script.
    """
    already_processed = {}
    if output_file:
        already_processed = get_already_processed_emails(output_file)

    plan_uuids_by_name = get_plan_uuids_by_name(plans_by_name_file)

    for chunk_id, subscription_plan_uuid, email_chunk in get_email_chunks(input_file, plan_uuids_by_name, chunk_size):
        if dry_run:
            print(f'DRY RUN: chunk_id={chunk_id} would assign to plan {subscription_plan_uuid} emails: {email_chunk}')
        else:
            do_assignment_for_chunk(
                subscription_plan_uuid, chunk_id, email_chunk,
                already_processed, output_file, environment, fetch_jwt, sleep_interval,
            )

if __name__ == '__main__':
    run()
