"""
Script for load-testing the license-manager service

requirements you must pip install these before using: requests

To source env variables, consider `source scripts/loadtest.env.development`.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from multiprocessing import Pool
from contextlib import contextmanager
from statistics import mean
import argparse
import json
import os
from pprint import pprint
import random
import sys
import time
import uuid
import numpy as np

import requests

# The local defaults should all "just work" against devstack.

CACHE_FILENAME = os.environ.get('CACHE_FILENAME', 'loadtest-cache.json')

# Used to fetch a JWT for the license_manager_worker
# Use the Client ID and Client Secret for license-manager-worker to stay within the throttle limit
OAUTH2_CLIENT_ID = os.environ.get('OAUTH2_CLIENT_ID', 'license_manager-backend-service-key')
OAUTH2_CLIENT_SECRET = os.environ.get('OAUTH2_CLIENT_SECRET', 'license_manager-backend-service-secret')

# Where to get a JWT, can change the env var to set this to the stage environment
LMS_BASE_URL = os.environ.get('LMS_BASE_URL', 'http://localhost:18000')
ACCESS_TOKEN_ENDPOINT = LMS_BASE_URL + '/oauth2/access_token/'

# The license-manager root URL, you can change the env var to set this to stage
LICENSE_MANAGER_BASE_URL = os.environ.get('LICENSE_MANAGER_BASE_URL', 'http://localhost:18170')

LEARNER_NAME_TEMPLATE = 'Subscription Learner {}'
LEARNER_USERNAME_TEMPLATE = 'subscription-learner-{}'
LEARNER_EMAIL_TEMPLATE = '{}@example.com'.format(LEARNER_USERNAME_TEMPLATE)
# Passwords need to have a number in them, the 1 guarantees that
LEARNER_PASSWORD_TEMPLATE = 'random-password-1-{}'

# Arguments to limit which test cases get run
parser = argparse.ArgumentParser(description='Specify loadtest arguments.')
parser.add_argument('-c', '--clearcache', action='store_true', default=True, help='Whether to run the script with a cleaned cache, default is true')
parser.add_argument('--admin', action='store_true', default=True, help='Whether to run the admin only endpoints, default is true')
parser.add_argument('--learner', action='store_true', default=True, help='Whether to run the learner only endpoints, default is true')
args = parser.parse_args()

# How many users will be assigned licenses in this run
NUM_USERS = 1000
# If using a large number of users and wish to reduce the number of requests that get made update this value
NETWORK_REQUEST_CAP = 100
# The uuid subscription plan being load tested
SUBSCRIPTION_PLAN_UUID = '7bb88bfe-51ab-4bf4-8945-9f1e2ae8a30b'
# Optionally can set what the enterprise customer uuid is here too
ENTERPRISE_UUID = ''

ASSIGN_EMAILS = []
GENERATED_USERS = {}
LICENSE_UUIDS = []
METRICS = []


def _now():
    return datetime.utcnow().timestamp()


def _later(**timedelta_kwargs):
    defaults = {'hours': 1}
    later = datetime.utcnow() + timedelta(**timedelta_kwargs or defaults)
    return later.timestamp()


def _random_hex_string(a=0, b=1e6):
    """
    Return a random hex string, default range between 0 and 1 million.
    """
    return hex(random.randint(a, b)).lstrip('0x')


def _random_password(**kwargs):
    return LEARNER_PASSWORD_TEMPLATE.format(_random_hex_string(**kwargs))


def _random_user_data():
    hex_str = _random_hex_string()
    return {
        'email': LEARNER_EMAIL_TEMPLATE.format(hex_str),
        'name': LEARNER_NAME_TEMPLATE.format(hex_str),
        'username': LEARNER_USERNAME_TEMPLATE.format(hex_str),
        'password': _random_password(),
        'country': 'US',
        'honor_code': 'true',
    }


class Cache:
    class Keys:
        REQUEST_JWT = '__request_jwt'
        REGISTERED_USERS = '__registered_users'
        USER_JWT_TEMPLATE = '__jwt_for_user_{}'
        ALL_SUBSCRIPTION_PLANS = '__subscription_plans'

    def __init__(self):
        self._data = {}
        self._expiry = {}

    def get(self, key, default=None):
        value = self._data.get(key)
        if not value:
            return None or default

        expiry = self._expiry.get(key)
        if expiry and (_now() > expiry):
            self.evict(key)
            return None or default

        return value or default

    def set(self, key, value, expiry=None):
        self._data[key] = value
        self._expiry[key] = expiry

    def evict(self, key):
        self._data.pop(key, None)
        self._expiry.pop(key, None)

    def to_dict(self):
        return {
            '_data': self._data,
            '_expiry': self._expiry,
        }

    @classmethod
    def from_dict(cls, _dict):
        instance = cls()
        instance._data = _dict['_data']
        instance._expiry = _dict['_expiry']
        return instance

    def current_request_jwt(self):
        return self.get(self.Keys.REQUEST_JWT)

    def set_current_request_jwt(self, jwt):
        self.set(self.Keys.REQUEST_JWT, jwt, expiry=_later())

    def clear_current_request_jwt(self):
        self.evict(self.Keys.REQUEST_JWT)

    def registered_users(self):
        return self.get(self.Keys.REGISTERED_USERS, dict())

    def add_registered_user(self, user_data):
        users = self.registered_users()
        if user_data['email'] not in users:
            users[user_data['email']] = user_data
        self.set(self.Keys.REGISTERED_USERS, users)

    def set_jwt_for_email(self, email, jwt):
        key = self.Keys.USER_JWT_TEMPLATE.format(email)
        self.set(key, jwt, expiry=_later())

    def get_jwt_for_email(self, email):
        key = self.Keys.USER_JWT_TEMPLATE.format(email)
        return self.get(key)

    def subscription_plans(self):
        return self.get(self.Keys.ALL_SUBSCRIPTION_PLANS, dict())

    def add_subscription_plan(self, subsc_data):
        all_plans = self.subscription_plans()
        all_plans[subsc_data['uuid']] = subsc_data
        self.set(self.Keys.ALL_SUBSCRIPTION_PLANS, all_plans)

    def set_license_for_email(self, email_address, license_data):
        users = self.registered_users()
        if email_address not in users:
            return
        user_data = users[email_address]
        user_data['license'] = license_data
        users[email_address] = user_data
        self.set(self.Keys.REGISTERED_USERS, users)

    def get_license_uuids(self):
        users = self.registered_users()
        license_uuids = []
        for user_data in users.values():
            license_data = user_data.get('license', {})
            if license_data:
                license_uuids.append(license_data.get('uuid'))
        return license_uuids

    @property
    def license_uuids_by_status(self):
        license_data_by_status = defaultdict(dict)
        for email, user_data in self.registered_users().items():
            license_data = user_data.get('license', {})
            status = license_data.get('status', 'unassigned')
            license_data_by_status[status][email] = license_data
        return license_data_by_status

    def print_user_license_data(self):
        print('Currently cached user count by status:')
        pprint({
            status: len(user_license_data)
            for status, user_license_data
            in self.license_uuids_by_status.items()
        })


CACHE = Cache()


class Metric:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.values = []
        self.failure_count = 0

    def print_metrics(self):
        pprint('{}:'.format(self.endpoint))
        if self.values:
            pprint('Average time: {} ms'.format(round(mean(self.values), 3) * 1000))
            pprint('Max time: {} ms'.format(round(max(self.values), 3) * 1000))
            pprint('Min time: {} ms'.format(round(min(self.values), 3) * 1000))
            pprint('95th Percentile: {} ms'.format(round(np.percentile(self.values, 95), 3) * 1000))
            pprint('90th Percentile: {} ms'.format(round(np.percentile(self.values, 90), 3) * 1000))
        pprint('Number of errors: ' + str(self.failure_count))
        pprint('Failure Percentage: {}%'.format((self.failure_count / (len(self.values) + self.failure_count)) * 100))


def _dump_cache():
    with open(CACHE_FILENAME, 'w') as file_out:
        file_out.write(json.dumps(CACHE.to_dict()))


def _load_cache():
    global CACHE
    try:
        with open(CACHE_FILENAME, 'r') as file_in:
            json_data = json.loads(file_in.read())
            CACHE = Cache.from_dict(json_data)
    except:
        CACHE = Cache()

    # for the sake of convenience, try to get the cached request JWT
    # so that it's evicted if already expired
    CACHE.current_request_jwt()


@contextmanager
def _load_cache_and_dump_when_done():
    try:
        _load_cache()
        yield
    finally:
        _dump_cache()


def _get_admin_jwt():
    if CACHE.current_request_jwt():
        return CACHE.current_request_jwt()

    payload = {
        'client_id': OAUTH2_CLIENT_ID,
        'client_secret': OAUTH2_CLIENT_SECRET,
        'grant_type': 'client_credentials',
        'token_type': 'jwt',
    }
    response = requests.post(
        ACCESS_TOKEN_ENDPOINT,
        data=payload,
    )
    jwt_token = response.json().get('access_token')
    CACHE.set_current_request_jwt(jwt_token)
    return jwt_token


def _get_jwt_from_response_and_add_to_cache(response, user_data=None):
    # The cookie name is prefixed with "stage" in the staging environment
    prefix = ''
    if 'stage' in CACHE_FILENAME.lower():
        prefix = 'stage-'

    jwt_header = response.cookies.get(prefix + 'edx-jwt-cookie-header-payload')
    jwt_signature = response.cookies.get(prefix + 'edx-jwt-cookie-signature')
    jwt = jwt_header + '.' + jwt_signature
    CACHE.add_registered_user(user_data)
    CACHE.set_jwt_for_email(user_data['email'], jwt)
    return jwt


def _register_user(user_data, **kwargs):
    url = LMS_BASE_URL + '/user_api/v2/account/registration/'
    response = requests.post(url, data=user_data)
    if response.status_code == 200:
        print('Successfully created new account for {}'.format(user_data['email']))
        jwt = _get_jwt_from_response_and_add_to_cache(response, user_data)
        return response, jwt
    else:
        print('Failed to create new account for {}!'.format(user_data['email']))
        raise


def _create_pending_enterprise_user(email, enterprise_uuid):
    url = LMS_BASE_URL + '/enterprise/api/v1/pending-enterprise-learner/'
    data = {
        'enterprise_customer': enterprise_uuid,
        'user_email': email,
    }
    response = _make_request(url, data=data, request_method=requests.post)
    if response.status_code >= 400:
        import pdb; pdb.set_trace()
        raise


def _get_learner_jwt(email):
    jwt = CACHE.get_jwt_for_email(email)
    if not jwt:
        password = CACHE.registered_users().get(email, {}).get('password')
        if not password:
            print('Cannot get JWT for {}, no password'.format(email))
            return

        # this will actually put a new JWT in the cache for the given email
        _login_session(email, password)
        jwt = CACHE.get_jwt_for_email(email)
    return jwt


def _login_session(email, password):
    request_headers = {
        'use-jwt-cookie': 'true',
        'X-CSRFToken': 'b2m2Szrpqk5mcGxdImCL0nvqq7hTJJWIUQvriT6NnphlNVtEGz0xwaB6JfiXkkNj',
    }
    request_cookies = {
        'csrftoken': 'b2m2Szrpqk5mcGxdImCL0nvqq7hTJJWIUQvriT6NnphlNVtEGz0xwaB6JfiXkkNj',
    }
    user_data = {
        'email': email,
        'password': password,
    }
    url = LMS_BASE_URL + '/user_api/v1/account/login_session/'
    response = requests.post(url, headers=request_headers, cookies=request_cookies, data=user_data)
    if response.status_code == 200:
        print('Successfully logged in {}'.format(user_data['email']))
        jwt = _get_jwt_from_response_and_add_to_cache(response, user_data)
        return response, jwt
    return response, None


def _make_request(url, delay_seconds=None, jwt=None, request_method=requests.get, **kwargs):
    """
    Makes an authenticated request to a given URL
    Will use the admin Authorization token by default.
    """
    headers = {
        "Authorization": "JWT {}".format(jwt or _get_admin_jwt()),
    }
    response = request_method(
        url,
        headers=headers,
        **kwargs
    )

    if delay_seconds:
        time.sleep(delay_seconds)

    return response


def fetch_all_subscription_plans():
    """
    Fetch data on all subscription plans and cache it.
    """
    def _process_results(data):
        for subscription in data:
            print('Updating subscription plan {} ({}) in cache.'.format(subscription['uuid'], subscription['title']))
            if subscription['uuid'] == SUBSCRIPTION_PLAN_UUID and not ENTERPRISE_UUID:
                ENTERPRISE_UUID = subscription['enterprise_customer_uuid']
            CACHE.add_subscription_plan(subscription)

    fetch_all_subscriptions_metric = Metric('Load All Subscriptions {} API call(s)')

    for _ in range(NETWORK_REQUEST_CAP):
        url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/'
        while url:
            start = time.time()
            response = _make_request(url)
            fetch_all_subscriptions_metric.values.append(time.time() - start)
            response_data = response.json()
            if response.status_code < 400:
                _process_results(response_data['results'])
                url = response_data['next']
            else:
                url = None

    num_subscriptions = len(fetch_all_subscriptions_metric.values)
    fetch_all_subscriptions_metric.endpoint = fetch_all_subscriptions_metric.endpoint.format(num_subscriptions)
    METRICS.append(fetch_all_subscriptions_metric)


def fetch_one_subscription_plan(plan_uuid, user_email=None):
    if user_email:
        subscription_data = CACHE.subscription_plans().get(plan_uuid, {})
        enterprise_customer_uuid = subscription_data.get('enterprise_customer_uuid')
        url = LICENSE_MANAGER_BASE_URL + '/api/v1/learner-subscriptions/?enterprise_customer_uuid={}'.format(enterprise_customer_uuid)
    else:
        url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/'.format(plan_uuid)

    if not user_email:
        jwt = _get_admin_jwt()
    else:
        jwt = _get_learner_jwt(user_email)

    response = _make_request(url, jwt=jwt)
    if response.status_code != 200:
        print("Encountered an error while fetching a subscription plan: {}".format(response))
        return response.json(), 1
    return response.json(), 0


def assign_licenses(plan_uuid, user_emails):
    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/assign/'.format(plan_uuid)
    print('Attempting to assign licenses for {} emails...'.format(len(user_emails)))
    data = {
        'user_emails': user_emails,
    }
    # It's important to use json=data here, and not data=data
    # "Using the json parameter in the request will change the Content-Type in the header to application/json."
    # https://requests.readthedocs.io/en/master/user/quickstart/#more-complicated-post-requests
    response = _make_request(url, json=data, request_method=requests.post)
    response_data = response.json()
    print('Result of license assignment: {}\n'.format(response_data))
    if response.status_code > 400:
        return response, 1
    return response_data, 0


def remind(plan_uuid, user_email=None):
    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/remind/'.format(plan_uuid)
    data = {
        'user_email': user_email,
    }
    # It's important to use json=data here, and not data=data
    # "Using the json parameter in the request will change the Content-Type in the header to application/json."
    # https://requests.readthedocs.io/en/master/user/quickstart/#more-complicated-post-requests
    response = _make_request(url, json=data, request_method=requests.post)
    if response.status_code != 200:
        print("Encountered an error while reminding: {}".format(response))
        return response, 1
    return response, 0


def remind_all(plan_uuid):
    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/remind-all/'.format(plan_uuid)
    response = _make_request(url, request_method=requests.post)
    if response.status_code != 200:
        print("Encountered an error while reminding all learners: {}".format(response))
        return response, 1
    return response, 0


def fetch_licenses(plan_uuid, status=None, page_size=100):
    """
    Fetch all licenses for a given subscription plan.  Optionally filter by a license status.
    Will associate licenses with cached users as appropriate.
    """
    def _process_results(data):
        for license_data in data:
            user_email = license_data.pop('user_email')
            if user_email in GENERATED_USERS.keys():
                LICENSE_UUIDS.append(license_data['uuid'])
                GENERATED_USERS[user_email]['license'] = license_data

    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/?page_size={}'.format(plan_uuid, page_size)
    fetch_all_licenses_metric = Metric('Admin fetch all licenses {} API call(s)')
    if status:
        url += '&status={}'.format(status)

    num_loops = 0
    while url:
        start = time.time()
        response = _make_request(url)
        if response.status_code != 200:
            fetch_all_licenses_metric.failure_count = fetch_all_licenses_metric.failure_count + 1
        else:
            fetch_all_licenses_metric.values.append(time.time() - start)
        response_data = response.json()
        _process_results(response_data['results'])
        url = response_data['next']
        num_loops = num_loops + 1

    fetch_all_licenses_metric.endpoint = fetch_all_licenses_metric.endpoint.format(num_loops)
    METRICS.append(fetch_all_licenses_metric)

    # Return how many licenses exist for this subscription (optionally with the given status)
    return response_data['count']


def fetch_individual_licenses(plan_uuid, license_uuids):
    fetch_license_metric = Metric('Fetch Individual Licenses (N={})'.format(len(license_uuids)))
    for x in range(NETWORK_REQUEST_CAP):
        license_uuid = license_uuids[x]
        start = time.time()
        url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/{}/'.format(plan_uuid, license_uuid)
        response = _make_request(url, request_method=requests.get)
        if response.status_code != 200:
            fetch_license_metric.failure_count = fetch_license_metric.failure_count + 1
            print("Encountered an error while fetching an individual license: {}".format(response))
        else:
            fetch_license_metric.values.append(time.time() - start)
    METRICS.append(fetch_license_metric)


def fetch_learner_license(plan_uuid, user_email):
    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/license'.format(plan_uuid)
    response = _make_request(url, jwt=_get_learner_jwt(user_email), request_method=requests.get)
    if response.status_code != 200:
        print("Encountered an error while a learner tried fetching their own license: {}".format(response))
        return response, 1
    return response, 0


def fetch_license_overview(plan_uuid):
    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/overview/'.format(plan_uuid)
    fetch_overview_metric = Metric('Fetch license overview 1 API call')
    response = None
    for _ in range(NETWORK_REQUEST_CAP):
        start = time.time()
        response = _make_request(url, request_method=requests.get)
        if response.status_code != 200:
            print("Encountered an error while fetching the license overview: {}".format(response))
            fetch_overview_metric.failure_count = fetch_overview_metric.failure_count + 1
        else:
            fetch_overview_metric.values.append(time.time() - start)

    METRICS.append(fetch_overview_metric)
    return response


def revoke_license(plan_uuid, user_email):
    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/revoke/'.format(plan_uuid)
    data = {
        'user_email': user_email,
    }
    # It's important to use json=data here, and not data=data
    # "Using the json parameter in the request will change the Content-Type in the header to application/json."
    # https://requests.readthedocs.io/en/master/user/quickstart/#more-complicated-post-requests
    response = _make_request(url, jwt=_get_admin_jwt(), json=data, request_method=requests.post)
    if response.status_code != 204:
        print("Encountered an error while fetching revoking a license: {}".format(response))
        return response, 1
    return response, 0


def activate_license(user_email):
    user_data = CACHE.registered_users().get(user_email)
    if not user_data:
        print('No user record for {}'.format(user_email))

    license_data = user_data.get('license')
    if not license_data:
        print('No license data for user {}'.format(user_email))
        return

    if license_data.get('status') == 'activated':
        print('License for user {} already activated'.format(user_email))
        return

    activation_key = license_data.get('activation_key')
    if not activation_key:
        print('No activation_key for licensed-user {}'.format(user_email))
        return

    url = LICENSE_MANAGER_BASE_URL + '/api/v1/license-activation?activation_key={}'.format(activation_key)
    response = _make_request(
        url,
        request_method=requests.post,
        jwt=CACHE.get_jwt_for_email(user_email),
    )
    if response.status_code >= 400:
        print('Error activating license: {}'.format(response))
        return response, 1
    else:
        license_data['status'] = 'activated'
        print('License successfully activated for {}'.format(user_email))
    return response, 0


def main():
    print('Using cache filename: {}'.format(CACHE_FILENAME))
    with _load_cache_and_dump_when_done():
        if not args.clearcache:
            CACHE.print_user_license_data()

        # Forces us to always fetch a fresh JWT for the worker/admin user.
        CACHE.clear_current_request_jwt()

        for _ in range(NUM_USERS):
            random_user = _random_user_data()
            GENERATED_USERS[random_user['email']] = random_user
            ASSIGN_EMAILS.append(random_user['email'])
            if x % 700 == 0:
                pprint('Sleeping for a minute')
                time.sleep(60)
            _create_pending_enterprise_user(random_user['email'], ENTERPRISE_UUID)

        # Tests for the enterprise admin only license-manager endpoints
        if args.admin:
            _enterprise_subscription_requests()

        # Tests for the learner endpoints
        if args.learner:
            _learner_subscription_requests()

        # Test revoking licenses which is an admin endpoint
        if args.admin:
            _test_revoke_licenses()

        print('***************Results***************')
        for metric in METRICS:
            metric.print_metrics()
            print('*************************************')


# Functions to test that things work
def _enterprise_subscription_requests():
    # As an admin, test assigning licenses to users
    _test_assign_licenses()

    # As an admin, test reminding learners about their licenses
    _test_remind()

    # As an admin, test loading subscriptions
    _test_load_subscriptions()

    # As an admin, test loading licenses
    _test_load_licenses()


def _learner_subscription_requests():
    activate_license_metric = Metric('Learner Activate License (N = {})'.format(NUM_USERS))
    load_subscription_metric = Metric('Learner Load Enterprises Subscriptions (N = {})'.format(NUM_USERS))
    load_license_metric = Metric('Learner Load Own License (N = {})'.format(NUM_USERS))

    # Limit to only doing the first NETWORK_REQUEST_CAP amount of learners to get a baseline for larger datasets
    user_emails = list(GENERATED_USERS.keys())
    users_data = list(GENERATED_USERS.values())
    for x in range(NETWORK_REQUEST_CAP):
        user_email = user_emails[x]
        user_data = users_data[x]

        _register_user(user_data)
        if user_data.get('license'):
            # get a new JWT for the user, this is important because
            # the activation endpoint matches the JWT email against the assigned license
            _login_session(user_email, user_data['password'])

            # As a learner test how long it takes to activate license
            start = time.time()
            response, failure_count = activate_license(user_email)
            if not failure_count:
                activate_license_metric.values.append(time.time() - start)
            activate_license_metric.failure_count = activate_license_metric.failure_count + failure_count

            # As a learner test how long it takes to load my subscription plan info
            start = time.time()
            response, failure_count = fetch_one_subscription_plan(
                SUBSCRIPTION_PLAN_UUID,
                user_email=user_email,
            )
            if not failure_count:
                load_subscription_metric.values.append(time.time() - start)
            load_subscription_metric.failure_count = load_subscription_metric.failure_count + failure_count

            # As a learner test how long it takes to load my license info
            start = time.time()
            response, failure_count = fetch_learner_license(
                SUBSCRIPTION_PLAN_UUID,
                user_email=user_email
            )
            if not failure_count:
                load_license_metric.values.append(time.time() - start)
            load_license_metric.failure_count = load_subscription_metric.failure_count + failure_count

    METRICS.append(activate_license_metric)
    METRICS.append(load_subscription_metric)
    METRICS.append(load_license_metric)


def _test_register():
    """
    Run this to generate NUM_USERS number of new users.
    """
    register_users()


def _test_login():
    """
    Run this to verify that we have retained data when registering users
    and can log each of them in.
    """
    for user_email, user_data in CACHE.registered_users().items():
        password = user_data['password']
        _login_session(user_email, password)


# In order to have more data points for assigning licenses rerun this script as many times as you need data points
# with new subscription UUIDs with all unassigned licenses
def _test_assign_licenses():
    unassigned_emails = list(ASSIGN_EMAILS)
    start = time.time()
    response, failure_count = assign_licenses(SUBSCRIPTION_PLAN_UUID, unassigned_emails)
    assign_metric = Metric('Assign {} Licenses, 1 API call'.format(NUM_USERS))
    if not failure_count:
        assign_metric.values.append(time.time() - start)
    assign_metric.failure_count = failure_count
    METRICS.append(assign_metric)

    # assure that cached user-license data is updated
    fetch_licenses(SUBSCRIPTION_PLAN_UUID, status='assigned')


def _test_remind():
    plan_uuid = SUBSCRIPTION_PLAN_UUID
    # Test reminding users to activate their license
    remind_metric = Metric('Remind Single Users N API calls (N = {})'.format(NETWORK_REQUEST_CAP))
    user_emails = list(GENERATED_USERS.keys())
    for x in range(NETWORK_REQUEST_CAP):
        user_email = user_emails[x]
        start = time.time()
        response, failure_count = remind(plan_uuid=plan_uuid, user_email=user_email)
        remind_metric.values.append(time.time() - start)
        remind_metric.failure_count = remind_metric.failure_count + failure_count

    METRICS.append(remind_metric)

    # Test reminding all users to activate their license
    remind_all_metric = Metric('Remind All - {} Users {} API calls'.format(NUM_USERS, NETWORK_REQUEST_CAP))
    for _ in range(NETWORK_REQUEST_CAP):
        start = time.time()
        response, failure_count = remind_all(plan_uuid=plan_uuid)
        remind_all_metric.values.append(time.time() - start)
        remind_all_metric.failure_count = failure_count
    METRICS.append(remind_all_metric)


def _test_load_subscriptions():
    # Test loading all subscriptions
    fetch_all_subscription_plans()

    # Test loading individual subscription info
    fetch_one_subscription_metric = Metric('Admin Load Single Subscription {}} API calls'.format(NETWORK_REQUEST_CAP))
    for _ in range(NETWORK_REQUEST_CAP):
        start = time.time()
        json_response, failure_count = fetch_one_subscription_plan(SUBSCRIPTION_PLAN_UUID)
        if not failure_count:
            fetch_one_subscription_metric.values.append(time.time() - start)
        fetch_one_subscription_metric.failure_count = failure_count
    METRICS.append(fetch_one_subscription_metric)


def _test_load_licenses():
    # Test fetching all licenses
    fetch_licenses(SUBSCRIPTION_PLAN_UUID)

    # Fetch and cache the licenses in the subscription
    fetch_individual_licenses(SUBSCRIPTION_PLAN_UUID, LICENSE_UUIDS)

    # Test fetching the license overview for the subscription
    fetch_license_overview(SUBSCRIPTION_PLAN_UUID)


def _test_revoke_licenses():
    # Test revoking all licenses
    user_emails = list(GENERATED_USERS.keys())
    revoke_metric = Metric('Admin Revoke Licenses {} API Calls}'.format(NETWORK_REQUEST_CAP))
    for x in range(NETWORK_REQUEST_CAP):
        user_email = user_emails[x]
        start = time.time()
        response, failure_count = revoke_license(SUBSCRIPTION_PLAN_UUID, user_email)
        if not failure_count:
            revoke_metric.values.append(time.time() - start)
        revoke_metric.failure_count = revoke_metric.failure_count + failure_count
    METRICS.append(revoke_metric)


# End all testing functions


if __name__ == '__main__':
    main()
