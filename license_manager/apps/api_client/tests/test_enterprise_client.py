
from unittest import mock
from uuid import uuid4

import ddt
import requests
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
        cls.user_id = 3
        cls.content_ids = ['demoX', 'testX']

    @mock.patch('license_manager.apps.api_client.base_oauth.OAuthAPIClient', return_value=mock.MagicMock())
    def test_create_pending_enterprise_users_successful(self, mock_oauth_client):
        """
        Verify the ``create_pending_enterprise_users`` method does not raise an exception for successful requests.
        """
        # Mock out the response from the lms
        mock_oauth_client.return_value.post.return_value = MockResponse(
            {'detail': 'Good Request'},
            201,
        )

        user_emails = [
            'larry@stooges.com',
            'moe@stooges.com',
            'curly@stooges.com',
        ]
        enterprise_client = EnterpriseApiClient()
        response = enterprise_client.create_pending_enterprise_users(self.uuid, user_emails)
        mock_oauth_client.return_value.post.assert_called_once_with(
            enterprise_client.pending_enterprise_learner_endpoint,
            json=[
                {'enterprise_customer': self.uuid, 'user_email': user_email}
                for user_email in user_emails
            ],
        )
        assert response.status_code == 201

    @mock.patch('license_manager.apps.api_client.base_oauth.OAuthAPIClient', return_value=mock.MagicMock())
    def test_create_pending_enterprise_users_http_error(self, mock_oauth_client):
        """
        Verify the ``create_pending_enterprise_users`` method does not raise an exception for successful requests.
        """
        # Mock out the response from the lms
        mock_oauth_client.return_value.post.return_value = MockResponse(
            {'detail': 'Bad Request'},
            400,
            content=b'error response',
        )

        user_emails = [
            'larry@stooges.com',
            'moe@stooges.com',
            'curly@stooges.com',
        ]
        enterprise_client = EnterpriseApiClient()
        with self.assertRaises(requests.exceptions.HTTPError):
            response = enterprise_client.create_pending_enterprise_users(self.uuid, user_emails)
            mock_oauth_client.return_value.post.assert_called_once_with(
                enterprise_client.pending_enterprise_learner_endpoint,
                json=[
                    {'enterprise_customer': self.uuid, 'user_email': user_email}
                    for user_email in user_emails
                ],
            )
            assert response.status_code == 400
            assert response.content == 'error response'

    @mock.patch('license_manager.apps.api_client.enterprise.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api_client.base_oauth.OAuthAPIClient', return_value=mock.MagicMock())
    def test_revoke_course_enrollments_for_user_with_error(self, mock_oauth_client, mock_logger):
        """
        Verify the ``update_course_enrollment_mode_for_user`` method logs an error for a status code of >=400.
        """
        # Mock out the response from the lms
        mock_oauth_client().post.return_value = MockResponse({'detail': 'Bad Request'}, 400, content='error response')

        with self.assertRaises(requests.exceptions.HTTPError):
            EnterpriseApiClient().revoke_course_enrollments_for_user(
                user_id=self.user_id,
                enterprise_id=self.uuid,
            )
            mock_logger.error.assert_called_once()
