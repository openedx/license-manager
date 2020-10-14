import logging

import backoff
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
    course_enrollments_revoke_endpoint = api_base_url + 'licensed-enterprise-course-enrollment/license_revoke/'

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

    def get_enterprise_name(self, enterprise_customer_uuid):
        """
        Gets the enterprise name for the enterprise associated with a customer.

        Arguments:
            enterprise_customer_uuid (UUID): UUID of the enterprise customer associated with an enterprise

        Returns:
            string: The enterprise_name for the enterprise
        """
        endpoint = self.enterprise_customer_endpoint + str(enterprise_customer_uuid) + '/'
        response = self.client.get(endpoint).json()
        return response.get('name', None)

    @backoff.on_predicate(
        # Use an exponential backoff algorithm
        backoff.expo,
        # Backoff when a status code of 429 is returned, indicating rate limiting
        lambda status_code: status_code == 429,
        # Back off for a maximum of 120 seconds (2 minutes) before giving up. This might need to be adjusted
        max_time=120,
    )
    def create_pending_enterprise_user(self, enterprise_customer_uuid, user_email):
        """
        Creates a pending enterprise user for the specified user and enterprise.

        Arguments:
            enterprise_customer_uuid (UUID): UUID of the enterprise customer associated with an enterprise
            user_email (str): The email to create the pending enterprise user entry for.
        Returns:
            int: The status code returned by the POST request to create the pending enterprise user. This is only used
                for the purpose of backing off of requests for rate limiting.
        """
        data = {
            'enterprise_customer': enterprise_customer_uuid,
            'user_email': user_email,
        }
        response = self.client.post(self.pending_enterprise_learner_endpoint, data=data)
        if response.status_code == 429:
            msg = (
                'Rate limited when trying to create a pending enterprise user for enterprise with uuid: {uuid}. '
                'Response: {response}. '
                'Backing off and trying request again shortly'.format(
                    uuid=enterprise_customer_uuid,
                    response=response.json(),
                )
            )
            logger.error(msg)
        elif response.status_code >= 400:
            msg = (
                'Failed to create a pending enterprise user for enterprise with uuid: {uuid}. '
                'Response: {response}'.format(uuid=enterprise_customer_uuid, response=response.json())
            )
            logger.error(msg)

        return response.status_code

    def revoke_course_enrollments_for_user(self, user_id, enterprise_id):
        """
        Calls the Enterprise API Client to revoke the user's enterprise licensed course enrollments

        Arguments:
            user_id (str): The ID of the user who had an enterprise license revoked
            enterprise_id (str): The ID of the enterprise to revoke course enrollments for
        """
        data = {
            'user_id': user_id,
            'enterprise_id': enterprise_id,
        }
        response = self.client.post(self.course_enrollments_revoke_endpoint, json=data)
        if response.status_code >= 400:
            msg = (
                'Failed to revoke course enrollments for user "{user_id}" and enterprise "{enterprise_id}". '
                'Response: {response}'.format(
                    user_id=user_id,
                    enterprise_id=enterprise_id,
                    response=response.content,
                )
            )
            logger.error(msg)
