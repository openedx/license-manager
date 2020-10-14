
from unittest import mock
from uuid import uuid4

import ddt
from django.test import TestCase

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions import constants
from license_manager.test_utils import MockResponse


@ddt.ddt
class EnterpriseApiClientTests(TestCase):
    """
    Tests for the enterprise api client.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.uuid = uuid4()
        cls.user_email = 'test@example.com'
        cls.user_id = 3
        cls.content_ids = ['demoX', 'testX']

    @mock.patch('license_manager.apps.api_client.enterprise.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api_client.base_oauth.OAuthAPIClient', return_value=mock.MagicMock())
    def test_create_pending_enterprise_user_logs(self, mock_oauth_client, mock_logger):
        """
        Verify the ``create_pending_enterprise_user`` method logs an error for a status code of >=400.
        """
        # Mock out the response from the lms
        mock_oauth_client().post.return_value = MockResponse({'detail': 'Bad Request'}, 400)

        EnterpriseApiClient().create_pending_enterprise_user(self.uuid, self.user_email)
        mock_logger.error.assert_called_once()

    @mock.patch('license_manager.apps.api_client.base_oauth.OAuthAPIClient', return_value=mock.MagicMock())
    def test_create_pending_enterprise_user_rate_limited(self, mock_oauth_client):
        """
        Verify the ``create_pending_enterprise_user`` method retries on a 429 response code.
        """
        rate_limited_response = MockResponse({'detail': 'Rate limited'}, 429)
        # Mock out a few rate-limited response and one good from the lms
        mock_oauth_client().post.side_effect = [
            rate_limited_response,
            rate_limited_response,
            rate_limited_response,
            MockResponse({'detail': 'Good Request'}, 201),
        ]

        EnterpriseApiClient().create_pending_enterprise_user(self.uuid, self.user_email)
        assert mock_oauth_client().post.call_count == 4

    @mock.patch('license_manager.apps.api_client.enterprise.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api_client.base_oauth.OAuthAPIClient', return_value=mock.MagicMock())
    def test_revoke_course_enrollments_for_user_with_error(self, mock_oauth_client, mock_logger):
        """
        Verify the ``update_course_enrollment_mode_for_user`` method logs an error for a status code of >=400.
        """
        # Mock out the response from the lms
        mock_oauth_client().post.return_value = MockResponse({'detail': 'Bad Request'}, 400)
        mock_oauth_client().post.return_value.content = 'error response'

        EnterpriseApiClient().revoke_course_enrollments_for_user(
            user_id=self.user_id,
            enterprise_id=self.uuid,
        )
        mock_logger.error.assert_called_once()
