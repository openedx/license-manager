# pylint: disable=redefined-outer-name
"""
Tests for the Subscription and License V1 API view sets.
"""
from datetime import date
from uuid import uuid4

import mock
import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get as get_model_fixture
from rest_framework import status
from rest_framework.test import APIClient

from license_manager.apps.core.models import User
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.tests.factories import (
    USER_PASSWORD,
    LicenseFactory,
    SubscriptionPlanFactory,
    UserFactory,
)


@pytest.fixture
def api_client():
    """
    Fixture that provides a DRF test APIClient.
    """
    return APIClient()


@pytest.fixture
def non_staff_user():
    """
    Fixture that provides a plain 'ole authenticated User instance.
    Non-staff, non-admin.
    """
    return get_model_fixture(User)


@pytest.fixture
def staff_user():
    """
    Fixture that provides a User instance for whom staff=True.
    """
    return get_model_fixture(User, is_staff=True, is_superuser=False)


@pytest.fixture
def superuser():
    """
    Fixture that provides a superuser.
    """
    return get_model_fixture(User, is_staff=True, is_superuser=True)


def _subscriptions_list_request(api_client, user, enterprise_customer_uuid=None):
    """
    Helper method that requests a list of subscriptions entities for a given enterprise_customer_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:subscriptions-list')
    if enterprise_customer_uuid is not None:
        url += '?enterprise_customer_uuid={uuid}'.format(uuid=enterprise_customer_uuid)
    return api_client.get(url)


def _subscriptions_detail_request(api_client, user, subscription_uuid):
    """
    Helper method that requests details for a specific subscription_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:subscriptions-detail', kwargs={'subscription_uuid': subscription_uuid})
    return api_client.get(url)


def _licenses_list_request(api_client, user, subscription_uuid):
    """
    Helper method that requests a list of licenses for a given subscription_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:licenses-list', kwargs={'subscription_uuid': subscription_uuid})
    return api_client.get(url)


def _licenses_detail_request(api_client, user, subscription_uuid, license_uuid):
    """
    Helper method that requests details for a specific license_uuid.
    """
    api_client.force_authenticate(user=user)
    url = reverse('api:v1:licenses-detail', kwargs={
        'subscription_uuid': subscription_uuid,
        'license_uuid': license_uuid
    })
    return api_client.get(url)


def _get_date_string(date):
    """
    Helper to get the string associated with a date, or None if it doesn't exist.

    Returns:
        string or None: The string representation of the date if it exists.
    """
    if not date:
        return None
    return str(date)


def _assert_subscription_response_correct(response, subscription):
    """
    Helper for asserting that the response for a subscription matches the object's values.
    """
    assert response['enterprise_customer_uuid'] == str(subscription.enterprise_customer_uuid)
    assert response['uuid'] == str(subscription.uuid)
    assert response['purchase_date'] == _get_date_string(subscription.purchase_date)
    assert response['start_date'] == _get_date_string(subscription.start_date)
    assert response['expiration_date'] == _get_date_string(subscription.expiration_date)
    assert response['enterprise_catalog_uuid'] == str(subscription.enterprise_catalog_uuid)
    assert response['is_active'] == subscription.is_active
    assert response['licenses'] == {
        'total': subscription.num_licenses,
        'allocated': subscription.num_allocated_licenses,
    }


def _assert_license_response_correct(response, subscription_license):
    """
    Helper for asserting that the response for a subscription_license matches the object's values.
    """
    assert response['uuid'] == str(subscription_license.uuid)
    assert response['status'] == subscription_license.status
    assert response['user_email'] == subscription_license.user_email
    assert response['activation_date'] == _get_date_string(subscription_license.activation_date)
    assert response['last_remind_date'] == _get_date_string(subscription_license.last_remind_date)


@pytest.mark.django_db
def test_subscription_plan_list_unauthenticated_user_403(api_client):
    """
    Verify that unauthenticated users receive a 403 from the subscription plan list endpoint.
    """
    response = _subscriptions_list_request(api_client, AnonymousUser(), enterprise_customer_uuid=uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_retrieve_unauthenticated_user_403(api_client):
    """
    Verify that unauthenticated users receive a 403 from the subscription plan retrieve endpoint.
    """
    response = _subscriptions_detail_request(api_client, AnonymousUser(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_license_list_unauthenticated_user_403(api_client):
    """
    Verify that unauthenticated users receive a 403 from the license list endpoint.
    """
    response = _licenses_list_request(api_client, AnonymousUser(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_license_retrieve_unauthenticated_user_403(api_client):
    """
    Verify that unauthenticated users receive a 403 from the license retrieve endpoint.
    """
    response = _licenses_detail_request(api_client, AnonymousUser(), uuid4(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_list_non_staff_user_403(api_client, non_staff_user):
    response = _subscriptions_list_request(api_client, non_staff_user, enterprise_customer_uuid='foo')
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_detail_non_staff_user_403(api_client, non_staff_user):
    response = _subscriptions_detail_request(api_client, non_staff_user, uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_licenses_list_non_staff_user_403(api_client, non_staff_user):
    response = _licenses_list_request(api_client, non_staff_user, uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_license_detail_non_staff_user_403(api_client, non_staff_user):
    response = _licenses_detail_request(api_client, non_staff_user, uuid4(), uuid4())
    assert status.HTTP_403_FORBIDDEN == response.status_code


@pytest.mark.django_db
def test_subscription_plan_list_staff_user_200(api_client, staff_user):
    """
    Verify that the subscription list view for staff users gives the correct response.

    Additionally checks that the staff user only sees the subscription plans associated with the enterprise customer as
    specified by the query parameter.
    """
    enterprise_customer_uuid = uuid4()
    first_subscription = SubscriptionPlanFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    # Associate some unassigned and assigned licenses to the first subscription
    unassigned_licenses = LicenseFactory.create_batch(5)
    assigned_licenses = LicenseFactory.create_batch(2, status=constants.ASSIGNED)
    first_subscription.licenses.set(unassigned_licenses + assigned_licenses)
    # Create one more subscription for the enterprise with no licenses
    second_subscription = SubscriptionPlanFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    # Create another subscription not associated with the enterprise that shouldn't show up
    SubscriptionPlanFactory.create()

    response = _subscriptions_list_request(api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 2
    _assert_subscription_response_correct(results[0], first_subscription)
    _assert_subscription_response_correct(results[1], second_subscription)


@pytest.mark.django_db
def test_subscription_plan_list_staff_user_no_query_param(api_client, staff_user):
    """
    Verify that the subscription list view for staff gives no results if there is no query param.
    """
    SubscriptionPlanFactory.create()
    response = _subscriptions_list_request(api_client, staff_user)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 0


@pytest.mark.django_db
def test_subscription_plan_list_superuser_200(api_client, superuser):
    """
    Verify that the subscription list view for superusers returns all subscription plans.
    """
    SubscriptionPlanFactory.create_batch(10)
    response = _subscriptions_list_request(api_client, superuser)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 10


@pytest.mark.django_db
def test_subscription_plan_detail_staff_user_200(api_client, staff_user):
    """
    Verify that the subscription detail view for staff gives the correct result.
    """
    subscription = SubscriptionPlanFactory.create()
    # Associate some licenses with the subscription
    unassigned_licenses = LicenseFactory.create_batch(3)
    assigned_licenses = LicenseFactory.create_batch(5, status=constants.ASSIGNED)
    subscription.licenses.set(unassigned_licenses + assigned_licenses)
    response = _subscriptions_detail_request(api_client, staff_user, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_subscription_response_correct(response.data, subscription)


@pytest.mark.django_db
def test_license_list_staff_user_200(api_client, staff_user):
    subscription = SubscriptionPlanFactory.create()
    # Associate some licenses with the subscription
    unassigned_license = LicenseFactory.create()
    assigned_license = LicenseFactory.create(status=constants.ASSIGNED, user_email='fake@fake.com')
    subscription.licenses.set([unassigned_license, assigned_license])
    response = _licenses_list_request(api_client, staff_user, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    results = response.data['results']
    assert len(results) == 2
    _assert_license_response_correct(results[0], unassigned_license)
    _assert_license_response_correct(results[1], assigned_license)


@pytest.mark.django_db
def test_license_detail_staff_user_200(api_client, staff_user):
    subscription = SubscriptionPlanFactory.create()
    # Associate some licenses with the subscription
    subscription_license = LicenseFactory.create()
    subscription.licenses.set([subscription_license])
    response = _licenses_detail_request(api_client, staff_user, subscription.uuid, subscription_license.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_license_response_correct(response.data, subscription_license)


class LicenseViewSetActionTests(TestCase):
    """
    Tests for special actions on the LicenseViewSet.
    """
    def setUp(self):
        super().setUp()

        # API client setup
        self.api_client = APIClient()
        self.user = UserFactory(is_staff=True, is_superuser=True)
        self.api_client.login(username=self.user.username, password=USER_PASSWORD)

        # Routes setup
        self.subscription_plan = SubscriptionPlanFactory()
        self.remind_url = reverse('api:v1:licenses-remind', kwargs={'subscription_uuid': self.subscription_plan.uuid})
        self.remind_all_url = reverse(
            'api:v1:licenses-remind-all',
            kwargs={'subscription_uuid': self.subscription_plan.uuid},
        )

    def _assert_last_remind_date_correct(self, licenses, should_be_updated):
        """
        Helper that verifies that all of the given licenses have had their last_remind_date updated if applicable.

        If they should not have been updated, then it checks that last_remind_date is still None.
        """
        for license_obj in licenses:
            license_obj.refresh_from_db()
            if should_be_updated:
                assert license_obj.last_remind_date.date() == date.today()
            else:
                assert license_obj.last_remind_date is None

    @mock.patch('license_manager.apps.subscriptions.emails.send_reminder_emails')
    def test_remind_no_email(self, mock_send_reminder_emails):
        """
        Verify that the remind endpoint returns a 400 if no email is provided.
        """
        response = self.api_client.post(self.remind_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails.assert_not_called()

    @mock.patch('license_manager.apps.subscriptions.emails.send_reminder_emails')
    def test_remind_invalid_email(self, mock_send_reminder_emails):
        """
        Verify that the remind endpoint returns a 400 if an invalid email is provided.
        """
        response = self.api_client.post(self.remind_url, {'user_email': 'lkajsf'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails.assert_not_called()

    @mock.patch('license_manager.apps.subscriptions.emails.send_reminder_emails')
    def test_remind_blank_email(self, mock_send_reminder_emails):
        """
        Verify that the remind endpoint returns a 400 if an empty string is submitted for an email.
        """
        response = self.api_client.post(self.remind_url, {'user_email': ''})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails.assert_not_called()

    @mock.patch('license_manager.apps.subscriptions.emails.send_reminder_emails')
    def test_remind_no_license_for_user(self, mock_send_reminder_emails):
        """
        Verify that the remind endpoint returns a 404 if there is no license associated with the given email.
        """
        response = self.api_client.post(self.remind_url, {'user_email': 'nolicense@example.com'})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_send_reminder_emails.assert_not_called()

    @mock.patch('license_manager.apps.subscriptions.emails.send_reminder_emails')
    def test_remind_no_pending_license_for_user(self, mock_send_reminder_emails):
        """
        Verify that the remind endpoint returns a 404 if there is no pending license associated with the given email.
        """
        email = 'test@example.com'
        activated_license = LicenseFactory.create(user_email=email, status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([activated_license])

        response = self.api_client.post(self.remind_url, {'user_email': email})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        self._assert_last_remind_date_correct([activated_license], False)
        mock_send_reminder_emails.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind(self, mock_send_reminder_emails):
        """
        Verify that the remind endpoint sends an email to the specified user with a pending license.

        Also verifies that:
            - A custom greeting and closing can be sent to the endpoint
            - The license's `last_remind_date` is updated to reflect that an email was just sent out
        """
        email = 'test@example.com'
        pending_license = LicenseFactory.create(user_email=email, status=constants.ASSIGNED)
        assert pending_license.last_remind_date is None  # The learner should not have been reminded yet
        self.subscription_plan.licenses.set([pending_license])

        greeting = 'Hello'
        closing = 'Goodbye'
        response = self.api_client.post(
            self.remind_url,
            {'user_email': email, 'greeting': greeting, 'closing': closing},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_send_reminder_emails.assert_called_with(
            {'greeting': greeting, 'closing': closing},
            [email],
            str(self.subscription_plan.uuid),
        )
        self._assert_last_remind_date_correct([pending_license], True)

    @mock.patch('license_manager.apps.subscriptions.emails.send_reminder_emails')
    def test_remind_all_no_pending_licenses(self, mock_send_reminder_emails):
        """
        Verify that the remind all endpoint returns a 404 if there are no pending licenses.
        """
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        self.subscription_plan.licenses.set(unassigned_licenses)

        response = self.api_client.post(self.remind_all_url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        self._assert_last_remind_date_correct(unassigned_licenses, False)
        mock_send_reminder_emails.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_all(self, mock_send_reminder_emails):
        """
        Verify that the remind all endpoint sends an email to each user with a pending license.

        Also verifies that:
            - A custom greeting and closing can be sent to the endpoint.
            - The licenses' `last_remind_date` fields are updated to reflect that an email was just sent out.
        """
        # Create some pending and non-pending licenses for the subscription
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        pending_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set(unassigned_licenses + pending_licenses)

        greeting = 'Hello'
        closing = 'Goodbye'
        response = self.api_client.post(self.remind_all_url, {'greeting': greeting, 'closing': closing})
        assert response.status_code == status.HTTP_200_OK

        # Verify that the unassigned licenses did not have `last_remind_date` updated, but the pending licenses did
        self._assert_last_remind_date_correct(unassigned_licenses, False)
        self._assert_last_remind_date_correct(pending_licenses, True)

        # Verify emails sent to only the pending licenses
        mock_send_reminder_emails.assert_called_with(
            {'greeting': greeting, 'closing': closing},
            [license.user_email for license in pending_licenses],
            str(self.subscription_plan.uuid),
        )
