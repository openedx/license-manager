"""
Tests for the LicenseActivationView.
"""
import datetime
from unittest import mock
from uuid import uuid4

import ddt
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient

from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import License
from license_manager.apps.subscriptions.tests.factories import (
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.utils import localized_utcnow

from .test_views import LicenseViewTestMixin, _assign_role_via_jwt_or_db


@ddt.ddt
class LicenseActivationViewTests(LicenseViewTestMixin, TestCase):
    """
    Tests for the license activation view.
    """

    def tearDown(self):
        """
        Deletes all licenses after each test method is run.
        """
        super().tearDown()

        License.objects.all().delete()

    def _post_request(self, activation_key):
        """
        Helper to make the POST request to the license activation endpoint.

        Will update the test client's cookies to contain an lms_user_id and email,
        which can be overridden from those defined in the class ``setUpTestData()``
        method with the optional params provided here.
        """
        query_params = QueryDict(mutable=True)
        query_params['activation_key'] = str(activation_key)
        url = reverse('api:v1:license-activation') + '/?' + query_params.urlencode()
        return self.api_client.post(url)

    def test_activation_no_auth(self):
        """
        Unauthenticated requests should result in a 401.
        """
        # Create a new client with no authentication present.
        self.api_client = APIClient()

        response = self._post_request(uuid4())

        assert status.HTTP_401_UNAUTHORIZED == response.status_code

    def test_activation_no_jwt_roles(self):
        """
        JWT Authenticated requests without the appropriate learner role should result in a 403.
        """
        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            self.enterprise_customer_uuid,
            assign_via_jwt=True,
            system_role=None,
        )
        self._create_license()

        response = self._post_request(self.activation_key)

        assert status.HTTP_403_FORBIDDEN == response.status_code

    @mock.patch('license_manager.apps.api.v1.views.utils.get_decoded_jwt')
    def test_activation_no_jwt(self, mock_get_decoded_jwt):
        """
        Verify that license activation returns a 400 if the user's email could not be found in the JWT.
        """
        mock_get_decoded_jwt.return_value = {}
        response = self._post_request(str(self.activation_key))

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert '`email` is required and could not be found in your jwt' in str(response.content)

    def test_activation_key_is_malformed(self):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
                'subscription_plan_type': self.active_subscription_for_customer.product.plan_type_id,
            }
        )

        response = self._post_request('deadbeef')

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert 'deadbeef is not a valid activation key' in str(response.content)

    def test_activation_key_does_not_exist(self):
        """
        When the user is authenticated and has the appropriate role,
        but no corresponding license exists for the given ``activation_key``,
        we should return a 404.
        """
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
                'subscription_plan_type': self.active_subscription_for_customer.product.plan_type_id,
            }
        )

        response = self._post_request(uuid4())

        assert status.HTTP_404_NOT_FOUND == response.status_code

    @ddt.data(
        {'disable_onboarding_notifications': False},
        {'disable_onboarding_notifications': True}
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.v1.views.send_post_activation_email_task.delay')
    def test_activate_an_assigned_license(self, mock_send_post_activation_email_task, disable_onboarding_notifications):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
                'subscription_uuid': str(self.active_subscription_for_customer.uuid),
            }
        )
        license_to_be_activated = self._create_license()

        if disable_onboarding_notifications:
            customer_agreement = license_to_be_activated.subscription_plan.customer_agreement
            customer_agreement.disable_onboarding_notifications = True
            customer_agreement.save()

        with freeze_time(self.now):
            response = self._post_request(str(self.activation_key))

        assert status.HTTP_204_NO_CONTENT == response.status_code
        license_to_be_activated.refresh_from_db()
        assert constants.ACTIVATED == license_to_be_activated.status
        assert self.lms_user_id == license_to_be_activated.lms_user_id
        assert self.now == license_to_be_activated.activation_date

        if disable_onboarding_notifications:
            mock_send_post_activation_email_task.assert_not_called()
        else:
            mock_send_post_activation_email_task.assert_called_with(
                self.enterprise_customer_uuid,
                self.user.email,
            )

    def test_license_already_activated_returns_204(self):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
                'subscription_plan_type': self.active_subscription_for_customer.product.plan_type_id,
            }
        )
        already_activated_license = self._create_license(
            status=constants.ACTIVATED,
            activation_date=self.now,
        )

        response = self._post_request(str(self.activation_key))

        assert status.HTTP_204_NO_CONTENT == response.status_code
        already_activated_license.refresh_from_db()
        assert constants.ACTIVATED == already_activated_license.status
        assert self.lms_user_id == already_activated_license.lms_user_id
        assert self.now == already_activated_license.activation_date

    # pylint: disable=unused-argument
    @mock.patch('license_manager.apps.api.v1.views.send_post_activation_email_task.delay')
    @mock.patch('license_manager.apps.subscriptions.models.License.clean', return_value=None)
    def test_duplicate_licenses_are_cleaned_up(self, mock_license_clean, mock_email_task_delay):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
                'subscription_plan_type': self.active_subscription_for_customer.product.plan_type_id,
            }
        )
        # Make sure to use an activation key that's different from the
        # activation_key of the license  we want to keep.
        revoked_license = self._create_license(
            status=constants.REVOKED,
            assigned_date=self.now,
            activation_key=uuid4(),
        )
        license_a = self._create_license(
            status=constants.ASSIGNED,
            assigned_date=self.now - datetime.timedelta(days=1),
            activation_key=uuid4(),
        )
        license_b = self._create_license(
            status=constants.ASSIGNED,
            assigned_date=self.now,
            activation_key=self.activation_key,
        )
        license_c = self._create_license(
            status=constants.ASSIGNED,
            assigned_date=self.now - datetime.timedelta(days=2),
            activation_key=uuid4(),
        )

        with freeze_time(self.now):
            response = self._post_request(str(self.activation_key))

        assert status.HTTP_204_NO_CONTENT == response.status_code

        license_b.refresh_from_db()
        assert constants.ACTIVATED == license_b.status
        assert self.lms_user_id == license_b.lms_user_id
        assert self.now == license_b.activation_date
        assert self.now == license_b.assigned_date
        assert self.activation_key == license_b.activation_key

        license_a.refresh_from_db()
        assert constants.UNASSIGNED == license_a.status
        self.assertIsNone(license_a.lms_user_id)
        self.assertIsNone(license_a.activation_key)

        license_c.refresh_from_db()
        assert constants.UNASSIGNED == license_c.status
        self.assertIsNone(license_c.lms_user_id)
        self.assertIsNone(license_c.activation_key)

        revoked_license.refresh_from_db()
        assert constants.REVOKED == revoked_license.status

    # pylint: disable=unused-argument
    @mock.patch('license_manager.apps.api.v1.views.send_post_activation_email_task.delay')
    @mock.patch('license_manager.apps.subscriptions.models.License.clean', return_value=None)
    def test_activated_license_exists_with_duplicates(self, mock_license_clean, mock_email_task_delay):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
                'subscription_plan_type': self.active_subscription_for_customer.product.plan_type_id,
            }
        )
        # Make sure to use an activation key that's different from the
        # activation_key of the license  we want to keep.
        license_a_activation_key = uuid4()
        license_a = self._create_license(
            status=constants.ASSIGNED,
            assigned_date=self.now - datetime.timedelta(days=1),
            activation_key=license_a_activation_key,
        )
        license_b = self._create_license(
            status=constants.ACTIVATED,
            assigned_date=self.now,
            activation_date=self.now,
            activation_key=self.activation_key,
        )

        with freeze_time(self.now):
            response = self._post_request(str(license_a_activation_key))

        assert status.HTTP_204_NO_CONTENT == response.status_code

        license_b.refresh_from_db()
        assert constants.ACTIVATED == license_b.status
        assert self.lms_user_id == license_b.lms_user_id
        assert self.now == license_b.activation_date
        assert self.now == license_b.assigned_date
        assert self.activation_key == license_b.activation_key

        license_a.refresh_from_db()
        assert constants.UNASSIGNED == license_a.status
        self.assertIsNone(license_a.lms_user_id)
        self.assertIsNone(license_a.activation_key)
        self.assertIsNone(license_a.activation_date)

    def test_activating_revoked_license_returns_422(self):
        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
                'subscription_plan_type': self.active_subscription_for_customer.product.plan_type_id,
            }
        )
        revoked_license = self._create_license(
            status=constants.REVOKED,
            activation_date=self.now,
        )

        response = self._post_request(str(self.activation_key))

        assert status.HTTP_422_UNPROCESSABLE_ENTITY == response.status_code
        revoked_license.refresh_from_db()
        assert constants.REVOKED == revoked_license.status
        assert self.lms_user_id == revoked_license.lms_user_id
        assert self.now == revoked_license.activation_date

    @mock.patch('license_manager.apps.api.v1.views.send_post_activation_email_task.delay')
    def test_activating_renewed_assigned_license(self, mock_send_post_activation_email_task):
        yesterday = localized_utcnow() - datetime.timedelta(days=1)
        # create an expired plan and a current plan
        subscription_plan_original = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            start_date=localized_utcnow() - datetime.timedelta(days=366),
            expiration_date=yesterday,
        )
        subscription_plan_renewed = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
            product=subscription_plan_original.product
        )

        self._assign_learner_roles(
            jwt_payload_extra={
                'user_id': self.lms_user_id,
                'email': self.user.email,
                'subscription_plan_type': subscription_plan_original.product.plan_type_id,
            }
        )

        prior_assigned_license = self._create_license(
            subscription_plan=subscription_plan_original,
            # explicitly set activation_date to assert that this license
            # is *not* the one that gets activated during the POST request.
            activation_date=yesterday,
        )
        current_assigned_license = self._create_license(subscription_plan=subscription_plan_renewed)

        with freeze_time(self.now):
            response = self._post_request(str(self.activation_key))

        assert status.HTTP_204_NO_CONTENT == response.status_code
        current_assigned_license.refresh_from_db()
        prior_assigned_license.refresh_from_db()
        assert prior_assigned_license.activation_date != self.now
        assert current_assigned_license.activation_date == self.now
        mock_send_post_activation_email_task.assert_called_with(
            self.enterprise_customer_uuid,
            self.user.email,
        )
