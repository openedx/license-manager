"""
Script for load-testing the license-manager service

requirements you must pip install these before using: requests
"""

from collections import defaultdict
from datetime import datetime, timedelta
from multiprocessing import Pool
from contextlib import contextmanager
import json
import os
from pprint import pprint
import random
import sys
import time
import uuid

import requests

# The local defaults should all "just work" against devstack.

# used to fetch a JWT for the license_manager_worker
OAUTH2_CLIENT_ID = os.environ.get('OAUTH2_CLIENT_ID', 'license_manager-backend-service-key')
OAUTH2_CLIENT_SECRET = os.environ.get('OAUTH2_CLIENT_SECRET', 'license_manager-backend-service-secret')

# where to get a JWT, can change the env var to set this to the stage environment
LMS_BASE_URL = os.environ.get('LMS_BASE_URL', 'http://localhost:18000')
ACCESS_TOKEN_ENDPOINT = LMS_BASE_URL + '/oauth2/access_token/'

# the license-manager root URL, you can change the env var to set this to stage
LICENSE_MANAGER_BASE_URL = os.environ.get('LICENSE_MANAGER_BASE_URL', 'http://localhost:18170')

LEARNER_NAME_TEMPLATE = 'Subscription Learner {}'
LEARNER_USERNAME_TEMPLATE = 'subsc-learner-{}'
LEARNER_EMAIL_TEMPLATE = '{}@example.com'.format(LEARNER_USERNAME_TEMPLATE)
LEARNER_PASSWORD_TEMPLATE = 'random-password-{}'

SUBSCRIPTION_PLAN_UUID = '068e4d94-6d98-40fa-a674-99a1175c64ae'


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

    def set_license_for_email(self, email_address, license_data):
        users = self.registered_users()
        if email_address not in users:
            return
        user_data = users[email_address]
        user_data['license'] = license_data


CACHE = Cache()


def _dump_cache():
    with open('loadtest-cache.json', 'w') as file_out:
        file_out.write(json.dumps(CACHE.to_dict()))


def _load_cache():
    global CACHE
    try:
        with open('loadtest-cache.json', 'r') as file_in:
            json_data = json.loads(file_in.read())
            CACHE = Cache.from_dict(json_data)
    except FileNotFoundError:
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
    jwt_header = response.cookies.get('edx-jwt-cookie-header-payload')
    jwt_signature = response.cookies.get('edx-jwt-cookie-signature')
    jwt = jwt_header + '.' + jwt_signature
    CACHE.add_registered_user(user_data)
    CACHE.set_jwt_for_email(user_data['email'], jwt)
    return jwt


def _register_user(**kwargs):
    url = LMS_BASE_URL + '/user_api/v2/account/registration/'
    user_data = _random_user_data()
    response = requests.post(url, data=user_data)
    if response.status_code == 200:
        print('Successfully created new account for {}'.format(user_data['email']))
        jwt = _get_jwt_from_response_and_add_to_cache(response, user_data)
        return response, jwt
    return response, None


def register_users(n=1):
    for _ in range(n):
        _register_user()


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
    Makes an authenticated request to a given URL,
    returning the response content and the elapsed time.
    Will use the admin Authorization token by default.
    """
    headers = {
        "Authorization": "JWT {}".format(jwt or _get_admin_jwt()),
    }
    start = time.time()
    response = request_method(
        url,
        headers=headers,
        **kwargs
    )
    elapsed = time.time() - start

    if delay_seconds:
        time.sleep(delay_seconds)

    return response, elapsed


def fetch_all_subscription_plans(*args, **kwargs):
    """
    Fetch data on all subscription plans and cache it.
    """
    def _process_results(data):
        for subscription in data:
            print('Updating subscription plan {} ({}) in cache.'.format(subscription['uuid'], subscription['title']))
            CACHE.add_subscription_plan(subscription)

    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/'

    while url:
        response, _ = _make_request(url)
        response_data = response.json()
        _process_results(response_data['results'])
        url = response_data['next']


def fetch_one_subscription_plan(plan_uuid, user_email=None, fetch_as_learner=True):
    import pdb; pdb.set_trace()
    if fetch_as_learner:
        subscription_data = CACHE.subscription_plans().get(plan_uuid, {})
        enterprise_customer_uuid = subscription_data.get('enterprise_customer_uuid')
        url = LICENSE_MANAGER_BASE_URL + '/api/v1/learner-subscriptions/?enterprise_customer_uuid={}'.format(enterprise_customer_uuid)
    else:
        url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/'.format(plan_uuid)

    if not user_email:
        jwt = _get_admin_jwt()
    else:
        jwt = _get_learner_jwt(user_email)

    response, _ = _make_request(url, jwt=jwt)
    return response.json()


def assign_licenses(plan_uuid, user_emails):
    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/assign/'.format(plan_uuid)
    data = {
        'user_emails': user_emails,
    }
    # It's important to use json=data here, and not data=data
    # "Using the json parameter in the request will change the Content-Type in the header to application/json."
    # https://requests.readthedocs.io/en/master/user/quickstart/#more-complicated-post-requests
    response, elapsed = _make_request(url, json=data, request_method=requests.post)
    return response.json()


def fetch_licenses(plan_uuid, status=None):
    """
    Fetch all licenses for a given subscription plan.  Optionally filter by a license status.
    Will associate licenses with cached users as appropriate.
    """
    def _process_results(data):
        for license_data in data:
            user_email = license_data.pop('user_email')
            if user_email:
                CACHE.set_license_for_email(user_email, license_data)

    url = LICENSE_MANAGER_BASE_URL + '/api/v1/subscriptions/{}/licenses/'.format(plan_uuid)
    if status:
        url += '?status={}'.format(status)

    while url:
        response, _ = _make_request(url)
        response_data = response.json()
        _process_results(response_data['results'])
        url = response_data['next']


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

    # get a new JWT for the user, this is important because
    # the activation endpoint matches the JWT email against the assigned license
    _login_session(user_email, user_data['password'])

    url = LICENSE_MANAGER_BASE_URL + '/api/v1/license-activation?activation_key={}'.format(activation_key)
    response, _ = _make_request(
        url,
        request_method=requests.post,
        jwt=CACHE.get_jwt_for_email(user_email),
    )
    if response.status_code >= 400:
        print('Error activating license: {}'.format(response))
    else:
        license_data['status'] = 'activated'
        print('License successfully activated for {}'.format(user_email))
    return response

def main():
    with _load_cache_and_dump_when_done():
        # Forces us to always fetch a fresh JWT for the worker/admin user.
        CACHE.clear_current_request_jwt()

        _prereqs()


## Functions to test that things work ##

def _prereqs():
    # Have subscription plan and set KELLIE_SUBSCRIPTION_PLAN_UUID to its UUID
    _test_register() # register 10 users and cache their details
    _test_assign_and_activate_licenses() # assign and activate licenses for all 10


def _learner_subscription_requests():
    pass
    # TODO
    # Use this, once for each learner:
    # fetch_one_subscription_plan(
    #     SUBSCRIPTION_PLAN_UUID,
    #     user_email='subsc-learner-3a8e@example.com',
    # )

    # record the response times

    # get an average of the response times and spit it out.


def _test_register():
    """
    Run this to generate 10 new users.
    """
    register_users(n=10)


def _test_login():
    """
    Run this to verify that we have retained data when registering users
    and can log each of them in.
    """
    for user_email, user_data in CACHE.registered_users().items():
        password = user_data['password']
        _login_session(user_email, password)


def test_fetch_subscription_plans():
    fetch_all_subscription_plans()


def _test_assign_licenses(num_to_assign=1):
    plan_uuid = SUBSCRIPTION_PLAN_UUID
    user_emails = list(CACHE.registered_users().keys())[:num_to_assign]
    assign_licenses(plan_uuid, user_emails)


def _test_activate_licenses():
    for user_email, user_data in CACHE.registered_users().items():
        if user_data.get('license'):
            activate_license(user_email)


def _test_assign_and_activate_licenses():
    # As an admin, assign some licenses to users we have cached data about.
    _test_assign_licenses(num_to_assign=10)

    # As an admin, list all of the assigned licenses, and then associate
    # license data with the user to whom the license belongs.
    fetch_licenses(SUBSCRIPTION_PLAN_UUID, status='assigned')

    # Once we have license activation keys associated with users,
    # we can make a call for each user with a license to the activation endpoint.
    _test_activate_licenses()


## End all testing functions ###


if __name__ == '__main__':
    main()