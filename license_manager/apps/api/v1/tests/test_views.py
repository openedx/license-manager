# pylint: disable=redefined-outer-name
"""
Tests for the Subscription and License V1 API view sets.
"""
from datetime import datetime
from uuid import uuid4

import ddt
import mock
import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get as get_model_fixture
from edx_rest_framework_extensions.auth.jwt.cookies import jwt_cookie_name
from edx_rest_framework_extensions.auth.jwt.tests.utils import (
    generate_jwt_token,
    generate_unversioned_payload,
)
from rest_framework import status
from rest_framework.test import APIClient

from license_manager.apps.core.models import User
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import (
    SubscriptionsFeatureRole,
    SubscriptionsRoleAssignment,
)
from license_manager.apps.subscriptions.tests.factories import (
    USER_PASSWORD,
    LicenseFactory,
    SubscriptionPlanFactory,
    UserFactory,
)


def _jwt_token_from_role_context_pairs(user, role_context_pairs):
    """
    Generates a new JWT token with roles assigned from pairs of (role name, context).
    """
    roles = []
    for role, context in role_context_pairs:
        role_data = '{role}'.format(role=role)
        if context is not None:
            role_data += ':{context}'.format(context=context)
        roles.append(role_data)

    payload = generate_unversioned_payload(user)
    payload.update({'roles': roles})
    return generate_jwt_token(payload)


def set_jwt_cookie(client, user, role_context_pairs=None):
    """
    Set jwt token in cookies
    """
    jwt_token = _jwt_token_from_role_context_pairs(user, role_context_pairs or [])
    client.cookies[jwt_cookie_name()] = jwt_token


@pytest.fixture(params=[True, False])
def boolean_toggle(request):
    """
    Simple fixture that toggles between boolean states.
    Any test that uses this fixture will actually be two tests - one for each boolean value.
    """
    return request.param


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
def test_subscription_plan_list_staff_user_200(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription list view for staff users gives the correct response
    when the staff user is granted implicit permission to access the enterprise customer.

    Additionally checks that the staff user only sees the subscription plans associated with the enterprise customer as
    specified by the query parameter.
    """
    enterprise_customer_uuid = uuid4()
    first_subscription, second_subscription = _create_subscription_plans(enterprise_customer_uuid)
    _assign_role_via_jwt_or_db(api_client, staff_user, enterprise_customer_uuid, boolean_toggle)

    response = _subscriptions_list_request(api_client, staff_user, enterprise_customer_uuid=enterprise_customer_uuid)

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    assert len(results_by_uuid) == 2

    _assert_subscription_response_correct(results_by_uuid[str(first_subscription.uuid)], first_subscription)
    _assert_subscription_response_correct(results_by_uuid[str(second_subscription.uuid)], second_subscription)


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
def test_subscription_plan_detail_staff_user_200(api_client, staff_user, boolean_toggle):
    """
    Verify that the subscription detail view for staff gives the correct result.
    """
    subscription = SubscriptionPlanFactory.create()

    # Associate some licenses with the subscription
    unassigned_licenses = LicenseFactory.create_batch(3)
    assigned_licenses = LicenseFactory.create_batch(5, status=constants.ASSIGNED)
    subscription.licenses.set(unassigned_licenses + assigned_licenses)

    _assign_role_via_jwt_or_db(api_client, staff_user, subscription.enterprise_customer_uuid, boolean_toggle)

    response = _subscriptions_detail_request(api_client, staff_user, subscription.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_subscription_response_correct(response.data, subscription)


@pytest.mark.django_db
def test_license_list_staff_user_200(api_client, staff_user, boolean_toggle):
    subscription, assigned_license, unassigned_license = _subscription_and_licenses()
    _assign_role_via_jwt_or_db(api_client, staff_user, subscription.enterprise_customer_uuid, boolean_toggle)

    response = _licenses_list_request(api_client, staff_user, subscription.uuid)

    assert status.HTTP_200_OK == response.status_code
    results_by_uuid = {item['uuid']: item for item in response.data['results']}
    assert len(results_by_uuid) == 2
    _assert_license_response_correct(results_by_uuid[str(unassigned_license.uuid)], unassigned_license)
    _assert_license_response_correct(results_by_uuid[str(assigned_license.uuid)], assigned_license)


@pytest.mark.django_db
def test_license_detail_staff_user_200(api_client, staff_user, boolean_toggle):
    subscription = SubscriptionPlanFactory.create()

    # Associate some licenses with the subscription
    subscription_license = LicenseFactory.create()
    subscription.licenses.set([subscription_license])

    _assign_role_via_jwt_or_db(api_client, staff_user, subscription.enterprise_customer_uuid, boolean_toggle)

    response = _licenses_detail_request(api_client, staff_user, subscription.uuid, subscription_license.uuid)
    assert status.HTTP_200_OK == response.status_code
    _assert_license_response_correct(response.data, subscription_license)


def _assign_role_via_jwt_or_db(
    client,
    user,
    enterprise_customer_uuid,
    assign_via_jwt,
    system_role=constants.SYSTEM_ENTERPRISE_ADMIN_ROLE,
    subscriptions_role=constants.SUBSCRIPTIONS_ADMIN_ROLE,
):
    """
    Helper method to assign the given role (defaulting to enterprise/subscriptions admin role)
    via a request JWT or DB role assignment class.
    """
    if assign_via_jwt:
        # In the request's JWT, grant the given role for this enterprise customer.
        set_jwt_cookie(
            client,
            user,
            [(system_role, str(enterprise_customer_uuid))]
        )
    else:
        # Assign a feature role to the user via database record.
        SubscriptionsRoleAssignment.objects.create(
            enterprise_customer_uuid=enterprise_customer_uuid,
            user=user,
            role=SubscriptionsFeatureRole.objects.get(name=subscriptions_role),
        )


def _subscription_and_licenses():
    """
    Helper method to return a SubscriptionPlan, an unassigned license, and an assigned license.
    """
    subscription = SubscriptionPlanFactory.create()

    # Associate some licenses with the subscription
    unassigned_license = LicenseFactory.create()
    assigned_license = LicenseFactory.create(status=constants.ASSIGNED, user_email='fake@fake.com')
    subscription.licenses.set([unassigned_license, assigned_license])

    return subscription, assigned_license, unassigned_license


def _create_subscription_plans(enterprise_customer_uuid):
    """
    Helper method to create several plans.  Returns the plans.
    """
    first_subscription = SubscriptionPlanFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    # Associate some unassigned and assigned licenses to the first subscription
    unassigned_licenses = LicenseFactory.create_batch(5)
    assigned_licenses = LicenseFactory.create_batch(2, status=constants.ASSIGNED)
    first_subscription.licenses.set(unassigned_licenses + assigned_licenses)
    # Create one more subscription for the enterprise with no licenses
    second_subscription = SubscriptionPlanFactory.create(enterprise_customer_uuid=enterprise_customer_uuid)
    # Create another subscription not associated with the enterprise that shouldn't show up
    SubscriptionPlanFactory.create()
    return first_subscription, second_subscription


@ddt.ddt
class LicenseViewSetActionTests(TestCase):
    """
    Tests for special actions on the LicenseViewSet.
    """
    def setUp(self):
        super().setUp()

        # API client setup
        self.api_client = APIClient()
        self.api_client.login(username=self.super_user.username, password=USER_PASSWORD)

        # Try to start every test with the regular user not being staff
        self.user.is_staff = False

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Set up a couple of users
        cls.user = UserFactory()
        cls.super_user = UserFactory(is_staff=True, is_superuser=True)

        # Routes setup
        cls.subscription_plan = SubscriptionPlanFactory()
        cls.assign_url = reverse('api:v1:licenses-assign', kwargs={'subscription_uuid': cls.subscription_plan.uuid})
        cls.remind_url = reverse('api:v1:licenses-remind', kwargs={'subscription_uuid': cls.subscription_plan.uuid})
        cls.remind_all_url = reverse(
            'api:v1:licenses-remind-all',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )
        cls.license_overview_url = reverse(
            'api:v1:licenses-overview',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )

        cls.revoke_license_url = reverse(
            'api:v1:licenses-revoke',
            kwargs={'subscription_uuid': cls.subscription_plan.uuid},
        )

    def _create_available_licenses(self, num_licenses=5):
        """
        Helper that creates `num_licenses` licenses that can be assigned, associated with the subscription.
        """
        unassigned_licenses = LicenseFactory.create_batch(num_licenses)
        self.subscription_plan.licenses.set(unassigned_licenses)

    def _assert_licenses_assigned(self, user_emails):
        """
        Helper that verifies that there is an assigned license associated with each email in `user_emails`.
        """
        for email in user_emails:
            user_license = self.subscription_plan.licenses.get(user_email=email)
            assert user_license.status == constants.ASSIGNED

    def _test_and_assert_forbidden_user(self, url, user_is_staff, mock_task):
        """
        Helper to login an unauthorized user, request an action URL, and assert that 403 response is returned.
        """
        self.user.is_staff = user_is_staff
        self.api_client.login(username=self.user.username, password=USER_PASSWORD)
        response = self.api_client.post(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_no_emails(self, mock_send_activation_email_task):
        """
        Verify the assign endpoint returns a 400 if no user emails are provided.
        """
        response = self.api_client.post(self.assign_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_activation_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    @ddt.data(True, False)
    def test_assign_non_admin_user(self, user_is_staff, mock_send_activation_email_task):
        """
        Verify the assign endpoint returns a 403 if a non-superuser with no
        admin roles makes the request, even if they're staff (for good measure).
        """
        self._test_and_assert_forbidden_user(self.assign_url, user_is_staff, mock_send_activation_email_task)

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_empty_emails(self, mock_send_activation_email_task):
        """
        Verify the assign endpoint returns a 400 if the list of emails provided is empty.
        """
        response = self.api_client.post(self.assign_url, {'user_emails': []})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_activation_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_invalid_emails(self, mock_send_activation_email_task):
        """
        Verify the assign endpoint returns a 400 if the list contains an invalid email.
        """
        response = self.api_client.post(self.assign_url, {'user_emails': ['lkajsdf']})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_activation_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_insufficient_licenses(self, mock_send_activation_email_task):
        """
        Verify the assign endpoint returns a 400 if there are not enough unassigned licenses to assign to.
        """
        # Create some assigned licenses which will not factor into the count
        assigned_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set(assigned_licenses)
        response = self.api_client.post(self.assign_url, {'user_emails': ['test@example.com']})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_activation_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_insufficient_licenses_deactivated(self, mock_send_activation_email_task):
        """
        Verify the endpoint returns a 400 if there are not enough licenses to assign to considering deactivated licenses
        """
        # Create a deactivated license that is not being assigned to
        deactivated_license = LicenseFactory.create(status=constants.DEACTIVATED, user_email='deactivated@example.com')
        self.subscription_plan.licenses.set([deactivated_license])
        response = self.api_client.post(self.assign_url, {'user_emails': ['test@example.com']})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_activation_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_already_associated_email(self, mock_send_activation_email_task):
        """
        Verify the assign endpoint returns a 400 if there is already a license associated with a provided email.

        Also checks that the conflict email is listed in the response.
        """
        self._create_available_licenses()
        assigned_email = 'test@example.com'
        assigned_license = LicenseFactory.create(user_email=assigned_email, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set([assigned_license])
        response = self.api_client.post(self.assign_url, {'user_emails': [assigned_email, 'unassigned@example.com']})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert assigned_email in response.data
        mock_send_activation_email_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    @ddt.data(True, False)
    def test_assign(self, use_superuser, mock_send_activation_email_task):
        """
        Verify the assign endpoint assigns licenses to the provided emails and sends activation emails.

        Also verifies that a greeting and closing can be sent.
        """
        # setUp() makes us use the superuser by default
        if not use_superuser:
            _assign_role_via_jwt_or_db(
                self.api_client,
                self.user,
                self.subscription_plan.enterprise_customer_uuid,
                assign_via_jwt=True
            )
            self.api_client.login(username=self.user.username, password=USER_PASSWORD)

        self._create_available_licenses()
        user_emails = ['bb8@mit.edu', 'test@example.com']
        greeting = 'hello'
        closing = 'goodbye'
        response = self.api_client.post(
            self.assign_url,
            {'greeting': greeting, 'closing': closing, 'user_emails': user_emails},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned(user_emails)

        task_args, _ = mock_send_activation_email_task.call_args
        actual_template_text, actual_emails, actual_subscription_uuid = task_args
        assert ['bb8@mit.edu', 'test@example.com'] == sorted(actual_emails)
        assert self.subscription_plan.uuid.hex == actual_subscription_uuid.replace('-', '')
        assert greeting == actual_template_text['greeting']
        assert closing == actual_template_text['closing']

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_dedupe_input(self, mock_send_activation_email_task):
        """
        Verify the assign endpoint deduplicates submitted emails.
        """
        self._create_available_licenses()
        user_email = 'test@example.com'
        user_emails = [user_email, user_email]
        greeting = 'hello'
        closing = 'goodbye'
        response = self.api_client.post(
            self.assign_url,
            {'greeting': greeting, 'closing': closing, 'user_emails': user_emails},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned([user_email])
        mock_send_activation_email_task.assert_called_with(
            {'greeting': greeting, 'closing': closing},
            [user_email],
            str(self.subscription_plan.uuid),
        )

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_to_deactivated_user(self, mock_send_activation_email_task):
        """
        Verify that the assign endpoint allows assigning a license to a user who previously had a license revoked.
        """
        user_email = 'test@example.com'
        deactivated_license = LicenseFactory.create(
            user_email=user_email,
            status=constants.DEACTIVATED,
            lms_user_id=1,
            last_remind_date=datetime.now(),
            activation_date=datetime.now(),
        )
        self.subscription_plan.licenses.set([deactivated_license])

        response = self.api_client.post(self.assign_url, {'user_emails': [user_email]})
        assert response.status_code == status.HTTP_200_OK

        # Verify all the attributes on the formerly deactivated license are correct
        deactivated_license.refresh_from_db()
        self._assert_licenses_assigned([user_email])
        assert deactivated_license.lms_user_id is None
        assert deactivated_license.last_remind_date is None
        assert deactivated_license.activation_date is None
        mock_send_activation_email_task.assert_called_with(
            {'greeting': '', 'closing': ''},
            [user_email],
            str(self.subscription_plan.uuid)
        )

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_email(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if no email is provided.
        """
        response = self.api_client.post(self.remind_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    @ddt.data(True, False)
    def test_remind_non_admin_user(self, user_is_staff, mock_send_reminder_email_task):
        """
        Verify the remind endpoint returns a 403 if a non-superuser with no
        admin roles makes the request, even if they're staff (for good measure).
        """
        self._test_and_assert_forbidden_user(self.remind_url, user_is_staff, mock_send_reminder_email_task)

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_invalid_email(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if an invalid email is provided.
        """
        response = self.api_client.post(self.remind_url, {'user_email': 'lkajsf'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_blank_email(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 400 if an empty string is submitted for an email.
        """
        response = self.api_client.post(self.remind_url, {'user_email': ''})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_license_for_user(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 404 if there is no license associated with the given email.
        """
        response = self.api_client.post(self.remind_url, {'user_email': 'nolicense@example.com'})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_no_pending_license_for_user(self, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint returns a 404 if there is no pending license associated with the given email.
        """
        email = 'test@example.com'
        activated_license = LicenseFactory.create(user_email=email, status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([activated_license])

        response = self.api_client.post(self.remind_url, {'user_email': email})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    @ddt.data(True, False)
    def test_remind(self, use_superuser, mock_send_reminder_emails_task):
        """
        Verify that the remind endpoint sends an email to the specified user with a pending license.
        Also verifies that a custom greeting and closing can be sent to the endpoint
        """
        # setUp() makes us use the superuser by default
        if not use_superuser:
            _assign_role_via_jwt_or_db(
                self.api_client,
                self.user,
                self.subscription_plan.enterprise_customer_uuid,
                assign_via_jwt=True
            )
            self.api_client.login(username=self.user.username, password=USER_PASSWORD)

        email = 'test@example.com'
        pending_license = LicenseFactory.create(user_email=email, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set([pending_license])

        greeting = 'Hello'
        closing = 'Goodbye'
        response = self.api_client.post(
            self.remind_url,
            {'user_email': email, 'greeting': greeting, 'closing': closing},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_send_reminder_emails_task.assert_called_with(
            {'greeting': greeting, 'closing': closing},
            [email],
            str(self.subscription_plan.uuid),
        )

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_all_no_pending_licenses(self, mock_send_reminder_emails_task):
        """
        Verify that the remind all endpoint returns a 404 if there are no pending licenses.
        """
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        self.subscription_plan.licenses.set(unassigned_licenses)

        response = self.api_client.post(self.remind_all_url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_send_reminder_emails_task.assert_not_called()

    @mock.patch('license_manager.apps.api.v1.views.send_reminder_email_task.delay')
    def test_remind_all(self, mock_send_reminder_emails_task):
        """
        Verify that the remind all endpoint sends an email to each user with a pending license.
        Also verifies that a custom greeting and closing can be sent to the endpoint.
        """
        # Create some pending and non-pending licenses for the subscription
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        pending_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        self.subscription_plan.licenses.set(unassigned_licenses + pending_licenses)

        greeting = 'Hello'
        closing = 'Goodbye'
        response = self.api_client.post(self.remind_all_url, {'greeting': greeting, 'closing': closing})
        assert response.status_code == status.HTTP_200_OK

        # Verify emails sent to only the pending licenses
        mock_send_reminder_emails_task.assert_called_with(
            {'greeting': greeting, 'closing': closing},
            [license.user_email for license in pending_licenses],
            str(self.subscription_plan.uuid),
        )

    def test_license_overview(self):
        """
        Verify that the overview endpoint for the state of all licenses in the subscription returns correctly
        """
        unassigned_licenses = LicenseFactory.create_batch(5, status=constants.UNASSIGNED)
        pending_licenses = LicenseFactory.create_batch(3, status=constants.ASSIGNED)
        deactivated_licenses = LicenseFactory.create_batch(1, status=constants.DEACTIVATED)
        self.subscription_plan.licenses.set(unassigned_licenses + pending_licenses + deactivated_licenses)

        response = self.api_client.get(self.license_overview_url)
        assert response.status_code == status.HTTP_200_OK

        expected_response = [
            {'status': constants.UNASSIGNED, 'count': len(unassigned_licenses)},
            {'status': constants.ASSIGNED, 'count': len(pending_licenses)},
            {'status': constants.DEACTIVATED, 'count': len(deactivated_licenses)},
        ]
        actual_response = response.data
        assert expected_response == actual_response

    @ddt.data(
        {'license_state': constants.ACTIVATED, 'expected_status': status.HTTP_204_NO_CONTENT, 'use_superuser': True},
        {'license_state': constants.ACTIVATED, 'expected_status': status.HTTP_204_NO_CONTENT, 'use_superuser': False},
        {'license_state': constants.ASSIGNED, 'expected_status': status.HTTP_204_NO_CONTENT, 'use_superuser': True},
        {'license_state': constants.ASSIGNED, 'expected_status': status.HTTP_204_NO_CONTENT, 'use_superuser': False},
        {'license_state': constants.DEACTIVATED, 'expected_status': status.HTTP_404_NOT_FOUND, 'use_superuser': True},
        {'license_state': constants.DEACTIVATED, 'expected_status': status.HTTP_404_NOT_FOUND, 'use_superuser': False},
    )
    @ddt.unpack
    def test_revoke_license_states(self, license_state, expected_status, use_superuser):
        """
        Test that revoking a license behaves correctly for different initial license states
        """
        # setUp() makes us use the superuser by default
        if not use_superuser:
            _assign_role_via_jwt_or_db(
                self.api_client,
                self.user,
                self.subscription_plan.enterprise_customer_uuid,
                assign_via_jwt=True
            )
            self.api_client.login(username=self.user.username, password=USER_PASSWORD)

        email = 'test@example.com'
        original_license = LicenseFactory.create(user_email=email, status=license_state)
        self.subscription_plan.licenses.set([original_license])

        response = self.api_client.post(self.revoke_license_url, {'user_email': email})
        assert response.status_code == expected_status
        deactivated_license = self.subscription_plan.licenses.get(uuid=original_license.uuid)
        assert deactivated_license.status == constants.DEACTIVATED

    def test_revoke_no_license(self):
        """
        Tests revoking a license when the user doesn't have a license
        """
        email = 'test@example.com'
        response = self.api_client.post(self.revoke_license_url, {'user_email': email})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @ddt.data(True, False)
    def test_revoke_non_admin_user(self, user_is_staff):
        """
        Verify the revoke endpoint returns a 403 if a non-superuser with no
        admin roles makes the request, even if they're staff (for good measure).
        """
        self.user.is_staff = user_is_staff
        self.api_client.login(username=self.user.username, password=USER_PASSWORD)
        response = self.api_client.post(self.revoke_license_url, {'user_email': 'foo@bar.com'})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @mock.patch('license_manager.apps.api.v1.views.send_activation_email_task.delay')
    def test_assign_after_license_revoke(self, mock_send_activation_email_task):
        """
        Verifies that assigning a license after revoking one works
        """
        email = 'test@example.com'
        original_license = LicenseFactory.create(user_email=email, status=constants.ACTIVATED)
        self.subscription_plan.licenses.set([original_license])
        response = self.api_client.post(self.revoke_license_url, {'user_email': email})
        assert response.status_code == status.HTTP_204_NO_CONTENT

        self._create_available_licenses()
        user_emails = ['bb8@mit.edu', email]
        greeting = 'hello'
        closing = 'goodbye'
        response = self.api_client.post(
            self.assign_url,
            {'greeting': greeting, 'closing': closing, 'user_emails': user_emails},
        )
        assert response.status_code == status.HTTP_200_OK
        self._assert_licenses_assigned(user_emails)

        task_args, _ = mock_send_activation_email_task.call_args
        actual_template_text, actual_emails, actual_subscription_uuid = task_args
        assert ['bb8@mit.edu', 'test@example.com'] == sorted(actual_emails)
        assert self.subscription_plan.uuid.hex == actual_subscription_uuid.replace('-', '')
        assert greeting == actual_template_text['greeting']
        assert closing == actual_template_text['closing']


@ddt.ddt
class LicenseSubsidyViewTests(TestCase):
    """
    Tests for the LicenseSubsidyView.
    """
    def setUp(self):
        super().setUp()

        # API client setup
        self.api_client = APIClient()
        self.api_client.login(username=self.user.username, password=USER_PASSWORD)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = UserFactory()
        cls.enterprise_customer_uuid = uuid4()
        cls.enterprise_catalog_uuid = uuid4()
        cls.course_key = 'testX'
        cls.lms_user_id = 1

        cls.base_url = reverse('api:v1:license-subsidy')

    @property
    def _decoded_jwt(self):
        return {'user_id': self.lms_user_id}

    def _assign_learner_roles(self):
        """
        Helper that assigns the correct learner role via JWT to the user.
        """
        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            self.enterprise_customer_uuid,
            assign_via_jwt=True,
            system_role=constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
            subscriptions_role=constants.SUBSCRIPTIONS_LEARNER_ROLE,
        )

    def _get_url_with_params(self, use_enterprise_customer=True, use_course_key=True):
        """
        Helper to add the appropriate query parameters to the base url if specified.
        """
        url = reverse('api:v1:license-subsidy')
        query_params = QueryDict(mutable=True)
        if use_enterprise_customer:
            query_params['enterprise_customer_uuid'] = self.enterprise_customer_uuid
        if use_course_key:
            query_params['course_key'] = self.course_key
        return url + '/?' + query_params.urlencode()

    def _create_active_subscription(self):
        """
        Returns an active subscription associated with the enterprise customer's catalog.
        """
        return SubscriptionPlanFactory.create(
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            enterprise_catalog_uuid=self.enterprise_catalog_uuid,
            is_active=True,
        )

    def _create_activated_license(self):
        """
        Returns an activated license for the tests' user.
        """
        return LicenseFactory.create(
            status=constants.ACTIVATED,
            lms_user_id=self.lms_user_id,
        )

    def test_get_subsidy_missing_role(self):
        """
        Verify the view returns a 403 for users without the learner role.
        """
        self._create_active_subscription()
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_subsidy_wrong_enterprise_customer(self):
        """
        Verify the view returns a 404 for users associated with a different enterprise than they are requesting.
        """
        # Create another enterprise and subscription the user has access to
        other_enterprise_uuid = uuid4()
        SubscriptionPlanFactory.create(enterprise_customer_uuid=other_enterprise_uuid, is_active=True)
        _assign_role_via_jwt_or_db(
            self.api_client,
            self.user,
            other_enterprise_uuid,
            assign_via_jwt=True,
            system_role=constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
            subscriptions_role=constants.SUBSCRIPTIONS_LEARNER_ROLE,
        )

        # Request the subsidy view for an enterprise the user does not have access to
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_subsidy_missing_enterprise_customer(self):
        """
        Verify the view returns a 404 if the enterprise customer query param is not provided.
        """
        self._assign_learner_roles()
        url = self._get_url_with_params(use_enterprise_customer=False)
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_subsidy_missing_course_key(self):
        """
        Verify the view returns a 400 if the course key query param is not provided.
        """
        self._assign_learner_roles()
        self._create_active_subscription()
        url = self._get_url_with_params(use_course_key=False)
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_subsidy_no_subscription_for_customer(self):
        """
        Verify the view returns a 404 if there is no subscription plan for the customer.
        """
        self._assign_learner_roles()
        SubscriptionPlanFactory.create(is_active=True)
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_subsidy_no_active_subscription_for_customer(self):
        """
        Verify the view returns a 404 if there is no active subscription plan for the customer.
        """
        self._assign_learner_roles()
        SubscriptionPlanFactory.create(
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            is_active=False,
        )
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.v1.views.get_decoded_jwt')
    def test_get_subsidy_no_license_for_user(self, mock_get_decoded_jwt):
        """
        Verify the view returns a 404 if the subscription has no license for the user.
        """
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        subscription_plan = self._create_active_subscription()
        LicenseFactory.create(subscription_plan=subscription_plan)
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.v1.views.get_decoded_jwt')
    def test_get_subsidy_no_activated_license_for_user(self, mock_get_decoded_jwt):
        """
        Verify the view returns a 404 if the subscription has no activated license for the user.
        """
        self._assign_learner_roles()
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        subscription_plan = self._create_active_subscription()
        LicenseFactory.create(
            subscription_plan=subscription_plan,
            status=constants.UNASSIGNED,
            lms_user_id=self.lms_user_id,
        )
        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api.v1.views.get_decoded_jwt')
    def test_get_subsidy_course_not_in_catalog(self, mock_get_decoded_jwt, mock_subscription_contains_content):
        """
        Verify the view returns a 404 if the subscription's catalog does not contain the given course.
        """
        self._assign_learner_roles()
        # Mock that the content was not found in the subscription's catalog
        mock_subscription_contains_content.return_value = False
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        subscription_plan = self._create_active_subscription()
        user_license = self._create_activated_license()
        subscription_plan.licenses.set([user_license])

        url = self._get_url_with_params()
        response = self.api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_subscription_contains_content.assert_called_with([self.course_key])

    def _assert_correct_subsidy_response(self, response, user_license, subscription_plan):
        """
        Verifies the license subsidy endpoint returns the correct response.
        """
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            'discount_type': constants.PERCENTAGE_DISCOUNT_TYPE,
            'discount_value': constants.LICENSE_DISCOUNT_VALUE,
            'status': constants.ACTIVATED,
            'subsidy_id': str(user_license.uuid),
            'start_date': str(subscription_plan.start_date),
            'expiration_date': str(subscription_plan.expiration_date),
            'enrollment_link': '',
        }

    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api.v1.views.get_decoded_jwt')
    def test_get_subsidy(self, mock_get_decoded_jwt, mock_subscription_contains_content):
        """
        Verify the view returns the correct response for a course in the user's subscription's catalog.
        """
        self._assign_learner_roles()
        # Mock that the content was found in the subscription's catalog
        mock_subscription_contains_content.return_value = True
        mock_get_decoded_jwt.return_value = self._decoded_jwt
        subscription_plan = self._create_active_subscription()
        user_license = self._create_activated_license()
        subscription_plan.licenses.set([user_license])

        url = self._get_url_with_params()
        response = self.api_client.get(url)
        self._assert_correct_subsidy_response(response, user_license, subscription_plan)
        mock_subscription_contains_content.assert_called_with([self.course_key])
