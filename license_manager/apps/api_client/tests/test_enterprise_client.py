from uuid import uuid4

import ddt
import mock
from django.test import TestCase

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
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
        cls.content_ids = ['demoX', 'testX']

    @mock.patch('license_manager.apps.api_client.enterprise.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api_client.enterprise.OAuthAPIClient', return_value=mock.MagicMock())
    def test_create_pending_enterprise_user_logs(self, mock_oauth_client, mock_logger):
        """
        Verify the ``create_pending_enterprise_user`` method logs an error for a status code of >=400.
        """
        # Mock out the response from the lms
        mock_oauth_client().post.return_value = MockResponse({'detail': 'Bad Request'}, 400)

        EnterpriseApiClient().create_pending_enterprise_user(self.uuid, self.user_email)
        mock_logger.error.assert_called_once()
