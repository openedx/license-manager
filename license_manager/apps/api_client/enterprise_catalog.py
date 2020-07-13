from license_manager.apps.api_client.base_oauth import BaseOAuthClient


class EnterpriseCatalogApiClient(BaseOAuthClient):
    """
    API client for calls to the enterprise catalog service.
    """
    enterprise_catalog_endpoint = BaseOAuthClient.api_base_url + 'enterprise-catalogs/'

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
