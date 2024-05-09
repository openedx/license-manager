"""
Tests for the utils.py module.
"""
import base64
import hashlib
import hmac
import uuid
from unittest import TestCase, mock

import ddt

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


@ddt.ddt
class TestBatchCounts(TestCase):
    """
    Tests for batch_counts().
    """

    @ddt.data(
        {
            'total_count': 0,
            'batch_size': 5,
            'expected_batch_counts': [],
        },
        {
            'total_count': 4,
            'batch_size': 5,
            'expected_batch_counts': [4],
        },
        {
            'total_count': 5,
            'batch_size': 5,
            'expected_batch_counts': [5],
        },
        {
            'total_count': 6,
            'batch_size': 5,
            'expected_batch_counts': [5, 1],
        },
        {
            'total_count': 23,
            'batch_size': 5,
            'expected_batch_counts': [5, 5, 5, 5, 3],
        },
        # Just make sure something weird doesn't happen when the batch size is 1.
        {
            'total_count': 5,
            'batch_size': 1,
            'expected_batch_counts': [1, 1, 1, 1, 1],
        },
    )
    @ddt.unpack
    def test_batch_counts(self, total_count, batch_size, expected_batch_counts):
        """
        Test batch_counts().
        """
        actual_batch_counts = list(utils.batch_counts(total_count, batch_size=batch_size))
        assert actual_batch_counts == expected_batch_counts
