import logging

import requests
from django.conf import settings

from license_manager.apps.api_client.base_oauth import BaseOAuthClient


logger = logging.getLogger(__name__)


class LMSApiClient(BaseOAuthClient):
    """
    API client for calls to the LMS.
    """
    api_base_url = settings.LMS_URL
    user_details_endpoint = api_base_url + '/api/user/v1/accounts'

    def fetch_lms_user_id(self, email):
        """
        Fetch user details for the specified user email.

        Arguments:
            email (str): Email of the user for which we want to fetch details for.

        Returns:
            str: lms_user_id of the user.
        """
        # {base_api_url}/api/user/v1/accounts?email=edx@example.com
        try:
            query_params = {'email': email}
            response = self.client.get(self.user_details_endpoint, params=query_params)
            response.raise_for_status()
            response_json = response.json()
            return response_json[0].get('id')
        except requests.exceptions.HTTPError as exc:
            logger.error(
                'Failed to fetch user details for user {email} because {reason}'.format(
                    email=email,
                    reason=str(exc),
                )
            )
            raise exc
