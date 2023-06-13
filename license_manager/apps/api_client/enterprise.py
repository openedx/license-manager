import logging

import requests
from django.conf import settings

from license_manager.apps.api_client.base_oauth import BaseOAuthClient


logger = logging.getLogger(__name__)


class EnterpriseApiClient(BaseOAuthClient):
    """
    API client for calls to the enterprise service.
    """
    api_base_url = settings.LMS_URL + '/enterprise/api/v1/'
    enterprise_customer_endpoint = api_base_url + 'enterprise-customer/'
    enterprise_learner_endpoint = api_base_url + 'enterprise-learner/'
    pending_enterprise_learner_endpoint = api_base_url + 'pending-enterprise-learner/'
    course_enrollments_revoke_endpoint = api_base_url + 'licensed-enterprise-course-enrollment/license_revoke/'
    bulk_licensed_enrollments_expiration_endpoint = api_base_url \
        + 'licensed-enterprise-course-enrollment/bulk_licensed_enrollments_expiration/'

    def get_enterprise_customer_data(self, enterprise_customer_uuid):
        """
        Gets the data for an EnterpriseCustomer with a given UUID.

        Arguments:
            enterprise_customer_uuid (UUID): UUID of the enterprise customer associated with an enterprise
        Returns:
            response (dict): JSON response data
        """
        endpoint = '{}{}/'.format(self.enterprise_customer_endpoint, str(enterprise_customer_uuid))
        try:
            response = self.client.get(endpoint)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            logger.error(
                'Failed to fetch enterprise customer data for %r because %r',
                enterprise_customer_uuid,
                response.text,
            )
            raise exc

    def get_enterprise_admin_users(self, enterprise_customer_uuid):
        """
        Gets a list of admin users for a given enterprise customer.

        Arguments:
            enterprise_customer_uuid (UUID): UUID of the enterprise customer associated with an enterprise
        Returns:
            A list of dicts in the form of
                {
                    'id': str,
                    'username': str,
                    'first_name': str,
                    'last_name': str,
                    'email': str,
                    'is_staff': bool,
                    'is_active': bool,
                    'date_joined': str,
                    'ecu_id': str,
                    'created': str
                }
        """

        query_params = f'?enterprise_customer_uuid={str(enterprise_customer_uuid)}&role=enterprise_admin'

        try:
            url = self.enterprise_learner_endpoint + query_params
            results = []

            while url:
                response = self.client.get(url)
                response.raise_for_status()
                resp_json = response.json()
                url = resp_json['next']

                for result in resp_json['results']:
                    user_data = result['user']
                    user_data.update(ecu_id=result['id'], created=result['created'])
                    results.append(user_data)

            return results
        except requests.exceptions.HTTPError as exc:
            logger.error(
                'Failed to fetch enterprise admin users for %r because %r',
                enterprise_customer_uuid,
                response.text,
            )
            raise exc

    def create_pending_enterprise_users(self, enterprise_customer_uuid, user_emails):
        """
        Creates a pending enterprise user in the given ``enterprise_customer_uuid`` for each of the
        specified ``user_emails`` provided.

        Arguments:
            enterprise_customer_uuid (UUID): UUID of the enterprise customer in which pending user records are created.
            user_emails (list(str)): The emails for which pending enterprise users will be created.
        Returns:
            Response: A ``requests.Response`` object.
        Raises:
            ``requests.exceptions.HTTPError`` on any response with an unsuccessful status code.
        """
        data = [
            {
                'enterprise_customer': str(enterprise_customer_uuid),
                'user_email': user_email,
            }
            for user_email in user_emails
        ]
        response = self.client.post(self.pending_enterprise_learner_endpoint, json=data)
        try:
            response.raise_for_status()
            logger.info(
                'Successfully created %r PendingEnterpriseCustomerUser records for customer %r',
                len(data),
                enterprise_customer_uuid,
            )
            return response
        except requests.exceptions.HTTPError as exc:
            logger.error(
                'Failed to create %r PendingEnterpriseCustomerUser records for customer %r because %r',
                len(data),
                enterprise_customer_uuid,
                response.text,
            )
            raise exc

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

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            msg = (
                'Failed to revoke course enrollments for user "{user_id}" and enterprise "{enterprise_id}". '
                'Response: {response}'.format(
                    user_id=user_id,
                    enterprise_id=enterprise_id,
                    response=response.content,
                )
            )
            logger.error(msg)
            raise exc

    def bulk_licensed_enrollments_expiration(self, expired_license_uuids, ignore_enrollments_modified_after=None):
        """
        Calls the Enterprise API Client to terminate expired course enrollments for the provided license uuids

        Arguments:
            expired_license_uuids (list of str): The UUIDs of the expired licenses
        """
        data = {
            'expired_license_uuids': expired_license_uuids,
            'ignore_enrollments_modified_after': ignore_enrollments_modified_after
        }
        response = self.client.post(self.bulk_licensed_enrollments_expiration_endpoint, json=data)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            msg = (
                'Failed to terminate expired course enrollments for licenses [{expired_license_uuids}]. '
                'Response: {response}'.format(
                    expired_license_uuids=expired_license_uuids,
                    response=response.content,
                )
            )
            logger.error(msg)
            raise exc

    def bulk_enroll_enterprise_learners(self, enterprise_id, options):
        """
        Calls the Enterprise Bulk Enrollment API to enroll learners in courses.
        """
        enrollment_url = '{}{}/enroll_learners_in_courses/'.format(self.enterprise_customer_endpoint, enterprise_id)
        return self.client.post(enrollment_url, json=options, timeout=settings.BULK_ENROLL_REQUEST_TIMEOUT_SECONDS)
