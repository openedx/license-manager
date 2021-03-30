import logging
from urllib.parse import urljoin

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
    pending_enterprise_learner_endpoint = api_base_url + 'pending-enterprise-learner/'
    course_enrollments_revoke_endpoint = api_base_url + 'licensed-enterprise-course-enrollment/license_revoke/'
    bulk_licensed_enrollments_expiration_endpoint = api_base_url \
        + 'licensed-enterprise-course-enrollment/bulk_licensed_enrollments_expiration/'

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

    def get_enterprise_sender_alias(self, enterprise_customer_uuid):
        """
        Gets the sender alias for the enterprise associated with a customer.

        Arguments:
            enterprise_customer_uuid (UUID): UUID of the enterprise customer associated with an enterprise

        Returns:
            string: The sender alias for the enterprise, if sender alias for the enterprise is None or not present
                then the default alias `edX Support Team` is returned.
        """
        endpoint = urljoin(self.enterprise_customer_endpoint, str(enterprise_customer_uuid)) + '/'
        response = self.client.get(endpoint).json()
        return response.get('sender_alias', None) or 'edX Support Team'

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
                'enterprise_customer': enterprise_customer_uuid,
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

    def bulk_licensed_enrollments_expiration(self, expired_license_uuids):
        """
        Calls the Enterprise API Client to terminate expired course enrollments for the provided license uuids

        Arguments:
            expired_license_uuids (list of str): The UUIDs of the expired licenses
        """
        data = {
            'expired_license_uuids': expired_license_uuids,
        }
        response = self.client.post(self.bulk_licensed_enrollments_expiration_endpoint, json=data)
        if response.status_code >= 400:
            msg = (
                'Failed to terminate expired course enrollments for licenses [{expired_license_uuids}]. '
                'Response: {response}'.format(
                    expired_license_uuids=expired_license_uuids,
                    response=response.content,
                )
            )
            logger.error(msg)

    def bulk_enroll_enterprise_learners(self, enterprise_id, options):
        """
        Calls the Enterprise Bulk Enrollment API to enroll learners in courses.
        """
        enrollment_url = '{}{}/enroll_learners_in_courses/'.format(self.enterprise_customer_endpoint, enterprise_id)
        return self.client.post(enrollment_url, json=options)
