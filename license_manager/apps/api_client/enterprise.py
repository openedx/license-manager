import logging

from django.conf import settings

from license_manager.apps.api_client.base_oauth import BaseOAuthClient


logger = logging.getLogger(__name__)


class EnterpriseApiClient(BaseOAuthClient):
    """
    API client for calls to the enterprise service.
    """
    api_base_url = settings.LMS_URL + '/enterprise/api/v1/'
    enterprise_customer_endpoint = api_base_url + 'enterprise-customer/'
    pending_enterprise_learner_endpoint = api_base_url + 'pending-enterprise-learner/'

    def get_enterprise_slug(self, enterprise_customer_uuid):
        """
        Gets the enterprise slug for the enterprise associated with a customer.

        Arguments:
            enterprise_customer_uuid (UUID): UUID of the enterprise customer associated with an enterprise

        Returns:
            string: The enterprise_slug for the enterprise
        """
        endpoint = self.enterprise_customer_endpoint + str(enterprise_customer_uuid) + '/'
        response = self.client.get(endpoint).json()
        return response.get('slug', None)

    def create_pending_enterprise_user(self, enterprise_customer_uuid, user_email):
        """
        Creates a pending enterprise user for the specified user and enterprise.

        Arguments:
            enterprise_customer_uuid (UUID): UUID of the enterprise customer associated with an enterprise
            user_email (str): The email to create the pending enterprise user entry for.
        """
        data = {
            'enterprise_customer': enterprise_customer_uuid,
            'user_email': user_email,
        }
        response = self.client.post(self.pending_enterprise_learner_endpoint, data=data)
        if response.status_code >= 400:
            msg = (
                'Failed to create a pending enterprise user for enterprise with uuid: {uuid}. '
                'Response: {response}'.format(uuid=enterprise_customer_uuid, response=response.json())
            )
            logger.error(msg)
