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


def _now():
    return datetime.utcnow().timestamp()


def _later(**timedelta_kwargs):
    defaults = {'hours': 1}
    later = datetime.utcnow() + timedelta(**timedelta_kwargs or defaults)
    return later.timestamp()


class Cache:
    def __init__(self):
        self._data = {}
        self._expiry = {}

    def get(self, key):
        value = self._data.get(key)
        if not value:
            return None

        expiry = self._expiry.get(key)
        if expiry and (_now() > expiry):
            self.evict(key)
            return None

        return value
            
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


CACHE = Cache()

def _get_jwt():
    if CACHE.get('jwt'):
        return CACHE.get('jwt')

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
    jwt = response.json().get('access_token')
    CACHE.set('jwt', jwt, _later(hours=1))
    return jwt


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


def main():
    _load_cache()
    _get_jwt()
    _dump_cache()


if __name__ == '__main__':
    main()
