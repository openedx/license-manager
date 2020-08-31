"""
Script for load-testing the license-manager service

requirements you must pip install these before using: requests
"""

from collections import defaultdict
from datetime import datetime, timedelta
from multiprocessing import Pool
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
LICENSE_MANAGER_BASE_URL = os.environ.get('LICENSE_MANAGER_BASE_URL', 'http://localhost:18734')

LEARNER_NAME_TEMPLATE = 'Subscription Learner {}'
LEARNER_USERNAME_TEMPLATE = 'subsc-learner-{}'
LEARNER_EMAIL_TEMPLATE = '{}@example.com'.format(LEARNER_USERNAME_TEMPLATE)
LEARNER_PASSWORD_TEMPLATE = 'random-password-{}'


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

    def registered_users(self):
        return self.get(self.Keys.REGISTERED_USERS, dict())

    def add_registered_user(self, user_data):
        users = self.registered_users()
        users[user_data['email']] = user_data
        self.set(self.Keys.REGISTERED_USERS, users)

    def set_jwt_for_email(self, email, jwt):
        key = self.Keys.USER_JWT_TEMPLATE.format(email)
        self.set(key, jwt, expiry=_later())


CACHE = Cache()

def _get_jwt():
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


def _make_request(url, *args, delay_seconds=0.1):
    headers = {
        "Authorization": "JWT {}".format(_get_jwt),
    }
    start = time.time()
    response = requests.get(
        url.format(*args),
        headers=_headers(),
    )
    elapsed = time.time() - start

    if response.status_code != 200:
        print(response.status_code)
        print(response.content)
        raise Exception('Got non-200 status_code')

    time.sleep(delay_seconds)

    return response.content, elapsed


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


def main():
    _load_cache()

    # Run this to generate 10 new users
    # register_users(n=10)

    # Run this to verify that we have retained their data and can log
    # each of them in.
    # _login_session('verified@example.com', 'edx')
    for user_email, user_data in CACHE.registered_users().items():
        password = user_data['password']
        _login_session(user_email, password)

    _dump_cache()


if __name__ == '__main__':
    main()
