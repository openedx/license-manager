import logging

from django.conf import settings
from edx_rest_api_client.client import OAuthAPIClient


logger = logging.getLogger(__name__)


class EnterpriseCatalogApiClient:
    """
    API client for calls to the enterprise catalog service.
    """
    api_base_url = settings.ENTERPRISE_CATALOG_URL + '/api/v1/'
    enterprise_catalog_endpoint = api_base_url + 'enterprise-catalogs/'

    def __init__(self):
        self.client = OAuthAPIClient(
            settings.SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT.strip('/'),
            self.oauth2_client_id,
            self.oauth2_client_secret
        )

    @property
    def oauth2_client_id(self):
        return settings.BACKEND_SERVICE_EDX_OAUTH2_KEY

    @property
    def oauth2_client_secret(self):
        return settings.BACKEND_SERVICE_EDX_OAUTH2_SECRET

    def contains_content_items(self, catalog_uuid, content_ids):
        """
        Checks whether the specified enterprise catalog contains the given content.

        Arguments:
            catalog_uuid (UUID): UUID of the enterprise catalog to check.
            content_ids (list of str): List of content ids to check whether the catalog contains. The endpoint does not
                differentiate between course_run_ids and program_uuids so they can be used interchangeably. The two
                query parameters are left in for backwards compatability with edx-enterprise.

        Returns:
            bool: Whether the given content_ids were found in the specified enterprise catalog.
        """
        query_params = {'course_run_ids': content_ids}
        endpoint = self.enterprise_catalog_endpoint + str(catalog_uuid) + '/contains_content_items/'
        response = self.client.get(endpoint, params=query_params).json()
        return response.get('contains_content_items', False)
