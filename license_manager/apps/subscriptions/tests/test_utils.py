"""
Tests for the utils.py module.
"""
import base64
import hashlib
import hmac
import uuid
from unittest import mock

from license_manager.apps.subscriptions import utils


def test_get_subsidy_checksum():
    lms_user_id = 123
    course_key = 'demoX'
    license_uuid = uuid.uuid4()

    with mock.patch(
        'license_manager.apps.subscriptions.utils.settings.ENTERPRISE_SUBSIDY_CHECKSUM_SECRET_KEY',
        'foo',
    ):
        message = f'{lms_user_id}:{course_key}:{license_uuid}'
        expected_checksum = base64.b64encode(
            hmac.digest(b'foo', message.encode(), hashlib.sha256),
        ).decode()

        assert hmac.compare_digest(
            expected_checksum,
            utils.get_subsidy_checksum(lms_user_id, course_key, license_uuid),
        )
