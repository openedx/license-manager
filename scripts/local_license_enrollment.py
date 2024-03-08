"""
Script designed for local execution.

Reads multiple input CSV files describing which emails to enroll in which courses (for one enterprise customer).


To use:
```
# os environ names are meaningful and should correspond to the requested environment
# this allows us to fetch a JWT before each request, so you don't have to
# worry about your JWT expiring in the middle of the script execution.
export CLIENT_SECRET_LOCAL=[your-client-secret]
export CLIENT_ID_LOCAL=[your-client-id]

pip install -r scripts/local_license_enrollment_requirements.txt

python local_license_enrollment.py \
  --input-file=your-input-file.csv \
  --enterprise-uuid=<uuid> \
  --output-file=local-enrollment-output.csv \
  --environment=local \
  --fetch-jwt
```

Options:
* ``--input-file`` is your input file - it should be a CSV containing at least the following header columns:
email, course_run. Required.

* ``--enterprise-uuid`` The UUID of the enterprise to which all enrollments are associated.

* ``--output-file`` is where results of the call to the bulk-license-enrollment view are stored.  It'll be a headerless
CSV with three columns: ``chunk_id``, ``job_id``, ``email``, ``job_results_url``.

* ``--chunk-size`` Number of emails contained in each chunk. Default and max is 1000.

* ``--environment`` Which environment to execute against. Choices are 'local', 'stage', or 'prod'.

* ``--sleep-interval`` is how long to wait between chunk deliveries, in seconds (default = 120).  Each chunk of this
script causes one asynchronous bulk enrollment task to be queued, so this interval is the primary way of controlling
concurrency.  If ``--sleep-interval`` is too high, operational risk is low but enrollment of all learners may take too
long.  If ``--sleep-interval`` is too low, a couple of risks arise: 1) we risk overwhelming the
license_manager.bulk_enrollment dedicated celery queue, and 2) completion rate may be slower than task creation,
increasing risk of accumulating more failed tasks before manually terminating the script.
"""
from collections import defaultdict
import csv
import os
import time

import click
import requests
from requests.models import PreparedRequest


# 1000 is currently the maximum number of emails allowed by the bulk-license-enrollment API endpoint. (I didn't actually
# check this, I just heard that it was 1000; nevertheless, 1000 is a fine number).
DEFAULT_CHUNK_SIZE = 1000

# After manual testing (in stage) with a chunk size of 1000, each async task takes about 8 minutes to complete (while
# 5 tasks are running concurrently, throttled by celery).  Therefore, a 2 minute sleep interval should result in an
# average concurrency of 4 tasks at a time, one less than the celery max concurrency.
#
# With these defaults, 400k enrollments should take about 14 hours.
DEFAULT_SLEEP_INTERVAL = 60 * 2

ENVIRONMENTS = {
    'local': 'http://localhost:18170/api/v1/bulk-license-enrollment',
    'stage': 'https://license-manager.stage.edx.org/api/v1/bulk-license-enrollment',
    'prod': 'https://license-manager.edx.org/api/v1/bulk-license-enrollment',
}

ACCESS_TOKEN_URL_BY_ENVIRONMENT = {
    'local': 'http://localhost:18000/oauth2/access_token/',
    'stage': 'https://courses.stage.edx.org/oauth2/access_token/',
    'prod': 'https://courses.edx.org/oauth2/access_token/',
}


def _get_jwt(fetch_jwt=False, environment='local'):
    """
    Obtain a JWT token by either fetching a new one, or from the LICENSE_MANAGER_JWT environment variable.
    """
    if fetch_jwt:
        client_id = os.environ.get(f'CLIENT_ID_{environment}'.upper())
        client_secret = os.environ.get(f'CLIENT_SECRET_{environment}'.upper())
        assert client_id and client_secret, 'client_id and client_secret must be set if fetch_jwt is true'
        request_payload = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'client_credentials',
            'token_type': 'jwt',
            'scope': 'user_id email profile read write',
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
    Reads a headerless CSV with rows representing `chunk_id,task_id,email` and returns a dictionary mapping
    already processed emails to their chunk_id.
    """
    already_processed_emails = {}
    with open(results_file, 'r') as f_in:
        reader = csv.reader(f_in, delimiter=',')
        for (chunk_id, _, email_address, _) in reader:
            already_processed_emails[email_address] = chunk_id
    return already_processed_emails


def get_email_chunks(input_file_path, chunk_size=DEFAULT_CHUNK_SIZE):
    """
    Yield chunks of emails from the given input file.  Given the same input file and chunk_size,
    this will always yield rows with the same chunk id for each provided email.

    Note: One chunk may not contain multiple courses, so this function is "smart" and defers yeilding chunks until
    enough emails have been accumulated for a given course_run_key.

    Yields:
        3-tuple of (int, str, list of str) with elements:
            - chunk_id
            - course_run_key
            - list of emails
    """
    current_chunks_by_course_run = defaultdict(list)
    chunk_id = 0
    with open(input_file_path, 'r') as f_in:
        reader = csv.DictReader(f_in, delimiter=',')
        for row in reader:
            email = row['email']
            course_run_key = row['course_run_key']
            current_chunks_by_course_run[course_run_key].append(email)
            # Must pre-evaluate the chunks dict (using list()) or else python will complain with: "RuntimeError:
            # dictionary changed size during iteration".
            for course_run_key, email_chunk in list(current_chunks_by_course_run.items()):
                if len(email_chunk) == chunk_size:
                    yield chunk_id, course_run_key, email_chunk
                    del current_chunks_by_course_run[course_run_key]
                    chunk_id += 1
        # Flush the remainder of chunks that didn't reach the full chunk size.
        for course_run_key, email_chunk in current_chunks_by_course_run.items():
            yield chunk_id, course_run_key, email_chunk
            chunk_id += 1


def request_enrollments(
    chunk_id,
    enterprise_uuid,
    course_run_key,
    emails_for_chunk,
    environment='local',
    fetch_jwt=False,
):
    """
    Makes the request to the ``bulk-license-enrollment`` endpoint for the given enterprise to enroll
    `emails_for_chunk` into `course_run_key`.
    """
    print()  # Create visual separation from the last chunk.
    print(
        f'Sending bulk enrollment request for chunk_id={chunk_id} and course_run_key={course_run_key} with '
        f'{len(emails_for_chunk)} emails'
    )

    url = ENVIRONMENTS[environment]
    headers = {
        "Authorization": "JWT {}".format(_get_jwt(fetch_jwt, environment=environment)),
    }
    params = {
        'enterprise_customer_uuid': enterprise_uuid,
    }
    payload = {
        'emails': emails_for_chunk,
        'course_run_keys': [course_run_key],
        'notify': False,
    }
    print(f'POST query parameters: {params}')
    print(f'POST payload: {payload}')

    response = requests.post(
        url,
        headers=headers,
        params=params,
        json=payload,
    )

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        # if it's a 401, try refetching the JWT and re-try the request
        if response.status_code == 401:
            print('EXPIRED JWT, REFETCHING...')
            jwt = _get_jwt(fetch_jwt, environment=environment)
            headers = {
                "Authorization": "JWT {}".format(_get_jwt(fetch_jwt, environment=environment)),
            }
            params = {
                'enterprise_customer_uuid': enterprise_uuid,
            }
            payload = {
                'emails': emails_for_chunk,
                'course_run_keys': [course_run_key],
                'notify': False,
            }
            response = requests.post(
                url,
                headers=headers,
                params=params,
                json=payload,
            )
            response.raise_for_status()

    response_data = response.json()

    # Use the requests library to generate a URL to fetch job results, but not actually call it.
    req = PreparedRequest()
    req.prepare_url(
        url,
        {
            'enterprise_customer_uuid': enterprise_uuid,
            'bulk_enrollment_job_uuid': response_data['job_id'],
        },
    )
    job_results_url = req.url

    results_for_chunk = []
    for email in emails_for_chunk:
        results_for_chunk.append([
            str(chunk_id),
            str(response_data['job_id']),
            email,
            job_results_url,
        ])

    print(
        f'Successfully sent bulk enrollment request containing {len(emails_for_chunk)} emails. '
        f'chunk_id = {chunk_id}, '
        f'course_run_key = {course_run_key}, '
        f'BulkEnrollmentJob UUID = {response_data["job_id"]}, '
        f'job results URL = {job_results_url}'
    )

    return results_for_chunk


def do_enrollment_for_chunk(
    chunk_id,
    enterprise_uuid,
    course_run_key,
    email_chunk,
    results_file,
    environment='local',
    fetch_jwt=False,
    sleep_interval=DEFAULT_SLEEP_INTERVAL,
):
    """
    Given a "chunk" list emails for which enrollments should be requested, checks if the given
    email has already been processed.  If not, adds it to a list for this
    chunk to be requested, then requests bulk license enrollment in the given enterprise.
    On successful request, appends results including chunk_id, job_id, and email to results_file.
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
        results_for_chunk = request_enrollments(
            chunk_id, enterprise_uuid, course_run_key, payload_for_chunk, environment, fetch_jwt,
        )
        with open(results_file, 'a+') as f_out:
            writer = csv.writer(f_out, delimiter=',')
            writer.writerows(results_for_chunk)
        if sleep_interval:
            print(f'Sleeping for {sleep_interval} seconds.')
            time.sleep(sleep_interval)
    else:
        print(
            'No enrollments need to be created for chunk_id',
            chunk_id,
            'with size',
            len(email_chunk),
            'and course_run_key',
            course_run_key,
        )


@click.command()
@click.option(
    '--input-file',
    help='Path of local CSV file containing at least the following header columns: email, course_run.',
)
@click.option(
    '--enterprise-uuid',
    help='Enterprise customer for which there are available subscription licenses to use to create the enrollments.',
)
@click.option(
    '--output-file',
    default=None,
    help='headerless CSV file of emails that we have processed.',
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
def run(input_file, enterprise_uuid, output_file, chunk_size, environment, sleep_interval, fetch_jwt):
    """
    Entry-point for this script.
    """
    for chunk_id, course_run_key, email_chunk in get_email_chunks(input_file, chunk_size):
        do_enrollment_for_chunk(
            chunk_id, enterprise_uuid, course_run_key, email_chunk,
            output_file, environment, fetch_jwt, sleep_interval,
        )


if __name__ == '__main__':
    run()
