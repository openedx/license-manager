from unittest import mock
from uuid import uuid4

import ddt
from django.test import TestCase

from license_manager.apps.api_client.enterprise_catalog import (
    EnterpriseCatalogApiClient,
)


@ddt.ddt
class EnterpriseCatalogApiClientTests(TestCase):
    """
    Tests for the enterprise catalog api client.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.uuid = uuid4()
        cls.content_ids = ['demoX', 'testX']

    @mock.patch('license_manager.apps.api_client.base_oauth.OAuthAPIClient', return_value=mock.MagicMock())
    def test_contains_content_items_defaults_false(self, mock_oauth_client):
        """
        Verify the `contains_content_items` method returns False if the response does not contain the expected key.
        """
        # Mock out the response from the enterprise catalog service
        mock_oauth_client().get.return_value.json.return_value = {'0': 'Bad response'}
        client = EnterpriseCatalogApiClient()
        assert client.contains_content_items(self.uuid, self.content_ids) is False

    @mock.patch('license_manager.apps.api_client.base_oauth.OAuthAPIClient', return_value=mock.MagicMock())
    @ddt.data(True, False)
    def test_contains_content_items(self, contains_content, mock_oauth_client):
        """
        Verify the `contains_content_items` method returns the value given by the response.
        """
        # Mock out the response from the enterprise catalog service
        mock_oauth_client().get.return_value.json.return_value = {'contains_content_items': contains_content}
        client = EnterpriseCatalogApiClient()
        assert client.contains_content_items(self.uuid, self.content_ids) is contains_content
